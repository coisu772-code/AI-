from __future__ import annotations

import json
import sys
import tempfile
import types
import unittest
import zipfile
from copy import deepcopy
from datetime import date
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
MCP_ROOT = ROOT / "plugins" / "ai-video-channel-production" / "mcp"
FIXTURES = ROOT / "tests" / "fixtures" / "stage3"
sys.path.insert(0, str(MCP_ROOT))

from aivcp_tools.source_documents import DocumentAdapter  # noqa: E402
from aivcp_tools.source_sites import OfficialSiteFetcher, SiteAdapterRegistry  # noqa: E402


def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_epub(path: Path) -> None:
    container = """<?xml version="1.0" encoding="UTF-8"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""
    package = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>風の図書室</dc:title><dc:creator>Fixture Author</dc:creator><dc:language>ja</dc:language>
  </metadata>
  <manifest>
    <item id="c1" href="Text/chapter1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="Text/chapter2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>"""
    chapters = {
        "OEBPS/Text/chapter1.xhtml": "<html><body><h1>第一章</h1><p>風の音を記録しました。</p></body></html>",
        "OEBPS/Text/chapter2.xhtml": "<html><body><h1>第二章</h1><p>記録を町に公開しました。</p></body></html>",
    }
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", container)
        archive.writestr("OEBPS/content.opf", package)
        for name, value in chapters.items():
            archive.writestr(name, value)


def build_docx(path: Path) -> None:
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    document = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>第一章 旧站台</w:t></w:r></w:p>
  <w:p><w:r><w:t>公开记录只包含已经核验的事实。</w:t></w:r></w:p>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>第二章 新车票</w:t></w:r></w:p>
  <w:p><w:r><w:t>无法核验的部分保持未知。</w:t></w:r></w:p>
</w:body></w:document>"""
    core = """<?xml version="1.0" encoding="UTF-8"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>旧站台</dc:title><dc:creator>Fixture Author</dc:creator><dc:language>zh-CN</dc:language></cp:coreProperties>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document)
        archive.writestr("docProps/core.xml", core)


class FixtureFetcher:
    def __init__(self, response: dict[str, object]) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    def __call__(self, request_url: str, capability: dict[str, object]) -> dict[str, object]:
        self.calls.append((request_url, str(capability["siteId"])))
        return deepcopy(self.response)


class ExplodingFetcher:
    def __call__(self, request_url: str, capability: dict[str, object]) -> dict[str, object]:
        raise AssertionError("commercial source-record adapters must not fetch pages")


class DocumentAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = DocumentAdapter()
        self.temp = tempfile.TemporaryDirectory(prefix="aivcp-stage3-doc-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_japanese_chinese_english_text_and_markdown_are_normalized(self) -> None:
        cases = [
            (FIXTURES / "documents" / "ja" / "short-story.txt", "ja"),
            (FIXTURES / "documents" / "zh" / "short-story.md", "zh-CN"),
            (FIXTURES / "documents" / "en" / "short-story.txt", "en"),
        ]
        for path, language in cases:
            with self.subTest(path=path):
                result = self.adapter.collect(path, language=language)
                self.assertEqual("CONTENT_READY", result["status"])
                self.assertEqual(language, result["language"])
                self.assertEqual(64, len(result["metadata"]["originalSha256"]))
                self.assertEqual(64, len(result["contentSha256"]))
                self.assertGreaterEqual(result["metadata"]["structure"]["extractedUnitCount"], 1)
                self.assertTrue(result["report"]["originalPreserved"])
                self.assertEqual({"raw", "normalized"}, {asset["role"] for asset in result["assets"]})
                self.assertTrue(
                    {"content.txt", "chapters.json"}.issubset(
                        {asset["filename"] for asset in result["assets"]}
                    )
                )

    def test_same_content_with_different_file_encoding_has_one_content_hash(self) -> None:
        text = (FIXTURES / "documents" / "zh" / "short-story.md").read_text(encoding="utf-8")
        utf8_path = self.root / "story-utf8.txt"
        utf16_path = self.root / "story-utf16.txt"
        utf8_path.write_text(text, encoding="utf-8")
        utf16_path.write_text(text, encoding="utf-16")
        first = self.adapter.collect(utf8_path, language="zh-CN")
        second = self.adapter.collect(utf16_path, language="zh-CN")
        self.assertNotEqual(first["metadata"]["originalSha256"], second["metadata"]["originalSha256"])
        self.assertEqual(first["contentSha256"], second["contentSha256"])
        self.assertEqual(first["assets"][1]["data"], second["assets"][1]["data"])

    def test_epub_preserves_spine_chapters_and_metadata(self) -> None:
        path = self.root / "fixture.epub"
        build_epub(path)
        result = self.adapter.collect(path)
        self.assertEqual("CONTENT_READY", result["status"])
        self.assertEqual("風の図書室", result["title"])
        self.assertEqual("ja", result["language"])
        structure = result["metadata"]["structure"]
        self.assertEqual("chapter", structure["unitType"])
        self.assertEqual(2, structure["expectedUnitCount"])
        self.assertEqual(2, structure["extractedUnitCount"])

    def test_docx_preserves_headings_paragraphs_and_core_properties(self) -> None:
        path = self.root / "fixture.docx"
        build_docx(path)
        result = self.adapter.collect(path)
        self.assertEqual("CONTENT_READY", result["status"])
        self.assertEqual("旧站台", result["title"])
        self.assertEqual("zh-CN", result["language"])
        self.assertEqual("Fixture Author", result["metadata"]["author"])
        self.assertEqual("chapter", result["metadata"]["structure"]["unitType"])
        self.assertEqual(2, result["metadata"]["structure"]["expectedUnitCount"])

    def test_pdf_uses_optional_extractor_and_preserves_page_completeness(self) -> None:
        path = self.root / "fixture.pdf"
        path.write_bytes(b"%PDF-fixture")

        class Page:
            def __init__(self, text: str) -> None:
                self.value = text

            def extract_text(self) -> str:
                return self.value

        class Reader:
            is_encrypted = False
            pages = [Page("Page one fixture text."), Page("Page two fixture text.")]
            metadata = {"/Title": "The Quiet Workshop", "/Author": "Fixture Author"}

        fake_module = types.SimpleNamespace(PdfReader=lambda _: Reader())
        with patch.dict(sys.modules, {"pypdf": fake_module}):
            result = self.adapter.collect(path, language="en")
        self.assertEqual("CONTENT_READY", result["status"])
        self.assertEqual("page", result["metadata"]["structure"]["unitType"])
        self.assertEqual(2, result["metadata"]["structure"]["extractedUnitCount"])

    def test_scanned_pdf_without_text_is_blocked_without_ocr_fabrication(self) -> None:
        path = self.root / "scan.pdf"
        path.write_bytes(b"%PDF-scanned-fixture")

        class Page:
            def extract_text(self) -> str:
                return ""

        class Reader:
            is_encrypted = False
            pages = [Page()]
            metadata: dict[str, str] = {}

        with patch.dict(sys.modules, {"pypdf": types.SimpleNamespace(PdfReader=lambda _: Reader())}):
            result = self.adapter.collect(path, language="en")
        self.assertEqual("BLOCKED", result["status"])
        self.assertIsNone(result["contentSha256"])
        self.assertEqual("DOCUMENT_PDF_NO_SEARCHABLE_TEXT", result["report"]["failure"]["code"])
        self.assertIn("provide-ocr-text-or-searchable-pdf", result["report"]["nextActions"])

    def test_unauthorized_local_file_is_not_read_or_hashed(self) -> None:
        path = self.root / "not-authorized.txt"
        path.write_text("This content must not be read yet.", encoding="utf-8")
        result = self.adapter.collect(path, authorized=False)
        self.assertEqual("BLOCKED", result["status"])
        self.assertIsNone(result["platformId"])
        self.assertIsNone(result["metadata"]["originalSha256"])
        self.assertEqual([], result["assets"])


class SiteAdapterRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="aivcp-stage3-site-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_manifest_contains_exact_first_market_pack_and_policy_fields(self) -> None:
        result = SiteAdapterRegistry(today=date(2026, 8, 4)).list_capabilities()
        self.assertEqual(9, len(result["sites"]))
        self.assertEqual({"ja": 3, "zh": 3, "en": 3}, {
            market: sum(site["market"] == market for site in result["sites"])
            for market in ("ja", "zh", "en")
        })
        self.assertEqual(
            {
                "syosetu", "kakuyomu", "aozora", "qidian", "fanqie",
                "zh-wikisource", "royal-road", "scribble-hub", "project-gutenberg",
            },
            {site["siteId"] for site in result["sites"]},
        )
        for site in result["sites"]:
            self.assertIn("allowedFields", site)
            self.assertIn("rules", site)
            self.assertIn("rateLimit", site)
            self.assertFalse(site["ruleExpired"])
        fanqie = next(site for site in result["sites"] if site["siteId"] == "fanqie")
        self.assertTrue(fanqie["ruleUnclear"])
        self.assertEqual("metadata-only-user-import", fanqie["effectiveCapabilityLevel"])

    def test_runtime_registry_enables_only_the_policy_aware_official_fetcher(self) -> None:
        registry = SiteAdapterRegistry.from_environment()
        self.assertIsInstance(registry.fetcher, OfficialSiteFetcher)
        commercial = registry.collect("https://book.qidian.com/info/102030")
        self.assertEqual("METADATA_READY", commercial["status"])
        self.assertEqual([], commercial["assets"])

    def test_duplicate_commercial_urls_share_canonical_identity_without_fetch(self) -> None:
        fixture = load_json(FIXTURES / "sites" / "en" / "commercial-record.json")
        registry = SiteAdapterRegistry(fetcher=ExplodingFetcher(), today=date(2026, 8, 4))
        first = registry.collect(str(fixture["locator"]))
        second = registry.collect(str(fixture["duplicateLocator"]))
        self.assertEqual("METADATA_READY", first["status"])
        self.assertEqual(fixture["expectedCanonicalUrl"], first["canonicalUrl"])
        self.assertEqual(first["canonicalUrl"], second["canonicalUrl"])
        self.assertEqual(first["platformId"], second["platformId"])
        self.assertEqual(first["report"]["updateIdentity"], second["report"]["updateIdentity"])
        self.assertEqual([], first["assets"])

    def test_narou_official_api_maps_allowed_metadata_but_never_novel_body(self) -> None:
        fixture = load_json(FIXTURES / "sites" / "ja" / "syosetu-api.json")
        fetcher = FixtureFetcher(fixture["response"])
        result = SiteAdapterRegistry(fetcher=fetcher, today=date(2026, 8, 4)).collect(
            str(fixture["request"]["locator"])
        )
        self.assertEqual("METADATA_READY", result["status"])
        self.assertEqual("公開メタデータの物語", result["title"])
        self.assertEqual("Fixture Author", result["metadata"]["author"])
        self.assertEqual(2, result["metadata"]["chapterCount"])
        self.assertIsNone(result["contentSha256"])
        self.assertEqual([], result["assets"])
        self.assertIn("api.syosetu.com/novelapi/api/", fetcher.calls[0][0])

    def test_all_three_public_sources_can_return_verified_full_text(self) -> None:
        fixture_paths = [
            FIXTURES / "sites" / "ja" / "aozora-public.json",
            FIXTURES / "sites" / "zh" / "wikisource-public.json",
            FIXTURES / "sites" / "en" / "gutenberg-public.json",
        ]
        for path in fixture_paths:
            fixture = load_json(path)
            fetcher = FixtureFetcher(fixture["response"])
            registry = SiteAdapterRegistry(fetcher=fetcher, today=date(2026, 8, 4))
            result = registry.collect(str(fixture["request"]["locator"]))
            with self.subTest(path=path):
                self.assertEqual("CONTENT_READY", result["status"])
                self.assertEqual(64, len(result["contentSha256"]))
                self.assertTrue(result["report"]["rightsVerified"])
                self.assertFalse(result["report"]["contentIgnoredByBoundary"])
                self.assertIn(result["rightsBoundary"]["accessLevel"], {"public-domain", "open-license"})
                self.assertEqual("normalized", result["assets"][0]["role"])
                self.assertEqual(
                    {"content.txt", "chapters.json"},
                    {asset["filename"] for asset in result["assets"]},
                )
                self.assertEqual(1, len(fetcher.calls))

    def test_public_content_without_per_work_rights_is_not_stored(self) -> None:
        fixture = load_json(FIXTURES / "sites" / "ja" / "aozora-public.json")
        response = deepcopy(fixture["response"])
        response.pop("rights")
        result = SiteAdapterRegistry(
            fetcher=FixtureFetcher(response), today=date(2026, 8, 4)
        ).collect(str(fixture["request"]["locator"]))
        self.assertEqual("METADATA_READY", result["status"])
        self.assertIsNone(result["contentSha256"])
        self.assertEqual([], result["assets"])
        self.assertTrue(result["report"]["contentIgnoredByBoundary"])
        self.assertIn("verify-per-work-rights", result["report"]["nextActions"])

    def test_inaccessible_web_is_blocked_with_supplement_path_and_no_text(self) -> None:
        response = load_json(FIXTURES / "sites" / "inaccessible.json")
        result = SiteAdapterRegistry(
            fetcher=FixtureFetcher(response), today=date(2026, 8, 4)
        ).collect("https://www.aozora.gr.jp/cards/000148/card789.html")
        self.assertEqual("BLOCKED", result["status"])
        self.assertEqual("SITE_UNAVAILABLE", result["report"]["failure"]["code"])
        self.assertIn("provide-user-authorized-file", result["report"]["nextActions"])
        self.assertIsNone(result["contentSha256"])
        self.assertEqual([], result["assets"])

    def test_commercial_source_accepts_only_explicit_authorized_file_content(self) -> None:
        document = FIXTURES / "documents" / "zh" / "short-story.md"
        locator = "https://book.qidian.com/info/102030"
        blocked = SiteAdapterRegistry(today=date(2026, 8, 4)).collect(
            locator, supplied_file=document, user_authorized=False
        )
        self.assertEqual("BLOCKED", blocked["status"])
        self.assertEqual([], blocked["assets"])
        imported = SiteAdapterRegistry(today=date(2026, 8, 4)).collect(
            locator, supplied_file=document, user_authorized=True
        )
        self.assertEqual("CONTENT_READY", imported["status"])
        self.assertEqual("user-authorized", imported["rightsBoundary"]["accessLevel"])
        self.assertEqual("qidian", imported["platform"])
        self.assertEqual(64, len(imported["contentSha256"]))
        self.assertEqual("user-authorized-file", imported["report"]["acquisitionMethod"])

    def test_expired_public_capability_degrades_and_discards_full_text(self) -> None:
        fixture = load_json(FIXTURES / "sites" / "en" / "gutenberg-public.json")
        registry = SiteAdapterRegistry(fetcher=FixtureFetcher(fixture["response"]), today=date(2027, 8, 4))
        result = registry.collect(str(fixture["request"]["locator"]))
        self.assertEqual("METADATA_READY", result["status"])
        self.assertTrue(result["report"]["ruleExpired"])
        self.assertEqual("metadata-only-user-import", result["report"]["capabilityLevel"])
        self.assertIsNone(result["contentSha256"])
        self.assertIn("refresh-site-capability-rules", result["report"]["nextActions"])

    def test_incremental_revision_signals_change_identity_without_changing_url(self) -> None:
        fixture = load_json(FIXTURES / "sites" / "en" / "gutenberg-public.json")
        before = deepcopy(fixture["response"])
        before_signals = load_json(FIXTURES / "sites" / "incremental-before.json")
        before.update(before_signals)
        before["rights"] = fixture["response"]["rights"]
        before["acquisitionMethod"] = "official-mirror"
        after = deepcopy(fixture["response"])
        after_signals = load_json(FIXTURES / "sites" / "incremental-after.json")
        after.update(after_signals)
        after["rights"] = fixture["response"]["rights"]
        after["acquisitionMethod"] = "official-mirror"
        locator = str(fixture["request"]["locator"])
        first = SiteAdapterRegistry(fetcher=FixtureFetcher(before), today=date(2026, 8, 4)).collect(locator)
        second = SiteAdapterRegistry(fetcher=FixtureFetcher(after), today=date(2026, 8, 4)).collect(locator)
        self.assertEqual(first["canonicalUrl"], second["canonicalUrl"])
        self.assertNotEqual(first["contentSha256"], second["contentSha256"])
        self.assertNotEqual(first["report"]["updateIdentity"], second["report"]["updateIdentity"])
        self.assertEqual("fixture-v2", second["report"]["revisionSignals"]["etag"])


if __name__ == "__main__":
    unittest.main()
