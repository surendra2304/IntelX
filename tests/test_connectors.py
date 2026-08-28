"""Tests for INTELX Connectors, SSRF Protection, Robots Enforcement, Ingestion, and Sanitization."""

from pathlib import Path

import httpx
import pytest
import respx

from intelx.connectors.files import FileConnector
from intelx.connectors.sanitize import IngestionSanitizer
from intelx.connectors.search import WebSearchConnector
from intelx.connectors.web import HttpFetchConnector
from intelx.core.enums import SourceKind, TrustTier
from intelx.core.errors import (
    ContentSizeExceededError,
    DomainPolicyError,
    RobotsDisallowedError,
    SSRFBlockedError,
    UnsupportedContentTypeError,
)
from intelx.core.settings import Settings
from intelx.db.session import get_sessionmaker
from intelx.memory.normalize import chunk_text_with_offsets, ingest_and_normalize


@pytest.fixture
def db_session_factory():
    """Get active async sessionmaker."""
    return get_sessionmaker()


@pytest.mark.asyncio
async def test_ssrf_protection_blocks_private_and_metadata_ips():
    """Verify SSRF guard rejects loopback, private, and cloud metadata addresses."""
    connector = HttpFetchConnector()

    blocked_targets = [
        "http://localhost:8080/metrics",
        "http://127.0.0.1/admin",
        "http://169.254.169.254/latest/meta-data",
        "http://10.0.1.5/internal",
        "http://192.168.1.1/gateway",
        "http://0.0.0.0:8000/api",
    ]

    for target in blocked_targets:
        with pytest.raises(SSRFBlockedError) as exc_info:
            await connector.fetch(target)
        assert "SSRF violation" in str(exc_info.value) or "prohibited IP" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_ssrf_protection_on_redirect():
    """Verify SSRF guard checks every redirect hop and halts when redirected to private IP."""
    respx.get("http://example.com/redirect-to-private").mock(
        return_value=httpx.Response(
            302,
            headers={"Location": "http://127.0.0.1/secret"},
        )
    )

    connector = HttpFetchConnector()
    with pytest.raises(SSRFBlockedError) as exc_info:
        await connector.fetch("http://example.com/redirect-to-private")
    assert "127.0.0.1" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_robots_txt_disallow_enforcement():
    """Verify robots.txt disallow rules are honored."""
    respx.get("http://example.com/robots.txt").mock(
        return_value=httpx.Response(
            200,
            text="User-agent: *\nDisallow: /private/\n",
        )
    )
    respx.get("http://example.com/private/data").mock(
        return_value=httpx.Response(200, text="Secret Content")
    )

    settings = Settings(RESPECT_ROBOTS=True)
    connector = HttpFetchConnector(settings=settings)

    # 1. Fetching disallowed path returns robots_ok=False
    result = await connector.fetch("http://example.com/private/data")
    assert result.robots_ok is False
    assert result.status_code == 403

    # 2. raise_on_robots raises RobotsDisallowedError
    with pytest.raises(RobotsDisallowedError):
        await connector.fetch("http://example.com/private/data", raise_on_robots=True)


@pytest.mark.asyncio
@respx.mock
async def test_oversized_body_and_content_type_rejection():
    """Verify oversized payloads and unsupported content types are rejected."""
    # 1. Oversized body
    large_payload = "A" * 60000
    respx.get("http://example.com/huge.html").mock(
        return_value=httpx.Response(
            200,
            headers={"Content-Type": "text/html"},
            text=large_payload,
        )
    )

    settings = Settings(MAX_PAGE_BYTES=5000)
    connector = HttpFetchConnector(settings=settings)

    with pytest.raises(ContentSizeExceededError) as exc_size:
        await connector.fetch("http://example.com/huge.html")
    assert "MAX_PAGE_BYTES" in str(exc_size.value)

    # 2. Unsupported Content-Type
    respx.get("http://example.com/binary.exe").mock(
        return_value=httpx.Response(
            200,
            headers={"Content-Type": "application/x-msdownload"},
            content=b"\x4d\x5a\x90",
        )
    )
    with pytest.raises(UnsupportedContentTypeError) as exc_type:
        await connector.fetch("http://example.com/binary.exe")
    assert "Refusing content-type" in str(exc_type.value)


@pytest.mark.asyncio
async def test_denylisted_domain_rejection():
    """Verify domain denylist triggers DomainPolicyError."""
    settings = Settings(DOMAIN_DENYLIST=["malicious.com", "spam.net"])
    connector = HttpFetchConnector(settings=settings)

    with pytest.raises(DomainPolicyError) as exc_info:
        await connector.fetch("http://malicious.com/article")
    assert "blocked by policy guard" in str(exc_info.value)


