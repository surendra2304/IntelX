"""Tests for INTELX Connectors, SSRF Protection, Robots Enforcement, Ingestion, and Sanitization."""

import socket
from pathlib import Path

import httpx
import pytest
import respx

from intelx.connectors.files import FileConnector
from intelx.connectors.sanitize import IngestionSanitizer
from intelx.connectors.search import SearchResult, WebSearchConnector
from intelx.connectors.web import HttpFetchConnector
from intelx.core.enums import SourceKind, TrustTier
from intelx.core.errors import (
    ContentSizeExceededError,
    DomainPolicyError,
    ProviderError,
    RobotsDisallowedError,
    SSRFBlockedError,
    UnsupportedContentTypeError,
)
from intelx.core.settings import Settings
from intelx.db.session import get_sessionmaker
from intelx.memory.normalize import (
    _parse_published_at,
    chunk_text_with_offsets,
    ingest_and_normalize,
)


@pytest.fixture
def db_session_factory():
    """Get active async sessionmaker."""
    return get_sessionmaker()


@pytest.fixture
def resolve_example_com(monkeypatch):
    """Keep fetch tests deterministic while providing one public DNS answer."""
    original_getaddrinfo = socket.getaddrinfo

    def fake_getaddrinfo(host, *args, **kwargs):
        if host == "example.com":
            port = args[0] if args else kwargs.get("port", 0)
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("93.184.216.34", port or 0),
                )
            ]
        return original_getaddrinfo(host, *args, **kwargs)

    monkeypatch.setattr("intelx.connectors.fetch_guard.socket.getaddrinfo", fake_getaddrinfo)


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
async def test_ssrf_protection_on_redirect(resolve_example_com):
    """Verify SSRF guard checks every redirect hop and halts when redirected to private IP."""
    respx.get("http://93.184.216.34:80/redirect-to-private").mock(
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
async def test_fetch_pins_validated_dns_address_and_preserves_host(
    resolve_example_com,
):
    """Connect to the validated IP while retaining the origin Host and TLS SNI."""
    observed = []

    async def handler(request):
        observed.append(request)
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, text="safe")

    connector = HttpFetchConnector(
        settings=Settings(_env_file=None, RESPECT_ROBOTS=False, PER_DOMAIN_DELAY_S=0),
        transport=httpx.MockTransport(handler),
    )
    result = await connector.fetch("https://example.com/article?q=trace")

    assert result.final_url == "https://example.com/article?q=trace"
    assert len(observed) == 1
    request = observed[0]
    assert request.url.host == "93.184.216.34"
    assert request.url.path == "/article"
    assert request.url.query == b"q=trace"
    assert request.headers["host"] == "example.com"
    assert request.extensions["sni_hostname"] == "example.com"


@pytest.mark.asyncio
async def test_fetch_rejects_port_zero_before_dns(monkeypatch):
    def unexpected_dns(*_args, **_kwargs):
        pytest.fail("port zero should be rejected before DNS resolution")

    monkeypatch.setattr("intelx.connectors.fetch_guard.socket.getaddrinfo", unexpected_dns)
    connector = HttpFetchConnector(settings=Settings(_env_file=None, RESPECT_ROBOTS=False))

    with pytest.raises(SSRFBlockedError, match="Invalid URL port"):
        await connector.fetch("http://example.com:0/article")


