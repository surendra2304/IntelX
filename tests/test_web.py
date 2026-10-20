"""Tests for INTELX Server-Rendered Web Workspace, Templates, Citations, and Security."""

from pathlib import Path
from urllib.parse import quote

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from intelx.app.factory import create_app
from intelx.core.auth import hash_api_key
from intelx.core.enums import ApiKeyRole, ClaimType, SourceKind, TrustTier
from intelx.db.models import ApiKey, Claim, Source
from intelx.db.repos import ClaimRepo, RunRepo
from intelx.db.session import get_sessionmaker
from intelx.orchestration.worker import OrchestrationWorker
from intelx.web.renderer import render_markdown_safe


@pytest_asyncio.fixture
async def web_client():
    """Create test client with initialized database schemas and seeded API keys."""
    app = create_app()
    admin_key_raw = "intelx_admin_web_test_key"
    member_key_raw = "intelx_member_web_test_key"

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        k_admin = ApiKey(
            key_hash=hash_api_key(admin_key_raw),
            name="web-admin",
            role=ApiKeyRole.ADMIN,
        )
        k_member = ApiKey(
            key_hash=hash_api_key(member_key_raw),
            name="web-member",
            role=ApiKeyRole.MEMBER,
        )
        session.add_all([k_admin, k_member])
        await session.commit()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        client.admin_key = admin_key_raw
        client.member_key = member_key_raw
        yield client


@pytest.mark.asyncio
async def test_web_auth_flow_and_protection(web_client):
    """Verify anonymous access redirects to /login and valid login sets signed session cookie."""
    # 1. Anonymous access redirects
    res_anon = await web_client.get("/")
    assert res_anon.status_code == 307
    assert res_anon.headers.get("Location") == "/login"

    # 2. Invalid API key fails with error
    res_bad_login = await web_client.post("/login", data={"api_key": "invalid_secret_key"})
    assert res_bad_login.status_code == 401
    assert "Invalid API key" in res_bad_login.text

    # 3. Valid login sets cookie
    res_login = await web_client.post("/login", data={"api_key": web_client.admin_key})
    assert res_login.status_code == 303
    assert res_login.headers.get("Location") == "/"
    assert "intelx_session" in res_login.cookies

    # 4. Authenticated access succeeds
    web_client.cookies.set("intelx_session", res_login.cookies["intelx_session"])
    res_dash = await web_client.get("/")
    assert res_dash.status_code == 200
    assert "Research,<br><em>with receipts.</em>" in res_dash.text
    assert "Workspace pulse" in res_dash.text
    assert "web-admin" in res_dash.text
    web_client.cookies.clear()


@pytest.mark.asyncio
async def test_xss_protection_in_markdown_renderer():
    """Verify raw HTML and script tags in markdown are safely escaped."""
    malicious_md = """# Research Report: XSS Injection Test
## Direct Answer
Normal analysis <script>alert('XSS-Vulnerability');</script> with <b>bold text</b> and [C:c1234567].
"""
    html_output = render_markdown_safe(malicious_md)
    assert "<script>" not in html_output
    assert "&lt;script&gt;alert(" in html_output
    assert "citation-badge citation-claim" in html_output


@pytest.mark.asyncio
async def test_role_based_navigation_and_action_guards(web_client):
    """Verify admin endpoints return 403 for member sessions."""
    # Login as Member
    res_login = await web_client.post("/login", data={"api_key": web_client.member_key})
    web_client.cookies.set("intelx_session", res_login.cookies["intelx_session"])

    # Member cannot access review or audit page
    res_review = await web_client.get("/review")
    assert res_review.status_code == 403

    res_audit = await web_client.get("/admin/audit")
    assert res_audit.status_code == 403
    web_client.cookies.clear()