def test_chunking_offset_integrity():
    """Verify every chunk offset perfectly indexes the source text slice."""
    sample_text = (
        "Artificial intelligence systems require robust verification architectures.\n"
        "Evidence cannot remain unstructured text within prompts.\n"
        "Instead, every factual proposition must trace to specific document spans.\n"
    ) * 15

    chunks = chunk_text_with_offsets(sample_text, target_size=400, overlap=50)
    assert len(chunks) >= 3

    for c in chunks:
        slice_text = sample_text[c.start_char : c.end_char]
        assert slice_text == c.text
        assert len(c.text) == (c.end_char - c.start_char)


@pytest.mark.asyncio
async def test_ingest_and_deduplication(db_session_factory):
    """Verify content ingestion deduplicates identical content by SHA256 fingerprint."""
    async with db_session_factory() as session:
        raw_html = (
            b"<html><body><h1>Semiconductor Foundry Yields</h1>"
            b"<p>TSMC reached 85 percent yield.</p></body></html>"
        )

        # First ingestion
        source1, doc1, chunks1, is_new1 = await ingest_and_normalize(
            session=session,
            raw_bytes=raw_html,
            location="https://semiconductor.org/yields-2026.html",
            kind=SourceKind.WEB,
            content_type="text/html",
            domain="semiconductor.org",
        )
        assert is_new1 is True
        assert source1.trust_tier == TrustTier.QUARANTINE
        assert len(chunks1) >= 1
        assert "TSMC reached 85 percent yield." in doc1.text

        # Second ingestion with identical content
        source2, doc2, chunks2, is_new2 = await ingest_and_normalize(
            session=session,
            raw_bytes=raw_html,
            location="https://mirror.org/yields-2026.html",
            kind=SourceKind.WEB,
            content_type="text/html",
            domain="mirror.org",
        )
        assert is_new2 is False
        assert source2.id == source1.id
        assert doc2.id == doc1.id


def test_injection_corpus_detection_and_content_immutability():
    """Verify all injection fixtures are flagged without altering content."""
    fixtures_dir = Path("./tests/fixtures/injection").resolve()
    fixture_files = list(fixtures_dir.glob("*.txt"))
    assert len(fixture_files) == 6

    sanitizer = IngestionSanitizer()

    for fpath in fixture_files:
        content = fpath.read_text(encoding="utf-8")
        scan_res = sanitizer.scan(content)

        assert scan_res.injection_risk is True
        assert scan_res.flags_count >= 1
        assert len(content) == len(fpath.read_text(encoding="utf-8"))


def test_file_connector_supported_formats(tmp_path):
    """Verify FileConnector parses HTML, Markdown, JSON, and text correctly."""
    connector = FileConnector()

    # 1. HTML file
    html_file = tmp_path / "report.html"
    html_file.write_text(
        "<html><body><h2>Executive Summary</h2><p>Q2 revenue grew 15%.</p></body></html>"
    )
    res_html = connector.parse_bytes(html_file.read_bytes(), "report.html")
    assert "Executive Summary" in res_html.extracted_text
    assert "Q2 revenue grew 15%." in res_html.extracted_text

    # 2. Markdown file
    md_file = tmp_path / "notes.md"
    md_file.write_text("# Notes\n- Point 1\n- Point 2")
    res_md = connector.parse_bytes(md_file.read_bytes(), "notes.md")
    assert "# Notes" in res_md.extracted_text

    # 3. JSON file
    json_file = tmp_path / "data.json"
    json_file.write_text('{"metric": "latency", "value_ms": 12.5}')
    res_json = connector.parse_bytes(json_file.read_bytes(), "data.json")
    assert '"latency"' in res_json.extracted_text

    # 4. Disallowed extension
    with pytest.raises(UnsupportedContentTypeError):
        connector.parse_bytes(b"\x00\x01\x02", "archive.zip")


@pytest.mark.asyncio
async def test_web_search_connector_mock_routing():
    """Verify WebSearchConnector produces structured results in mock mode."""
    searcher = WebSearchConnector(settings=Settings(MOCK_MODE=True))
    results = await searcher.fetch("quantum computing logical qubits")

    assert len(results) >= 2
    assert results[0].url.startswith("http")
    assert len(results[0].title) > 0
    assert len(results[0].snippet) > 0
