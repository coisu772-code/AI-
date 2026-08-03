from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit

from .contracts import utc_now
from .errors import ToolError
from .source_documents import DocumentAdapter


SITE_REGISTRY_ADAPTER_ID = "aivcp-site-registry"
SITE_REGISTRY_ADAPTER_VERSION = "1.0.0"
DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parents[2] / "assets" / "site-capability-manifest-v1.json"
_ACCESS_LEVELS = {"metadata-only", "public-domain", "open-license", "user-authorized", "unknown"}
_AUTOMATED_METADATA_METHODS = {
    "official-api",
    "official-work-card",
    "mediawiki-api",
    "official-offline-catalog-or-opds",
}


class SiteFetcher(Protocol):
    def __call__(self, request_url: str, capability: dict[str, Any]) -> dict[str, Any]: ...


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _stable_hash(value: Any) -> str:
    return _sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "\n".join(line.rstrip() for line in value.splitlines())
    return value.strip("\ufeff\n ")


def _detect_language(text: str, requested: str | None, default: str) -> str:
    if requested:
        return requested
    sample = text[:50_000]
    if len(re.findall(r"[\u3040-\u30ff]", sample)) >= 2:
        return "ja"
    if len(re.findall(r"[\u3400-\u9fff]", sample)) >= 2:
        return "zh"
    if len(re.findall(r"[A-Za-z]", sample)) >= 4:
        return "en"
    return default


def _decode_body(body: bytes, media_type: str | None) -> tuple[str, str]:
    charset_match = re.search(r"charset\s*=\s*[\"']?([^;\s\"']+)", media_type or "", re.IGNORECASE)
    candidates = [charset_match.group(1)] if charset_match else []
    candidates.extend(["utf-8-sig", "cp932", "gb18030", "windows-1252"])
    tried: set[str] = set()
    for encoding in candidates:
        lowered = encoding.lower()
        if lowered in tried:
            continue
        tried.add(lowered)
        try:
            return body.decode(encoding), encoding
        except (LookupError, UnicodeDecodeError):
            continue
    raise ToolError("SITE_RESPONSE_ENCODING_UNSUPPORTED", "站点响应编码无法安全识别。")


