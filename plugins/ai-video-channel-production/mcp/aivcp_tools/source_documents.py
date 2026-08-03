from __future__ import annotations

import hashlib
import importlib
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

from .contracts import utc_now
from .errors import ToolError


DOCUMENT_ADAPTER_ID = "aivcp-local-document"
DOCUMENT_ADAPTER_VERSION = "1.0.0"
MAX_DOCUMENT_BYTES = 256 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_EXPANDED_BYTES = 512 * 1024 * 1024

_MEDIA_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".epub": "application/epub+zip",
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_CHAPTER_RE = re.compile(
    r"^(?:#{1,6}\s+.+|第[零〇一二三四五六七八九十百千万0-9]+[章节卷回部篇].*|"
    r"(?:chapter|part|book)\s+[0-9ivxlcdm]+\b.*)$",
    re.IGNORECASE,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _normalized_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip("\ufeff\n ")


def _language_family(language: str | None) -> str | None:
    if not language:
        return None
    lowered = language.lower()
    if lowered.startswith("ja"):
        return "ja"
    if lowered.startswith("zh"):
        return "zh"
    if lowered.startswith("en"):
        return "en"
    return lowered.split("-", 1)[0]


def _detect_language(text: str, requested: str | None) -> str:
    if requested:
        return requested
    sample = text[:100_000]
    kana = len(re.findall(r"[\u3040-\u30ff]", sample))
    han = len(re.findall(r"[\u3400-\u9fff]", sample))
    latin = len(re.findall(r"[A-Za-z]", sample))
    if kana >= 2 and kana >= latin // 20:
        return "ja"
    if han >= 2:
        return "zh"
    if latin >= 4:
        return "en"
    return "und"


def _decode_text(data: bytes, language: str | None) -> tuple[str, str]:
    bom_candidates = (
        (b"\xef\xbb\xbf", "utf-8-sig"),
        (b"\xff\xfe\x00\x00", "utf-32"),
        (b"\x00\x00\xfe\xff", "utf-32"),
        (b"\xff\xfe", "utf-16"),
        (b"\xfe\xff", "utf-16"),
    )
    for marker, encoding in bom_candidates:
        if data.startswith(marker):
            try:
                return data.decode(encoding), encoding
            except UnicodeDecodeError as exc:
                raise ToolError("DOCUMENT_ENCODING_INVALID", "文件的字节顺序标记与内容不一致。") from exc
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass

    family = _language_family(language)
    candidates = {
        "ja": ("cp932", "shift_jis", "gb18030", "windows-1252"),
        "zh": ("gb18030", "big5", "cp932", "windows-1252"),
        "en": ("windows-1252", "cp932", "gb18030"),
    }.get(family, ("cp932", "gb18030", "big5", "windows-1252"))
    decoded: list[tuple[int, str, str]] = []
    for encoding in candidates:
        try:
            value = data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        controls = sum(ord(char) < 32 and char not in "\n\r\t" for char in value)
        kana = len(re.findall(r"[\u3040-\u30ff]", value))
        han = len(re.findall(r"[\u3400-\u9fff]", value))
        latin = len(re.findall(r"[A-Za-z]", value))
        language_score = kana * 4 + han if encoding in {"cp932", "shift_jis"} else 0
        language_score += han * 2 if encoding in {"gb18030", "big5"} else 0
        language_score += latin if encoding == "windows-1252" else 0
        decoded.append((language_score - controls * 100, encoding, value))
    if not decoded:
        raise ToolError(
            "DOCUMENT_ENCODING_UNSUPPORTED",
            "无法可靠识别文本编码；请另存为 UTF-8 后重新导入。",
            details={"supportedFallbacks": list(candidates)},
        )
    _, encoding, value = max(decoded, key=lambda item: item[0])
    return value, encoding


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n(?:[ \t]*\n)+", text) if part.strip()]


def _text_units(text: str, *, markdown: bool = False) -> tuple[list[dict[str, Any]], str]:
    lines = text.splitlines()
    headings = [index for index, line in enumerate(lines) if _CHAPTER_RE.match(line.strip())]
    if not headings:
        paragraphs = _paragraphs(text)
        return (
            [
                {
                    "index": 1,
                    "title": None,
                    "paragraphCount": len(paragraphs),
                    "characterCount": len(text),
                    "complete": True,
                }
            ],
            "paragraph",
        )

    starts = ([0] if headings[0] != 0 else []) + headings
    starts = sorted(set(starts))
    units: list[dict[str, Any]] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        body = "\n".join(lines[start:end]).strip()
        heading = lines[start].strip() if start in headings else None
        if markdown and heading:
            heading = re.sub(r"^#{1,6}\s+", "", heading).strip()
        units.append(
            {
                "index": position + 1,
                "title": heading,
                "paragraphCount": len(_paragraphs(body)),
                "characterCount": len(body),
                "complete": True,
            }
        )
    return units, "chapter"


class _BlockTextParser(HTMLParser):
    _BLOCK_TAGS = {
        "address",
        "article",
        "aside",
        "blockquote",
        "br",
        "div",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "hr",
        "li",
        "p",
        "pre",
        "section",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "svg"}:
            self._ignored_depth += 1
        if not self._ignored_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        if not self._ignored_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self.parts.append(data)

    def text(self) -> str:
        raw = "".join(self.parts)
        raw = re.sub(r"[ \t\f\v]+", " ", raw)
        raw = re.sub(r" *\n *", "\n", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return _normalized_text(raw)


def _html_text(data: bytes) -> str:
    match = re.search(br"<\?xml[^>]+encoding=[\"']([^\"']+)", data[:512], re.IGNORECASE)
    encoding = match.group(1).decode("ascii", errors="ignore") if match else "utf-8"
    try:
        html = data.decode(encoding)
    except (LookupError, UnicodeDecodeError):
        html = data.decode("utf-8", errors="replace")
    parser = _BlockTextParser()
    parser.feed(html)
    return parser.text()


def _validate_archive(archive: zipfile.ZipFile) -> None:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_MEMBERS:
        raise ToolError("DOCUMENT_ARCHIVE_UNSAFE", "文档归档包含过多文件，已停止读取。")
    total = 0
    for info in infos:
        member = PurePosixPath(info.filename.replace("\\", "/"))
        if member.is_absolute() or ".." in member.parts:
            raise ToolError("DOCUMENT_ARCHIVE_UNSAFE", "文档归档包含不安全路径，已停止读取。")
        total += info.file_size
        if total > MAX_ARCHIVE_EXPANDED_BYTES:
            raise ToolError("DOCUMENT_ARCHIVE_TOO_LARGE", "文档解压后超过安全大小上限。")


@dataclass(slots=True)
class _ExtractedDocument:
    text: str
    encoding: str
    title: str | None
    author: str | None
    language: str | None
    unit_type: str
    units: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    complete: bool
    blocked_reason: dict[str, Any] | None = None


class DocumentAdapter:
    """Normalize user-authorized local documents without writing to the source library."""

    adapter_id = DOCUMENT_ADAPTER_ID
    adapter_version = DOCUMENT_ADAPTER_VERSION
    supported_extensions = tuple(_MEDIA_TYPES)

    def collect(
        self,
        path: str | Path,
        *,
        language: str | None = None,
        authorized: bool = True,
    ) -> dict[str, Any]:
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise ToolError("DOCUMENT_NOT_FOUND", "找不到要导入的本地文件。")
        extension = source.suffix.lower()
        if extension not in _MEDIA_TYPES:
            raise ToolError(
                "DOCUMENT_TYPE_UNSUPPORTED",
                "本地资料类型不受支持。",
                details={"extension": extension, "supported": list(self.supported_extensions)},
            )
        size = source.stat().st_size
        if size > MAX_DOCUMENT_BYTES:
            raise ToolError(
                "DOCUMENT_TOO_LARGE",
                "本地文件超过单文件安全读取上限。",
                details={"sizeBytes": size, "maximumBytes": MAX_DOCUMENT_BYTES},
            )
        collected_at = utc_now()
        if not authorized:
            return {
                "sourceType": "local-file",
                "status": "BLOCKED",
                "title": source.stem,
                "language": language or "und",
                "platform": "local-file",
                "platformId": None,
                "canonicalUrl": None,
                "canonicalLocator": str(source),
                "provenance": {
                    "kind": "local-file",
                    "locator": str(source),
                    "collectedAt": collected_at,
                    "adapterId": self.adapter_id,
                    "adapterVersion": self.adapter_version,
                    "acquisitionMethod": "authorization-check-only",
                },
                "rightsBoundary": {
                    "accessLevel": "unknown",
                    "basis": "User authorization is required before reading or hashing content.",
                    "confirmedByUser": False,
                },
                "metadata": {
                    "fileName": source.name,
                    "extension": extension,
                    "sizeBytes": size,
                    "originalSha256": None,
                },
                "assets": [],
                "contentSha256": None,
                "report": {
                    "complete": False,
                    "failure": {
                        "code": "DOCUMENT_USER_AUTHORIZATION_REQUIRED",
                        "message": "需要用户确认有权处理该本地文件后才能读取正文。",
                        "retryable": True,
                    },
                    "nextActions": ["confirm-user-authorization"],
                    "sourceBoundary": "The file was located but its bytes were not read or hashed.",
                },
            }
        raw = source.read_bytes()
        original_hash = _sha256(raw)
        base = {
            "sourceType": "local-file",
            "title": source.stem,
            "language": language or "und",
            "platform": "local-file",
            "platformId": original_hash,
            "canonicalUrl": None,
            "canonicalLocator": str(source),
            "provenance": {
                "kind": "local-file",
                "locator": str(source),
                "collectedAt": collected_at,
                "adapterId": self.adapter_id,
                "adapterVersion": self.adapter_version,
                "acquisitionMethod": "user-authorized-local-import",
            },
            "rightsBoundary": {
                "accessLevel": "user-authorized" if authorized else "unknown",
                "basis": "User supplied the local file for processing." if authorized else "User authorization is required before reading content.",
                "confirmedByUser": bool(authorized),
            },
            "metadata": {
                "fileName": source.name,
                "extension": extension,
                "sizeBytes": size,
                "originalSha256": original_hash,
            },
            "contentSha256": None,
        }

        try:
            extracted = self._extract(extension, raw, source, language)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(
                "DOCUMENT_EXTRACTION_FAILED",
                "本地文档解析失败；原文件未被改写。",
                details={"documentType": extension, "errorType": type(exc).__name__},
            ) from exc

        text = _normalized_text(extracted.text)
        detected_language = _detect_language(text, language or extracted.language)
        normalized_bytes = text.encode("utf-8")
        content_hash = _sha256(normalized_bytes) if text else None
        extracted_count = sum(1 for unit in extracted.units if unit.get("complete"))
        structure = {
            "unitType": extracted.unit_type,
            "expectedUnitCount": len(extracted.units),
            "extractedUnitCount": extracted_count,
            "paragraphCount": len(_paragraphs(text)),
            "units": extracted.units,
        }
        metadata = {
            **base["metadata"],
            "encoding": extracted.encoding,
            "detectedLanguage": detected_language,
            "declaredLanguage": extracted.language,
            "title": extracted.title or source.stem,
            "author": extracted.author,
            "structure": structure,
        }
        status = "CONTENT_READY"
        if extracted.blocked_reason and not text:
            status = "BLOCKED"
        elif not extracted.complete or not text:
            status = "PARTIAL"
        assets: list[dict[str, Any]] = [
            {
                "role": "raw",
                "mediaType": _MEDIA_TYPES[extension],
                "filename": source.name,
                "sourcePath": str(source),
                "sha256": original_hash,
                "sizeBytes": size,
            }
        ]
        if text:
            assets.append(
                {
                    "role": "normalized",
                    "mediaType": "text/plain;charset=utf-8",
                    "filename": "normalized.txt",
                    "data": text,
                    "sha256": content_hash,
                    "sizeBytes": len(normalized_bytes),
                }
            )
        return {
            **base,
            "status": status,
            "title": extracted.title or source.stem,
            "language": detected_language,
            "metadata": metadata,
            "assets": assets,
            "contentSha256": content_hash,
            "report": {
                "complete": status == "CONTENT_READY",
                "documentType": extension.removeprefix("."),
                "originalPreserved": True,
                "normalizedEncoding": "utf-8",
                "integrity": structure,
                "warnings": extracted.warnings,
                "failure": extracted.blocked_reason,
                "sourceBoundary": "Only the user-supplied file was read; no external source was inferred.",
                "nextActions": (
                    ["provide-ocr-text-or-searchable-pdf"]
                    if status == "BLOCKED" and extension == ".pdf"
                    else ["provide-complete-file"]
                    if status == "PARTIAL"
                    else []
                ),
            },
        }

    def _extract(
        self,
        extension: str,
        raw: bytes,
        source: Path,
        language: str | None,
    ) -> _ExtractedDocument:
        if extension in {".txt", ".md"}:
            text, encoding = _decode_text(raw, language)
            text = _normalized_text(text)
            units, unit_type = _text_units(text, markdown=extension == ".md")
            return _ExtractedDocument(
                text=text,
                encoding=encoding,
                title=None,
                author=None,
                language=language,
                unit_type=unit_type,
                units=units,
                warnings=[],
                complete=bool(text),
            )
        if extension == ".epub":
            return self._extract_epub(source)
        if extension == ".docx":
            return self._extract_docx(source)
        if extension == ".pdf":
            return self._extract_pdf(source)
        raise AssertionError(extension)

    def _extract_epub(self, source: Path) -> _ExtractedDocument:
        try:
            archive = zipfile.ZipFile(source)
        except (zipfile.BadZipFile, OSError) as exc:
            raise ToolError("DOCUMENT_EPUB_INVALID", "EPUB 不是有效的 ZIP/EPUB 文件。") from exc
        with archive:
            _validate_archive(archive)
            try:
                container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            except (KeyError, ElementTree.ParseError) as exc:
                raise ToolError("DOCUMENT_EPUB_INVALID", "EPUB 缺少有效的 container.xml。") from exc
            rootfile = next(
                (element.attrib.get("full-path") for element in container.iter() if element.tag.endswith("rootfile")),
                None,
            )
            if not rootfile or rootfile not in archive.namelist():
                raise ToolError("DOCUMENT_EPUB_INVALID", "EPUB 无法定位 OPF 包文档。")
            try:
                package = ElementTree.fromstring(archive.read(rootfile))
            except ElementTree.ParseError as exc:
                raise ToolError("DOCUMENT_EPUB_INVALID", "EPUB 的 OPF 包文档无效。") from exc
            base_dir = PurePosixPath(rootfile).parent
            metadata_values: dict[str, str] = {}
            manifest: dict[str, str] = {}
            spine: list[str] = []
            for element in package.iter():
                local = element.tag.rsplit("}", 1)[-1]
                if local in {"title", "creator", "language"} and element.text and local not in metadata_values:
                    metadata_values[local] = element.text.strip()
                elif local == "item" and element.attrib.get("id") and element.attrib.get("href"):
                    manifest[element.attrib["id"]] = element.attrib["href"]
                elif local == "itemref" and element.attrib.get("idref"):
                    spine.append(element.attrib["idref"])

            warnings: list[dict[str, Any]] = []
            units: list[dict[str, Any]] = []
            chapters: list[str] = []
            for item_id in spine:
                href = manifest.get(item_id)
                if not href:
                    warnings.append({"code": "EPUB_SPINE_ITEM_MISSING", "itemId": item_id})
                    continue
                member = str(base_dir.joinpath(PurePosixPath(href))).replace("\\", "/")
                try:
                    chapter_text = _html_text(archive.read(member))
                except KeyError:
                    warnings.append({"code": "EPUB_CONTENT_FILE_MISSING", "member": member})
                    continue
                index = len(units) + 1
                title = next((line.strip() for line in chapter_text.splitlines() if line.strip()), None)
                complete = bool(chapter_text)
                units.append(
                    {
                        "index": index,
                        "title": title,
                        "sourceMember": member,
                        "paragraphCount": len(_paragraphs(chapter_text)),
                        "characterCount": len(chapter_text),
                        "complete": complete,
                    }
                )
                if chapter_text:
                    chapters.append(chapter_text)
            if not spine:
                raise ToolError("DOCUMENT_EPUB_INVALID", "EPUB 没有可读取的 spine 章节顺序。")
            text = _normalized_text("\n\n".join(chapters))
            return _ExtractedDocument(
                text=text,
                encoding="xml-declared/utf-8-normalized",
                title=metadata_values.get("title"),
                author=metadata_values.get("creator"),
                language=metadata_values.get("language"),
                unit_type="chapter",
                units=units,
                warnings=warnings,
                complete=bool(text) and len(units) == len(spine) and all(unit["complete"] for unit in units),
            )

    def _extract_docx(self, source: Path) -> _ExtractedDocument:
        try:
            archive = zipfile.ZipFile(source)
        except (zipfile.BadZipFile, OSError) as exc:
            raise ToolError("DOCUMENT_DOCX_INVALID", "DOCX 不是有效的 Open XML 文件。") from exc
        with archive:
            _validate_archive(archive)
            try:
                document_root = ElementTree.fromstring(archive.read("word/document.xml"))
            except (KeyError, ElementTree.ParseError) as exc:
                raise ToolError("DOCUMENT_DOCX_INVALID", "DOCX 缺少有效的 word/document.xml。") from exc
            core: dict[str, str] = {}
            try:
                core_root = ElementTree.fromstring(archive.read("docProps/core.xml"))
                for element in core_root.iter():
                    local = element.tag.rsplit("}", 1)[-1]
                    if local in {"title", "creator", "language"} and element.text:
                        core[local] = element.text.strip()
            except (KeyError, ElementTree.ParseError):
                pass

            word_ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paragraph_rows: list[tuple[str | None, str]] = []
            for paragraph in document_root.iter(f"{word_ns}p"):
                style_element = paragraph.find(f"./{word_ns}pPr/{word_ns}pStyle")
                style = style_element.attrib.get(f"{word_ns}val") if style_element is not None else None
                parts: list[str] = []
                for node in paragraph.iter():
                    if node.tag == f"{word_ns}t" and node.text:
                        parts.append(node.text)
                    elif node.tag == f"{word_ns}tab":
                        parts.append("\t")
                    elif node.tag in {f"{word_ns}br", f"{word_ns}cr"}:
                        parts.append("\n")
                value = _normalized_text("".join(parts))
                if value:
                    paragraph_rows.append((style, value))
            text = _normalized_text("\n\n".join(value for _, value in paragraph_rows))
            heading_indexes = [
                index
                for index, (style, value) in enumerate(paragraph_rows)
                if (style and style.lower().startswith("heading")) or _CHAPTER_RE.match(value)
            ]
            units: list[dict[str, Any]] = []
            if heading_indexes:
                starts = ([0] if heading_indexes[0] else []) + heading_indexes
                starts = sorted(set(starts))
                for position, start in enumerate(starts):
                    end = starts[position + 1] if position + 1 < len(starts) else len(paragraph_rows)
                    values = [value for _, value in paragraph_rows[start:end]]
                    units.append(
                        {
                            "index": position + 1,
                            "title": values[0] if start in heading_indexes and values else None,
                            "paragraphCount": len(values),
                            "characterCount": len("\n\n".join(values)),
                            "complete": True,
                        }
                    )
                unit_type = "chapter"
            else:
                units = [
                    {
                        "index": index,
                        "title": None,
                        "paragraphCount": 1,
                        "characterCount": len(value),
                        "complete": True,
                    }
                    for index, (_, value) in enumerate(paragraph_rows, 1)
                ]
                unit_type = "paragraph"
            return _ExtractedDocument(
                text=text,
                encoding="openxml/utf-8-normalized",
                title=core.get("title"),
                author=core.get("creator"),
                language=core.get("language"),
                unit_type=unit_type,
                units=units,
                warnings=[],
                complete=bool(text),
            )

    def _extract_pdf(self, source: Path) -> _ExtractedDocument:
        try:
            pypdf = importlib.import_module("pypdf")
        except ImportError as exc:
            raise ToolError(
                "DOCUMENT_PDF_EXTRACTOR_UNAVAILABLE",
                "PDF 文本提取组件未安装；原文件未被改写。",
                retryable=True,
                details={"requiredComponent": "pypdf"},
            ) from exc
        try:
            reader = pypdf.PdfReader(str(source))
        except Exception as exc:
            raise ToolError(
                "DOCUMENT_PDF_INVALID",
                "PDF 无法打开或结构无效。",
                details={"errorType": type(exc).__name__},
            ) from exc
        if getattr(reader, "is_encrypted", False):
            try:
                unlocked = reader.decrypt("")
            except Exception:
                unlocked = False
            if not unlocked:
                return _ExtractedDocument(
                    text="",
                    encoding="pdf-text-extraction",
                    title=None,
                    author=None,
                    language=None,
                    unit_type="page",
                    units=[],
                    warnings=[],
                    complete=False,
                    blocked_reason={
                        "code": "DOCUMENT_PDF_ENCRYPTED",
                        "message": "PDF 受密码或 DRM 保护，系统不会绕过限制。",
                        "retryable": False,
                    },
                )
        page_texts: list[str] = []
        units: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        for index, page in enumerate(reader.pages, 1):
            try:
                value = _normalized_text(page.extract_text() or "")
            except Exception as exc:
                value = ""
                warnings.append({"code": "PDF_PAGE_EXTRACTION_FAILED", "page": index, "errorType": type(exc).__name__})
            units.append(
                {
                    "index": index,
                    "title": None,
                    "paragraphCount": len(_paragraphs(value)),
                    "characterCount": len(value),
                    "complete": bool(value),
                }
            )
            page_texts.append(value)
        text = _normalized_text("\n\n\f\n\n".join(page_texts))
        metadata = getattr(reader, "metadata", None) or {}
        title = metadata.get("/Title") if hasattr(metadata, "get") else None
        author = metadata.get("/Author") if hasattr(metadata, "get") else None
        blocked = None
        if not text:
            blocked = {
                "code": "DOCUMENT_PDF_NO_SEARCHABLE_TEXT",
                "message": "PDF 没有可提取文字；扫描版需要 OCR 或用户补充文字文件。",
                "retryable": True,
            }
        return _ExtractedDocument(
            text=text,
            encoding="pdf-text-extraction/utf-8-normalized",
            title=str(title) if title else None,
            author=str(author) if author else None,
            language=None,
            unit_type="page",
            units=units,
            warnings=warnings,
            complete=bool(text) and all(unit["complete"] for unit in units),
            blocked_reason=blocked,
        )


__all__ = [
    "DOCUMENT_ADAPTER_ID",
    "DOCUMENT_ADAPTER_VERSION",
    "DocumentAdapter",
]