@pytest.mark.asyncio
async def test_full_web_lifecycle_and_citation_drawer(web_client):
    """Verify complete web flow: submit research -> poll job -> open report -> inspect citations."""
    fixture_path = (
        Path(__file__).resolve().parent / "fixtures" / "docs" / "sample_battery.txt"
    ).resolve()

    # 1. Login as Admin
    res_login = await web_client.post("/login", data={"api_key": web_client.admin_key})
    web_client.cookies.set("intelx_session", res_login.cookies["intelx_session"])

    # 2. Submit Research via Web Form
    form_data = {
        "objective": "Assess sodium battery degradation mechanisms",
        "depth": "standard",
        "max_sources": 20,
        "max_usd": 5.0,
        "max_minutes": 10,
        "allowed_domains": "local",
        "blocked_domains": "",
    }
    res_submit = await web_client.post("/research/new", data=form_data)
    assert res_submit.status_code == 303
    job_url = res_submit.headers["Location"]
    job_id = job_url.split("/")[-1]

    # Ingest a source, claim, and evidence span for synthesis
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        from intelx.memory.normalize import ingest_and_normalize

        text_content = fixture_path.read_text(encoding="utf-8")
        source, doc, chunks, _ = await ingest_and_normalize(
            session=session,
            raw_bytes=text_content.encode("utf-8"),
            location=str(fixture_path),
            kind="FILE",
            created_by_run_id=job_id,
        )
        quote = "significant thermal stability"
        sp_start = text_content.index(quote)
        sp_end = sp_start + len(quote)
        claim = await ClaimRepo.create_claim(
            session=session,
            run_id=job_id,
            source_id=source.id,
            document_id=doc.id,
            chunk_id=chunks[0].id,
            text_content="Electrolyte demonstrates high thermal stability under cyclical loads.",
            quote=quote,
            span_start=sp_start,
            span_end=sp_end,
            claim_type="FACT",
        )
        await session.commit()
        claim_id = claim.id
        source_id = source.id

    # 3. Process the run via OrchestrationWorker
    worker = OrchestrationWorker()
    await worker.run_once(sessionmaker)

    # 4. View Report Page
    res_report = await web_client.get(f"/research/{job_id}/report")
    assert res_report.status_code == 200
    assert f"[C:{claim_id}]" in res_report.text
    assert f"[S:{source_id}]" in res_report.text
    assert "Not recorded; freshness unknown" in res_report.text
    assert "Retrieval time does not establish currentness." in res_report.text

    # Assert 9 core report sections are present in rendered HTML
    assert "Direct Answer" in res_report.text
    assert "Key Findings" in res_report.text
    assert "Evidence Map" in res_report.text
    assert (
        "Contradictions &amp; Disagreements" in res_report.text
        or "Contradictions & Disagreements" in res_report.text
    )
    assert "What We Could Not Establish" in res_report.text
    assert (
        "Limitations &amp; Criticisms" in res_report.text
        or "Limitations & Criticisms" in res_report.text
    )
    assert "Degradations" in res_report.text
    assert "Methodology Note" in res_report.text
    assert "Sources" in res_report.text

    # 5. Citation Details Endpoint Verification
    res_claim_cite = await web_client.get(f"/api/citation/C/{claim_id[:8]}")
    assert res_claim_cite.status_code == 200
    claim_data = res_claim_cite.json()
    assert claim_data["id"] == claim_id
    assert "thermal stability" in claim_data["text"]

    res_source_cite = await web_client.get(f"/api/citation/S/{source_id[:8]}")
    assert res_source_cite.status_code == 200
    source_data = res_source_cite.json()
    assert source_data["id"] == source_id
    assert source_data["published_at"] is None
    assert source_data["retrieved_at"]
    web_client.cookies.clear()


@pytest.mark.asyncio
async def test_citation_drawer_rejects_ambiguous_prefixes(web_client):
    login = await web_client.post("/login", data={"api_key": web_client.admin_key})
    web_client.cookies.set("intelx_session", login.cookies["intelx_session"])
    source_ids = ("source-01aaaaaaaaaaaaaaaaaaaaaaaa", "source-01bbbbbbbbbbbbbbbbbbbbbbbb")
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        session.add_all(
            [
                Source(
                    id=source_id,
                    kind=SourceKind.FILE,
                    location=f"/{source_id}",
                    title=source_id,
                    fingerprint=str(index) * 64,
                    trust_tier=TrustTier.STANDARD,
                )
                for index, source_id in enumerate(source_ids, 1)
            ]
        )
        await session.commit()

    ambiguous = await web_client.get("/api/citation/S/source-01")
    assert ambiguous.status_code == 409
    uniquely_resolved = await web_client.get("/api/citation/S/source-01a")
    assert uniquely_resolved.status_code == 200
    assert uniquely_resolved.json()["id"] == source_ids[0]
    web_client.cookies.clear()