class _MetadataHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.in_title = False
        self.meta: dict[str, str] = {}
        self.text_parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value for key, value in attrs if value is not None}
        if tag in {"script", "style", "svg"}:
            self._ignored_depth += 1
        if tag == "title":
            self.in_title = True
        if tag == "meta":
            key = (values.get("property") or values.get("name") or "").lower()
            content = values.get("content")
            if key and content and key not in self.meta:
                self.meta[key] = content.strip()
        if not self._ignored_depth and tag in {"p", "div", "li", "h1", "h2", "h3", "br", "section"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag in {"script", "style", "svg"} and self._ignored_depth:
            self._ignored_depth -= 1
        if not self._ignored_depth and tag in {"p", "div", "li", "h1", "h2", "h3", "section"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.title_parts.append(data)
        if not self._ignored_depth:
            self.text_parts.append(data)

    def metadata(self) -> dict[str, Any]:
        title = self.meta.get("og:title") or _normalize_text("".join(self.title_parts)) or None
        description = self.meta.get("og:description") or self.meta.get("description")
        author = self.meta.get("author") or self.meta.get("book:author")
        return {key: value for key, value in {"title": title, "description": description, "author": author}.items() if value}

    def text(self) -> str:
        value = "".join(self.text_parts)
        value = re.sub(r"[ \t\f\v]+", " ", value)
        value = re.sub(r" *\n *", "\n", value)
        value = re.sub(r"\n{3,}", "\n\n", value)
        return _normalize_text(value)


@dataclass(frozen=True, slots=True)
class _MatchedSite:
    capability: dict[str, Any]
    canonical_url: str
    platform_id: str


class SiteAdapterRegistry:
    """Policy-aware adapter registry for the first Japanese, Chinese, and English site packs.

    The registry performs no persistence. A caller may inject a policy-aware, read-only
    ``fetcher`` for official APIs/download channels. Commercial-site full text is accepted
    only through ``supplied_file`` with explicit user authorization.
    """

    adapter_id = SITE_REGISTRY_ADAPTER_ID
    adapter_version = SITE_REGISTRY_ADAPTER_VERSION

    def __init__(
        self,
        manifest_path: str | Path | None = None,
        *,
        fetcher: SiteFetcher | None = None,
        document_adapter: DocumentAdapter | None = None,
        today: date | None = None,
    ) -> None:
        self.manifest_path = Path(manifest_path or DEFAULT_MANIFEST_PATH).resolve()
        self.fetcher = fetcher
        self.document_adapter = document_adapter or DocumentAdapter()
        self.today = today or date.today()
        self.manifest = self._load_manifest()
        self._sites = {site["siteId"]: site for site in self.manifest["sites"]}
        self._hosts: dict[str, str] = {}
        for site in self.manifest["sites"]:
            for host in site["hosts"]:
                self._hosts[host.lower()] = site["siteId"]

    @classmethod
    def from_environment(cls, *, fetcher: SiteFetcher | None = None) -> "SiteAdapterRegistry":
        configured = os.environ.get("AIVCP_SITE_CAPABILITY_MANIFEST")
        return cls(configured or DEFAULT_MANIFEST_PATH, fetcher=fetcher)

    def _load_manifest(self) -> dict[str, Any]:
        try:
            value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ToolError("SITE_CAPABILITY_MANIFEST_INVALID", "站点能力清单无法读取或不是有效 JSON。") from exc
        if value.get("schemaVersion") != "1.0.0" or value.get("manifestVersion") != "1.0.0":
            raise ToolError("SITE_CAPABILITY_MANIFEST_INCOMPATIBLE", "站点能力清单版本不受支持。")
        sites = value.get("sites")
        if not isinstance(sites, list) or len(sites) != 9:
            raise ToolError("SITE_CAPABILITY_MANIFEST_INVALID", "站点能力清单必须包含首版九个站点。")
        identifiers: set[str] = set()
        hosts: set[str] = set()
        for site in sites:
            required = {
                "siteId",
                "displayName",
                "market",
                "defaultLanguage",
                "hosts",
                "adapterVersion",
                "capabilityLevel",
                "capabilities",
                "allowedFields",
                "acquisitionMethods",
                "rightsPolicy",
                "rules",
                "rateLimit",
                "fallback",
            }
            if not isinstance(site, dict) or not required.issubset(site):
                raise ToolError("SITE_CAPABILITY_MANIFEST_INVALID", "站点能力条目缺少必填字段。")
            if site["siteId"] in identifiers or site["market"] not in {"ja", "zh", "en"}:
                raise ToolError("SITE_CAPABILITY_MANIFEST_INVALID", "站点 ID 重复或市场代码无效。")
            identifiers.add(site["siteId"])
            for host in site["hosts"]:
                lowered = host.lower()
                if lowered in hosts:
                    raise ToolError("SITE_CAPABILITY_MANIFEST_INVALID", "多个适配器声明了相同主机。")
                hosts.add(lowered)
        if {site["market"] for site in sites} != {"ja", "zh", "en"}:
            raise ToolError("SITE_CAPABILITY_MANIFEST_INVALID", "站点能力清单必须覆盖日中英三个市场。")
        return value

    def _effective_capability(self, site: dict[str, Any]) -> dict[str, Any]:
        result = deepcopy(site)
        rules = site["rules"]
        try:
            verified = datetime.strptime(rules["verifiedAt"], "%Y-%m-%d").date()
            max_age = int(rules.get("maxAgeDays", self.manifest["defaultRuleMaxAgeDays"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ToolError("SITE_CAPABILITY_MANIFEST_INVALID", "站点规则核验日期无效。") from exc
        age = (self.today - verified).days
        expired = age > max_age
        unclear = "unclear" in str(site["rules"].get("certainty", ""))
        result["ruleAgeDays"] = age
        result["ruleExpired"] = expired
        result["ruleUnclear"] = unclear
        result["configuredCapabilityLevel"] = site["capabilityLevel"]
        result["effectiveCapabilityLevel"] = site["fallback"] if expired or unclear else site["capabilityLevel"]
        result["fullTextEnabled"] = bool(
            not expired
            and not unclear
            and site["capabilityLevel"] == "public-full-text-conditional"
            and site["capabilities"].get("automatedFullText")
        )
        if expired:
            result["degradationReason"] = "rules-verification-expired"
        elif unclear:
            result["degradationReason"] = "rules-unclear-conservative"
        else:
            result["degradationReason"] = None
        return result

    def list_capabilities(self, *, market: str | None = None) -> dict[str, Any]:
        sites = [self._effective_capability(site) for site in self.manifest["sites"]]
        if market:
            sites = [site for site in sites if site["market"] == market]
        return {
            "schemaVersion": self.manifest["schemaVersion"],
            "manifestVersion": self.manifest["manifestVersion"],
            "manifestPath": str(self.manifest_path),
            "evaluatedAt": self.today.isoformat(),
            "sites": sites,
        }

    def capabilities(self, *, market: str | None = None) -> dict[str, Any]:
        return self.list_capabilities(market=market)

    def canonicalize(self, locator: str) -> dict[str, str]:
        matched = self._match(locator)
        return {
            "siteId": matched.capability["siteId"],
            "canonicalUrl": matched.canonical_url,
            "platformId": matched.platform_id,
        }

    def _match(self, locator: str) -> _MatchedSite:
        if not isinstance(locator, str) or not locator.strip():
            raise ToolError("SITE_LOCATOR_INVALID", "小说网页地址不能为空。")
        parsed = urlsplit(locator.strip())
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ToolError("SITE_LOCATOR_INVALID", "小说网页必须是公开的 HTTP(S) 地址。")
        host = parsed.hostname.lower().rstrip(".")
        site_id = self._hosts.get(host)
        if not site_id:
            raise ToolError("SITE_NOT_SUPPORTED", "该小说网站尚未进入首版能力清单。", details={"host": host})
        site = self._effective_capability(self._sites[site_id])
        canonical_url, platform_id = self._canonical_for_site(site_id, parsed)
        return _MatchedSite(site, canonical_url, platform_id)

    def _canonical_for_site(self, site_id: str, parsed: Any) -> tuple[str, str]:
        path = re.sub(r"/{2,}", "/", unquote(parsed.path or "/"))
        query_items = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.lower().startswith("utm_") and key.lower() not in {"ref", "source", "from"}
        ]
        host = parsed.hostname.lower().rstrip(".")
        platform_id: str | None = None
        if site_id == "syosetu":
            match = re.search(r"/(n[0-9a-z]+)/?", path, re.IGNORECASE)
            if match:
                platform_id = match.group(1).upper()
                host, path, query_items = "ncode.syosetu.com", f"/{platform_id.lower()}/", []
        elif site_id == "kakuyomu":
            match = re.search(r"/works/(\d+)", path)
            if match:
                platform_id = match.group(1)
                host, path, query_items = "kakuyomu.jp", f"/works/{platform_id}", []
        elif site_id == "aozora":
            match = re.search(r"/card(\d+)\.html", path, re.IGNORECASE) or re.search(r"/files/(\d+)", path)
            if match:
                platform_id = match.group(1)
            host, query_items = "www.aozora.gr.jp", []
        elif site_id == "qidian":
            match = re.search(r"/(?:info|book)/(\d+)", path)
            if match:
                platform_id = match.group(1)
                host, path, query_items = "book.qidian.com", f"/info/{platform_id}", []
        elif site_id == "fanqie":
            match = re.search(r"/(?:page|reader)/(\d+)", path)
            if match:
                platform_id = match.group(1)
                host, path, query_items = "fanqienovel.com", f"/page/{platform_id}", []
        elif site_id == "zh-wikisource":
            match = re.search(r"/wiki/(.+)", path)
            if match:
                title = re.sub(r"[ _]+", "_", match.group(1).strip(" /"))
                platform_id = title
                host, path, query_items = "zh.wikisource.org", f"/wiki/{quote(title, safe='/:()_-')}", []
        elif site_id == "royal-road":
            match = re.search(r"/fiction/(\d+)", path)
            if match:
                platform_id = match.group(1)
                host, path, query_items = "www.royalroad.com", f"/fiction/{platform_id}", []
        elif site_id == "scribble-hub":
            match = re.search(r"/series/(\d+)", path)
            if match:
                platform_id = match.group(1)
                host, path, query_items = "www.scribblehub.com", f"/series/{platform_id}/", []
        elif site_id == "project-gutenberg":
            match = re.search(r"/(?:ebooks|epub)/(\d+)", path)
            if match:
                platform_id = match.group(1)
                host, path, query_items = "www.gutenberg.org", f"/ebooks/{platform_id}", []
        canonical = urlunsplit(("https", host, quote(path, safe="/%:()_-.", encoding="utf-8"), urlencode(sorted(query_items)), ""))
        return canonical, platform_id or f"url-{_sha256(canonical.encode('utf-8'))[:24]}"

    def collect(
        self,
        locator: str,
        *,
        language: str | None = None,
        user_authorized: bool = False,
        supplied_file: str | Path | None = None,
    ) -> dict[str, Any]:
        matched = self._match(locator)
        site = matched.capability
        collected_at = utc_now()
        base = self._base_result(matched, collected_at, language)
        if supplied_file is not None:
            if not user_authorized:
                return self._blocked(
                    base,
                    "SITE_USER_IMPORT_AUTHORIZATION_REQUIRED",
                    "导入商业站点正文前需要用户明确确认有权处理该文件。",
                    retryable=True,
                    next_actions=["confirm-user-authorization", "provide-authorized-file"],
                )
            document = self.document_adapter.collect(supplied_file, language=language or site["defaultLanguage"], authorized=True)
            result = deepcopy(base)
            result.update(
                {
                    "status": document["status"],
                    "title": document.get("title") or result["title"],
                    "language": document.get("language") or result["language"],
                    "rightsBoundary": {
                        "accessLevel": "user-authorized",
                        "basis": "User explicitly authorized processing of the supplied local file for this source record.",
                        "confirmedByUser": True,
                    },
                    "assets": document["assets"],
                    "contentSha256": document.get("contentSha256"),
                }
            )
            result["metadata"] = {
                **result["metadata"],
                "localImport": document["metadata"],
                "chapterDirectory": document["metadata"].get("structure", {}).get("units", []),
            }
            result["report"] = {
                "complete": document["status"] == "CONTENT_READY",
                "acquisitionMethod": "user-authorized-file",
                "capabilityLevel": site["effectiveCapabilityLevel"],
                "ruleExpired": site["ruleExpired"],
                "documentReport": document["report"],
                "sourceBoundary": "Website identity is preserved, while full text comes only from the user-authorized local file.",
                "nextActions": document["report"].get("nextActions", []),
                "revisionSignals": {
                    "canonicalUrl": matched.canonical_url,
                    "platformId": matched.platform_id,
                    "contentSha256": document.get("contentSha256"),
                    "originalSha256": document["metadata"].get("originalSha256"),
                },
            }
            result["report"]["updateIdentity"] = _stable_hash(result["report"]["revisionSignals"])
            return result

        metadata_method = str(site["capabilities"].get("metadata", ""))
        may_fetch = self.fetcher is not None and metadata_method in _AUTOMATED_METADATA_METHODS
        if not may_fetch:
            result = deepcopy(base)
            result["status"] = "METADATA_READY"
            result["report"] = {
                "complete": False,
                "acquisitionMethod": "source-record",
                "capabilityLevel": site["effectiveCapabilityLevel"],
                "ruleExpired": site["ruleExpired"],
                "degradationReason": site.get("degradationReason"),
                "sourceBoundary": "Only the canonical source record was created; no page body or novel text was fetched.",
                "nextActions": ["provide-user-authorized-file"],
                "revisionSignals": {
                    "canonicalUrl": matched.canonical_url,
                    "platformId": matched.platform_id,
                },
            }
            result["report"]["updateIdentity"] = _stable_hash(result["report"]["revisionSignals"])
            return result

        request_url = self._request_url(site["siteId"], matched)
        try:
            response = self.fetcher(request_url, deepcopy(site))  # type: ignore[misc]
        except ToolError as exc:
            return self._blocked(
                base,
                exc.code,
                exc.message,
                retryable=exc.retryable,
                details=exc.details,
                next_actions=["retry", "provide-user-authorized-file"],
            )
        except Exception as exc:
            return self._blocked(
                base,
                "SITE_UNAVAILABLE",
                "网页或官方资料接口当前不可访问；未根据标题或链接编造正文。",
                retryable=True,
                details={"errorType": type(exc).__name__},
                next_actions=["retry", "provide-user-authorized-file"],
            )
        return self._from_response(base, site, matched, request_url, response, language)

    def _base_result(self, matched: _MatchedSite, collected_at: str, language: str | None) -> dict[str, Any]:
        site = matched.capability
        return {
            "sourceType": "novel-web",
            "status": "DISCOVERED",
            "title": None,
            "language": language or site["defaultLanguage"],
            "platform": site["siteId"],
            "platformId": matched.platform_id,
            "canonicalUrl": matched.canonical_url,
            "canonicalLocator": matched.canonical_url,
            "provenance": {
                "kind": "public-url",
                "locator": matched.canonical_url,
                "collectedAt": collected_at,
                "adapterId": f"{SITE_REGISTRY_ADAPTER_ID}:{site['siteId']}",
                "adapterVersion": site["adapterVersion"],
                "acquisitionMethod": "source-record",
                "manifestVersion": self.manifest["manifestVersion"],
            },
            "rightsBoundary": {
                "accessLevel": site["rightsPolicy"].get("defaultAccessLevel", "unknown"),
                "basis": "Capability manifest default; per-work rights were not inferred from the URL.",
                "confirmedByUser": False,
            },
            "metadata": {
                "siteName": site["displayName"],
                "market": site["market"],
                "allowedFields": site["allowedFields"],
                "chapterDirectory": [],
            },
            "assets": [],
            "contentSha256": None,
            "report": {},
        }

    def _request_url(self, site_id: str, matched: _MatchedSite) -> str:
        if site_id == "syosetu" and re.fullmatch(r"N[0-9A-Z]+", matched.platform_id):
            fields = "t-n-w-s-g-k-ga-gf-gl-nt-e-nu"
            return (
                "https://api.syosetu.com/novelapi/api/?"
                + urlencode({"out": "json", "ncode": matched.platform_id.lower(), "of": fields})
            )
        if site_id == "zh-wikisource" and matched.platform_id:
            return "https://zh.wikisource.org/w/api.php?" + urlencode(
                {
                    "action": "parse",
                    "page": matched.platform_id.replace("_", " "),
                    "prop": "text|displaytitle|sections|categories|properties",
                    "format": "json",
                    "formatversion": "2",
                }
            )
        return matched.canonical_url

    def _from_response(
        self,
        base: dict[str, Any],
        site: dict[str, Any],
        matched: _MatchedSite,
        request_url: str,
        response: Any,
        requested_language: str | None,
    ) -> dict[str, Any]:
        if not isinstance(response, dict):
            return self._blocked(
                base,
                "SITE_RESPONSE_INVALID",
                "站点适配器返回了无效响应；没有保存正文。",
                retryable=True,
                next_actions=["update-site-adapter", "provide-user-authorized-file"],
            )
        status_code = response.get("statusCode", 200)
        if not isinstance(status_code, int):
            status_code = 0
        if status_code < 200 or status_code >= 300:
            return self._blocked(
                base,
                "SITE_UNAVAILABLE",
                "网页或官方资料接口当前不可访问；没有根据标题或封面编造正文。",
                retryable=status_code >= 500 or status_code in {0, 408, 429},
                details={"httpStatus": status_code},
                next_actions=["retry", "provide-user-authorized-file"],
            )

        media_type = response.get("mediaType") or response.get("contentType") or "application/octet-stream"
        body = response.get("body")
        encoding = response.get("encoding")
        if isinstance(body, bytes):
            try:
                body, encoding = _decode_body(body, str(media_type))
            except ToolError as exc:
                return self._blocked(
                    base,
                    exc.code,
                    exc.message,
                    retryable=True,
                    next_actions=["update-site-adapter", "provide-user-authorized-file"],
                )
        elif body is not None and not isinstance(body, str):
            body = json.dumps(body, ensure_ascii=False)

        metadata = deepcopy(response.get("metadata") if isinstance(response.get("metadata"), dict) else {})
        content = response.get("content")
        if isinstance(content, bytes):
            content, encoding = _decode_body(content, str(media_type))
        if content is not None and not isinstance(content, str):
            content = str(content)
        parsed_metadata: dict[str, Any] = {}
        parsed_content: str | None = None
        if isinstance(body, str) and body:
            parsed_metadata, parsed_content = self._parse_body(site["siteId"], body, str(media_type))
        for key, value in parsed_metadata.items():
            metadata.setdefault(key, value)
        if content is None:
            content = parsed_content
        if isinstance(content, str):
            content = _normalize_text(content)
        else:
            content = ""

        allowed = set(site["allowedFields"])
        filtered_metadata = {key: value for key, value in metadata.items() if key in allowed}
        title = filtered_metadata.get("title")
        if title is not None and not isinstance(title, str):
            title = str(title)
        chapter_directory = filtered_metadata.get("chapterDirectory")
        if not isinstance(chapter_directory, list):
            chapter_directory = []
        filtered_metadata["chapterDirectory"] = chapter_directory

        rights = response.get("rights") if isinstance(response.get("rights"), dict) else {}
        access_level = rights.get("accessLevel")
        rights_verified = rights.get("verified") is True
        rights_basis = rights.get("basis")
        acquisition_method = response.get("acquisitionMethod")
        if not isinstance(acquisition_method, str) or not acquisition_method:
            acquisition_method = site["acquisitionMethods"][0]
        permitted_full_text_methods = {
            "aozora": {"official-download"},
            "zh-wikisource": {"mediawiki-api"},
            "project-gutenberg": {"official-mirror", "robot-harvest"},
        }.get(site["siteId"], set())
        rights_allow_content = (
            site["fullTextEnabled"]
            and isinstance(access_level, str)
            and access_level in {"public-domain", "open-license"}
            and rights_verified
            and isinstance(rights_basis, str)
            and bool(rights_basis.strip())
            and acquisition_method in permitted_full_text_methods
        )
        content_ignored = bool(content) and not rights_allow_content
        if not rights_allow_content:
            content = ""
        content_hash = _sha256(content.encode("utf-8")) if content else None
        language = response.get("language") if isinstance(response.get("language"), str) else None
        language = _detect_language(content or str(title or ""), requested_language or language, site["defaultLanguage"])
        revision_signals = {
            "canonicalUrl": matched.canonical_url,
            "platformId": matched.platform_id,
            "etag": response.get("etag"),
            "lastModified": response.get("lastModified"),
            "platformUpdatedAt": filtered_metadata.get("updatedAt"),
            "revisionId": filtered_metadata.get("revisionId"),
            "contentSha256": content_hash,
        }
        revision_signals = {key: value for key, value in revision_signals.items() if value is not None}
        result = deepcopy(base)
        result.update(
            {
                "status": "CONTENT_READY" if content else "METADATA_READY",
                "title": title,
                "language": language,
                "rightsBoundary": {
                    "accessLevel": access_level if rights_allow_content else site["rightsPolicy"].get("defaultAccessLevel", "unknown"),
                    "basis": rights_basis if rights_allow_content else "Per-work public-domain/open-license verification is missing or full-text capability is disabled.",
                    "confirmedByUser": False,
                },
                "metadata": {
                    **result["metadata"],
                    **filtered_metadata,
                    "responseEncoding": encoding,
                    "responseMediaType": media_type,
                },
                "contentSha256": content_hash,
            }
        )
        result["provenance"]["acquisitionMethod"] = acquisition_method
        result["provenance"]["requestUrl"] = request_url
        if content:
            content_bytes = content.encode("utf-8")
            result["assets"] = [
                {
                    "role": "normalized",
                    "mediaType": "text/plain;charset=utf-8",
                    "filename": "normalized.txt",
                    "data": content,
                    "sha256": content_hash,
                    "sizeBytes": len(content_bytes),
                }
            ]
        next_actions: list[str] = []
        if not content:
            next_actions.append("provide-user-authorized-file")
        if site["ruleExpired"]:
            next_actions.insert(0, "refresh-site-capability-rules")
        elif content_ignored:
            next_actions.insert(0, "verify-per-work-rights")
        result["report"] = {
            "complete": bool(content),
            "acquisitionMethod": result["provenance"]["acquisitionMethod"],
            "httpStatus": status_code,
            "capabilityLevel": site["effectiveCapabilityLevel"],
            "ruleExpired": site["ruleExpired"],
            "degradationReason": site.get("degradationReason"),
            "rightsVerified": rights_allow_content,
            "contentIgnoredByBoundary": content_ignored,
            "sourceBoundary": (
                "Full text came from an approved public source channel with per-work rights evidence."
                if content
                else "Only allowed metadata was retained; unavailable or unauthorized text was not inferred."
            ),
            "nextActions": next_actions,
            "revisionSignals": revision_signals,
            "updateIdentity": _stable_hash(revision_signals),
        }
        return result

    def _parse_body(self, site_id: str, body: str, media_type: str) -> tuple[dict[str, Any], str | None]:
        if "json" in media_type.lower() or body.lstrip().startswith(("{", "[")):
            try:
                payload = json.loads(body)
            except json.JSONDecodeError:
                return {}, None
            if site_id == "syosetu" and isinstance(payload, list):
                record = next((item for item in payload if isinstance(item, dict) and "title" in item), {})
                mapped = {
                    "title": record.get("title"),
                    "author": record.get("writer"),
                    "description": record.get("story"),
                    "keywords": record.get("keyword", "").split() if isinstance(record.get("keyword"), str) else None,
                    "chapterCount": record.get("general_all_no"),
                    "publishedAt": record.get("general_firstup"),
                    "updatedAt": record.get("novelupdated_at") or record.get("general_lastup"),
                }
                return {key: value for key, value in mapped.items() if value is not None and value != ""}, None
            if site_id == "zh-wikisource" and isinstance(payload, dict) and isinstance(payload.get("parse"), dict):
                parsed = payload["parse"]
                html = parsed.get("text") if isinstance(parsed.get("text"), str) else ""
                parser = _MetadataHtmlParser()
                parser.feed(html)
                metadata = {
                    "title": parsed.get("displaytitle") or parsed.get("title"),
                    "chapterDirectory": [
                        {"index": index, "title": section.get("line"), "anchor": section.get("anchor")}
                        for index, section in enumerate(parsed.get("sections", []), 1)
                        if isinstance(section, dict)
                    ],
                    "categories": [
                        item.get("*") or item.get("category")
                        for item in parsed.get("categories", [])
                        if isinstance(item, dict)
                    ],
                }
                return {key: value for key, value in metadata.items() if value is not None and value != ""}, parser.text()
            return {}, None
        if "html" in media_type.lower() or "<html" in body[:1000].lower():
            parser = _MetadataHtmlParser()
            parser.feed(body)
            return parser.metadata(), parser.text()
        return {}, _normalize_text(body)

    def _blocked(
        self,
        base: dict[str, Any],
        code: str,
        message: str,
        *,
        retryable: bool,
        next_actions: list[str],
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = deepcopy(base)
        result["status"] = "BLOCKED"
        result["report"] = {
            "complete": False,
            "failure": {
                "code": code,
                "message": message,
                "retryable": retryable,
                "details": details or {},
            },
            "sourceBoundary": "No novel body was stored or invented after the failed/blocked acquisition.",
            "nextActions": next_actions,
            "revisionSignals": {
                "canonicalUrl": result["canonicalUrl"],
                "platformId": result["platformId"],
            },
        }
        result["report"]["updateIdentity"] = _stable_hash(result["report"]["revisionSignals"])
        return result


__all__ = [
    "DEFAULT_MANIFEST_PATH",
    "SITE_REGISTRY_ADAPTER_ID",
    "SITE_REGISTRY_ADAPTER_VERSION",
    "SiteAdapterRegistry",
    "SiteFetcher",
]
