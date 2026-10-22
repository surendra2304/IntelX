"""Comprehensive security, SSRF defense, file ingestion, and source quality tests."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from intelx.connectors.fetch_guard import SSRFBlocked, resolve_and_validate, safe_target
from intelx.connectors.files import FileConnector, FileIngestResult
from intelx.connectors.search import (
    TavilySearchConnector,
    WebSearchConnector,
)
from intelx.connectors.source_quality import SourceQuality
from intelx.core.errors import ContentSizeExceededError, UnsupportedContentTypeError
from intelx.core.settings import Settings

# ============================================================================
# SSRF & Fetch Guard Defense Tests
# ============================================================================


def test_ssrf_blocks_invalid_schemes():
    """Reject schemes other than http and https."""
    for scheme in (
        "ftp://example.com",
        "file:///etc/passwd",
        "gopher://127.0.0.1",
        "javascript:void(0)",
    ):
        with pytest.raises(SSRFBlocked, match="prohibited URL scheme|invalid target URL"):
            safe_target(scheme)


def test_ssrf_blocks_embedded_credentials():
    """Reject URLs with username or password embedded in target."""
    with pytest.raises(SSRFBlocked, match="user information in target URL"):
        safe_target("https://admin:secret123@example.com/api")


def test_ssrf_blocks_empty_or_whitespace_hostnames():
    """Reject URLs with empty or space-padded hostnames."""
    with pytest.raises(SSRFBlocked):
        safe_target("https://")
    with pytest.raises(SSRFBlocked):
        resolve_and_validate("   ")
    with pytest.raises(SSRFBlocked):
        resolve_and_validate("")


def test_ssrf_blocks_cloud_metadata_explicit_ips():
    """Strictly block cloud instance metadata endpoints across providers."""
    metadata_targets = [
        "http://169.254.169.254/latest/meta-data",  # AWS/GCP
        "http://169.254.170.2/v2/credentials",  # AWS ECS
        "http://100.100.100.200/latest/meta-data",  # Alibaba
        "http://[fd00:ec2::254]/latest/meta-data",  # AWS IPv6 (bracketed)
    ]
    for target in metadata_targets:
        with pytest.raises(
            SSRFBlocked, match="resolved private/reserved target|DNS resolution failure"
        ):
            safe_target(target)


def test_ssrf_blocks_private_subnets_and_localhost():
    """Block loopback and RFC 1918 subnets when allow_private=False."""
    private_targets = [
        "http://127.0.0.1/admin",
        "http://10.0.0.1/admin",
        "http://192.168.1.1/admin",
        "http://172.16.0.1/admin",
        "http://[::1]/admin",
    ]
    for target in private_targets:
        with pytest.raises(SSRFBlocked, match="resolved private/reserved target"):
            safe_target(target, allow_private=False)


def test_ssrf_allows_private_when_explicitly_configured():
    """Permit loopback/private target when allow_private=True."""
    # 127.0.0.1 resolution should succeed without raising SSRFBlocked
    host = safe_target("http://127.0.0.1:8000/healthz", allow_private=True)
    assert host == "127.0.0.1"


def test_ssrf_custom_policy_rejection():
    """Ensure custom policy validate_url hook is respected."""
    mock_policy = MagicMock()
    mock_policy.validate_url.side_effect = ValueError("Domain blocked by organization policy")

    with pytest.raises(SSRFBlocked, match="policy violation"):
        safe_target("https://example.com/data", policy=mock_policy, allow_private=True)


# ============================================================================
# File Ingestion Connector Tests
# ============================================================================


def test_file_connector_supported_extensions_and_parsing(tmp_path: Path):
    """Verify plain text, markdown, csv, json, and html parsing."""
    connector = FileConnector()

    # 1. Plain text
    txt_file = tmp_path / "sample.txt"
    txt_file.write_text("Plain text content for intel research.", encoding="utf-8")
    res_txt = connector.parse_bytes(txt_file.read_bytes(), txt_file.name)
    assert isinstance(res_txt, FileIngestResult)
    assert res_txt.extension == ".txt"
    assert res_txt.content_type == "text/plain"
    assert "Plain text content" in res_txt.extracted_text

    # 2. Markdown
    md_file = tmp_path / "notes.md"
    md_file.write_text("# Battery Limits\n\nSolid state electrolytes.", encoding="utf-8")
    res_md = connector.parse_bytes(md_file.read_bytes(), md_file.name)
    assert res_md.extension == ".md"
    assert "Solid state electrolytes" in res_md.extracted_text

    # 3. CSV
    csv_file = tmp_path / "metrics.csv"
    csv_file.write_text("cycle,capacity\n1,100\n2,99\n", encoding="utf-8")
    res_csv = connector.parse_bytes(csv_file.read_bytes(), csv_file.name)
    assert "cycle,capacity" in res_csv.extracted_text

    # 4. JSON (valid formatting and malformed fallback)
    json_file = tmp_path / "data.json"
    json_file.write_text('{"project": "IntelX", "active": true}', encoding="utf-8")
    res_json = connector.parse_bytes(json_file.read_bytes(), json_file.name)
    assert '"project": "IntelX"' in res_json.extracted_text

    bad_json = b"{not-valid-json"
    res_bad_json = connector.parse_bytes(bad_json, "bad.json")
    assert "{not-valid-json" in res_bad_json.extracted_text

    # 5. HTML stripping script and style tags
    html_content = b"""
    <html>
      <head><style>body { color: red; }</style></head>
      <body>
        <nav>Navigation bar</nav>
        <header>Header content</header>
        <article>
          <h1>Actual Research Finding</h1>
          <p>Silicon nanowires improve lithium conductivity by 300%.</p>
        </article>
        <footer>Footer copyright</footer>
        <script>console.log("malicious code");</script>
      </body>
    </html>
    """
    res_html = connector.parse_bytes(html_content, "page.html")
    assert "Actual Research Finding" in res_html.extracted_text
    assert "Silicon nanowires improve lithium conductivity" in res_html.extracted_text
    assert "console.log" not in res_html.extracted_text
    assert "Navigation bar" not in res_html.extracted_text
    assert "Header content" not in res_html.extracted_text
    assert "Footer copyright" not in res_html.extracted_text


def test_file_connector_size_and_extension_limits():
    """Verify max size enforcement and rejection of unapproved extensions."""
    settings = Settings(MAX_PAGE_BYTES=100)
    connector = FileConnector(settings=settings)

    # Size cap exceeded
    big_data = b"X" * 150
    with pytest.raises(ContentSizeExceededError, match="exceeds MAX_PAGE_BYTES"):
        connector.parse_bytes(big_data, "large.txt")

    # Unsupported format
    with pytest.raises(UnsupportedContentTypeError, match="Unsupported file format"):
        connector.parse_bytes(b"MZ...", "program.exe")


@pytest.mark.asyncio
async def test_file_connector_fetch_from_disk(tmp_path: Path):
    """Verify fetch reads existing files from disk and raises on missing targets."""
    connector = FileConnector()
    test_file = tmp_path / "report.md"
    test_file.write_text("Autonomous market research synthesis.", encoding="utf-8")

    result = await connector.fetch(str(test_file))
    assert result.extracted_text == "Autonomous market research synthesis."

    with pytest.raises(FileNotFoundError):
        await connector.fetch(str(tmp_path / "nonexistent_file.txt"))


# ============================================================================
# Source Quality & Ranking Tests
# ============================================================================


def test_source_quality_authority_and_relevance():
    """Verify authority boosts for academic/governmental domains vs aggregators."""
    sq = SourceQuality()
    terms = {"solid-state", "lithium", "battery"}

    score_nature = sq.score(
        url="https://www.nature.com/articles/s41560-024-battery",
        title="Solid-State Lithium Battery Advances",
        snippet="Recent improvements in solid-state lithium battery cycling efficiency.",
        query_terms=terms,
        published_age_days=30,
        duplicate_count=0,
    )

    score_spam = sq.score(
        url="https://quora.com/what-is-battery",
        title="Battery discussion forum",
        snippet="Random opinions on battery tech.",
        query_terms=terms,
        published_age_days=30,
        duplicate_count=0,
    )

    # Nature has higher authority, relevance, and overall score
    assert score_nature.authority > score_spam.authority
    assert score_nature.total > score_spam.total
    assert sq.quality_bucket(score_nature.total) in ("high", "medium")
    assert sq.quality_bucket(score_spam.total) in ("low", "medium")


def test_source_quality_ranking_and_normalization():
    """Verify ranking orders candidates descending by score and normalizes titles."""
    sq = SourceQuality()

    class SourceStub:
        def __init__(self, url: str, title: str, snippet: str):
            self.url = url
            self.title = title
            self.snippet = snippet

    s1 = SourceStub("https://quora.com/spam", "Forum spam", "unrelated")
    s2 = SourceStub(
        "https://nature.com/breakthrough", "Battery Breakthrough", "Lithium sulfide solid state"
    )
    s3 = SourceStub(
        "https://arxiv.org/abs/2401.1234", "Quantum Annealing", "Superconducting qubits"
    )

    ranked = sq.rank([s1, s2, s3], query_terms=["battery", "solid", "state"])
    assert ranked[0].url == "https://nature.com/breakthrough"

    # Title normalization
    clean = sq.normalize_title("   MULTIPLE   SPACES   AND \n NEWLINES   ")
    assert clean == "multiple spaces and newlines"


# ============================================================================
# Search Connectors Tests
# ============================================================================


@pytest.mark.asyncio
async def test_tavily_search_connector_behavior():
    """Tavily connector returns empty when API key is missing."""
    connector = TavilySearchConnector(api_key=None)
    results = await connector.fetch("test query")
    assert results == []


@pytest.mark.asyncio
async def test_web_search_connector_mock_mode_and_null_results():
    """WebSearchConnector returns null results on impossible scientific queries."""
    settings = Settings(MOCK_MODE=True)
    connector = WebSearchConnector(settings=settings)

    # Perpetual motion query -> null result
    null_results = connector._load_mock_results("perpetual motion overunity energy generator")
    assert null_results == []

    # Valid query search result loading
    results = connector._load_mock_results("silicon anode energy density")
    assert isinstance(results, list)