@pytest.mark.asyncio
async def test_fetch_rejects_dns_rebinding_before_connect(monkeypatch):
    """Reject a host that becomes private between policy and connection checks."""
    resolutions = 0
    requests = []
    original_getaddrinfo = socket.getaddrinfo

    def rebinding_getaddrinfo(host, port, **kwargs):
        nonlocal resolutions
        if host != "rebind.example":
            return original_getaddrinfo(host, port, **kwargs)
        resolutions += 1
        address = "93.184.216.34" if resolutions == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port or 0))]

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"Content-Type": "text/plain"}, text="unexpected")

    monkeypatch.setattr("intelx.connectors.fetch_guard.socket.getaddrinfo", rebinding_getaddrinfo)
    connector = HttpFetchConnector(
        settings=Settings(_env_file=None, RESPECT_ROBOTS=False),
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(SSRFBlockedError, match="127.0.0.1"):
        await connector.fetch("http://rebind.example/article")

    assert resolutions == 2
    assert requests == []


@pytest.mark.asyncio
@respx.mock
async def test_robots_txt_disallow_enforcement(resolve_example_com):
    """Verify robots.txt disallow rules are honored."""
    respx.get("http://93.184.216.34/robots.txt").mock(
        return_value=httpx.Response(
            200,
            text="User-agent: *\nDisallow: /private/\n",
        )
    )
    respx.get("http://93.184.216.34/private/data").mock(
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
async def test_oversized_body_and_content_type_rejection(resolve_example_com):
    """Verify oversized payloads and unsupported content types are rejected."""
    # 1. Oversized body
    large_payload = "A" * 60000
    respx.get("http://93.184.216.34/huge.html").mock(
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
    respx.get("http://93.184.216.34/binary.exe").mock(
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


def test_parse_explicit_publication_date():
    """Publication dates in fixture/document metadata must survive ingestion."""
    assert (
        _parse_published_at("# Study\nPublished: 2021-01-10\nDomain: example.org")
        .date()
        .isoformat()
        == "2021-01-10"
    )
    assert _parse_published_at("Publication date: 2021") is not None
    assert _parse_published_at("No date supplied") is None


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
async def test_live_search_provider_outage_is_not_reported_as_no_results(monkeypatch):
    """Distinguish a genuine empty search response from failed external providers."""
    searcher = WebSearchConnector(settings=Settings(MOCK_MODE=False))

    class BrokenProvider:
        async def fetch(self, target, **kwargs):
            raise RuntimeError("provider internals must not leak")

    for name in ("_google_news", "_wikipedia", "_ddg"):
        monkeypatch.setattr(searcher, name, BrokenProvider())

    with pytest.raises(ProviderError, match="one or more providers failed") as exc_info:
        await searcher.fetch("test outage handling")

    failures = exc_info.value.details["failed_providers"]
    assert {failure["provider"] for failure in failures} == {
        "google_news",
        "wikipedia",
        "duckduckgo",
    }
    assert all("provider internals must not leak" not in str(failure) for failure in failures)


@pytest.mark.asyncio
async def test_live_search_empty_success_remains_an_honest_null_result(monkeypatch):
    searcher = WebSearchConnector(settings=Settings(MOCK_MODE=False))

    class EmptyProvider:
        async def fetch(self, target, **kwargs):
            return []

    for name in ("_google_news", "_wikipedia", "_ddg"):
        monkeypatch.setattr(searcher, name, EmptyProvider())

    assert await searcher.fetch("a query with no matching sources") == []


@pytest.mark.asyncio
async def test_live_search_uses_partial_results_when_a_provider_fails(monkeypatch):
    searcher = WebSearchConnector(settings=Settings(MOCK_MODE=False))
    expected = SearchResult(
        url="https://news.example.test/report",
        title="Independent report",
        snippet="A source result from a healthy provider.",
    )

    class ResultProvider:
        async def fetch(self, target, **kwargs):
            return [expected]

    class BrokenProvider:
        async def fetch(self, target, **kwargs):
            raise ProviderError("provider unavailable", details={"provider": "wikipedia"})

    monkeypatch.setattr(searcher, "_google_news", ResultProvider())
    monkeypatch.setattr(searcher, "_wikipedia", BrokenProvider())

    assert await searcher.fetch("a topic with partial provider health") == [expected]


@pytest.mark.asyncio
async def test_mock_search_keeps_topic_fixtures_separate_and_returns_honest_nulls():
    """Do not contaminate a topic with unrelated fixture evidence or synthetic defaults."""
    searcher = WebSearchConnector(settings=Settings(MOCK_MODE=True))

    solid_state = await searcher.fetch("Determine composite sulfide solid-state capacity retention")
    silicon = await searcher.fetch("Investigate silicon composite anode energy density benchmarks")
    unknown = await searcher.fetch("Assess undocumented orbital elevator field data")

    assert [result.url.rsplit("/", 1)[-1] for result in solid_state] == ["solid_state_cycling.txt"]
    assert {result.url.rsplit("/", 1)[-1] for result in silicon} == {
        "density_paper_nature.txt",
        "density_paper_prl.txt",
    }
    assert unknown == []


@pytest.mark.asyncio
async def test_web_search_connector_mock_routing():
    """Verify WebSearchConnector produces structured results in mock mode."""
    searcher = WebSearchConnector(settings=Settings(MOCK_MODE=True))
    results = await searcher.fetch("quantum computing logical qubits")

    assert len(results) >= 2
    assert results[0].url.startswith(("http", "file://"))
    assert len(results[0].title) > 0
    assert len(results[0].snippet) > 0