@pytest.mark.asyncio
async def test_citation_drawer_rejects_ambiguous_claim_prefixes(web_client):
    login = await web_client.post("/login", data={"api_key": web_client.admin_key})
    web_client.cookies.set("intelx_session", login.cookies["intelx_session"])
    claim_ids = (
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        "aaaaaaaa-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    )
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        from intelx.memory.normalize import ingest_and_normalize

        run = await RunRepo.create_run(
            session=session,
            objective="Verify stable claim citation resolution",
            created_by="web-test",
        )
        text_content = "Evidence for claim citation resolution."
        source, doc, chunks, _ = await ingest_and_normalize(
            session=session,
            raw_bytes=text_content.encode("utf-8"),
            location="/web-test/claim-citation-resolution.txt",
            kind="FILE",
            created_by_run_id=run.id,
        )
        session.add_all(
            [
                Claim(
                    id=claim_id,
                    run_id=run.id,
                    source_id=source.id,
                    document_id=doc.id,
                    chunk_id=chunks[0].id,
                    text=f"Claim {index} backed by the same verified quote.",
                    claim_type=ClaimType.FACT,
                    quote="Evidence",
                    span_start=0,
                    span_end=len("Evidence"),
                    created_by_agent="web-test",
                )
                for index, claim_id in enumerate(claim_ids, 1)
            ]
        )
        await session.commit()

    ambiguous = await web_client.get("/api/citation/C/aaaaaaaa")
    assert ambiguous.status_code == 409
    uniquely_resolved = await web_client.get("/api/citation/C/aaaaaaaa-aaaa")
    assert uniquely_resolved.status_code == 200
    assert uniquely_resolved.json()["id"] == claim_ids[0]
    web_client.cookies.clear()


@pytest.mark.asyncio
async def test_citation_drawer_treats_like_wildcards_literally(web_client):
    login = await web_client.post("/login", data={"api_key": web_client.admin_key})
    web_client.cookies.set("intelx_session", login.cookies["intelx_session"])
    source_ids = ("src%_literalA", "srcXYliteralB", "noneABliteralC")
    claim_ids = ("clm%_literalA", "clmXYliteralB", "absentABliteralC")
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        from intelx.memory.normalize import ingest_and_normalize

        run = await RunRepo.create_run(
            session=session,
            objective="Verify literal citation token matching",
            created_by="web-test",
        )
        evidence_text = "Evidence for literal citation token matching."
        source, doc, chunks, _ = await ingest_and_normalize(
            session=session,
            raw_bytes=evidence_text.encode("utf-8"),
            location="/web-test/literal-citation-matching.txt",
            kind="FILE",
            created_by_run_id=run.id,
        )
        seeded_sources = [
            Source(
                id=source_id,
                kind=SourceKind.FILE,
                location=f"/{source_id}",
                title=source_id,
                fingerprint=str(index) * 64,
                trust_tier=TrustTier.STANDARD,
            )
            for index, source_id in enumerate(source_ids, 1)
        ]
        seeded_claims = [
            Claim(
                id=claim_id,
                run_id=run.id,
                source_id=source.id,
                document_id=doc.id,
                chunk_id=chunks[0].id,
                text=f"Claim {index} backed by verified evidence.",
                claim_type=ClaimType.FACT,
                quote="Evidence",
                span_start=0,
                span_end=len("Evidence"),
                created_by_agent="web-test",
            )
            for index, claim_id in enumerate(claim_ids, 1)
        ]
        session.add_all([*seeded_sources, *seeded_claims])
        await session.commit()

    source_token = "src%_"
    source_match = await web_client.get(
        f"/api/citation/S/{quote(source_token, safe='')}"
    )
    assert source_match.status_code == 200
    assert source_match.json()["id"] == source_ids[0]
    source_missing = await web_client.get(
        f"/api/citation/S/{quote('none%_', safe='')}"
    )
    assert source_missing.status_code == 404

    claim_token = "clm%_"
    claim_match = await web_client.get(
        f"/api/citation/C/{quote(claim_token, safe='')}"
    )
    assert claim_match.status_code == 200
    assert claim_match.json()["id"] == claim_ids[0]
    claim_missing = await web_client.get(
        f"/api/citation/C/{quote('absent%_', safe='')}"
    )
    assert claim_missing.status_code == 404
    web_client.cookies.clear()
