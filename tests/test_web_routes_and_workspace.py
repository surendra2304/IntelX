"""Comprehensive integration tests for the INTELX Server-Rendered Web Workspace."""

import pytest
from httpx import ASGITransport, AsyncClient

from intelx.app.factory import create_app
from intelx.core.auth import hash_api_key
from intelx.core.enums import ApiKeyRole, ClaimStatus, ClaimType, RunStatus, SourceKind, TrustTier
from intelx.db.models import ApiKey
from intelx.db.repos import ClaimRepo, RunRepo, SourceRepo
from intelx.db.session import get_sessionmaker
from intelx.web.auth import COOKIE_NAME, sign_session_data


@pytest.fixture
async def web_client():
    """Create async HTTP client wired to IntelX ASGI application."""
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


@pytest.fixture
async def seeded_web_keys():
    """Seed test admin and read-only user API keys."""
    sessionmaker = get_sessionmaker()
    admin_raw = "admin-secret-key-super-secure-12345"
    reader_raw = "reader-secret-key-normal-user-12345"

    admin_hash = hash_api_key(admin_raw)
    reader_hash = hash_api_key(reader_raw)

    async with sessionmaker() as session:
        # Check if already exists
        k_admin = await session.get(ApiKey, "key-web-admin-001")
        if not k_admin:
            k_admin = ApiKey(
                id="key-web-admin-001",
                key_hash=admin_hash,
                name="Web Admin Tester",
                role=ApiKeyRole.ADMIN,
                revoked=False,
            )
            session.add(k_admin)

        k_reader = await session.get(ApiKey, "key-web-reader-001")
        if not k_reader:
            k_reader = ApiKey(
                id="key-web-reader-001",
                key_hash=reader_hash,
                name="Web Reader Tester",
                role=ApiKeyRole.MEMBER,
                revoked=False,
            )
            session.add(k_reader)

        await session.commit()

    admin_token = sign_session_data(
        {"key_hash": admin_hash, "name": "Web Admin Tester", "role": "ADMIN"}
    )
    reader_token = sign_session_data(
        {"key_hash": reader_hash, "name": "Web Reader Tester", "role": "MEMBER"}
    )

    return {
        "admin_raw": admin_raw,
        "reader_raw": reader_raw,
        "admin_cookie": {COOKIE_NAME: admin_token},
        "reader_cookie": {COOKIE_NAME: reader_token},
    }


@pytest.mark.asyncio
async def test_web_auth_login_logout_flow(web_client: AsyncClient, seeded_web_keys: dict):
    """Verify login page rendering, authentication failure, success cookie setting, and logout."""
    # 1. Anonymous visiting /login renders login form
    res_login_page = await web_client.get("/login")
    assert res_login_page.status_code == 200
    assert "Login" in res_login_page.text

    # 2. Invalid API key -> 401 with error message
    res_bad_login = await web_client.post("/login", data={"api_key": "wrong-invalid-key"})
    assert res_bad_login.status_code == 401
    assert "Verification failed" in res_bad_login.text

    # 3. Valid admin key -> 303 redirect with session cookie
    res_ok_login = await web_client.post(
        "/login", data={"api_key": seeded_web_keys["admin_raw"]}, follow_redirects=False
    )
    assert res_ok_login.status_code in (302, 303)
    assert res_ok_login.headers["location"] == "/"
    assert COOKIE_NAME in res_ok_login.cookies

    # 4. Visiting /login while already authenticated redirects to /
    res_already_logged = await web_client.get(
        "/login", cookies=seeded_web_keys["admin_cookie"], follow_redirects=False
    )
    assert res_already_logged.status_code == 302
    assert res_already_logged.headers["location"] == "/"

    # 5. Logout clears cookie and redirects to /login
    res_logout = await web_client.get(
        "/logout", cookies=seeded_web_keys["admin_cookie"], follow_redirects=False
    )
    assert res_logout.status_code in (302, 303)
    assert res_logout.headers["location"] == "/login"


@pytest.mark.asyncio
async def test_web_dashboard_and_anonymous_redirect(web_client: AsyncClient, seeded_web_keys: dict):
    """Verify unauthenticated redirect and authenticated dashboard rendering."""
    # 1. Anonymous request to / redirects to /login with 307
    res_anon = await web_client.get("/", follow_redirects=False)
    assert res_anon.status_code == 307
    assert res_anon.headers["location"] == "/login"

    # 2. Authenticated request renders dashboard HTML
    res_auth = await web_client.get("/", cookies=seeded_web_keys["admin_cookie"])
    assert res_auth.status_code == 200
    assert "IntelX" in res_auth.text
    assert "Dashboard" in res_auth.text or "Research" in res_auth.text


@pytest.mark.asyncio
async def test_web_research_submission_and_autonomous_trigger(
    web_client: AsyncClient, seeded_web_keys: dict
):
    """Verify /research/new form rendering, job creation submission, and autonomous trigger."""
    cookies = seeded_web_keys["admin_cookie"]

    # 1. GET /research/new renders form
    res_form = await web_client.get("/research/new", cookies=cookies)
    assert res_form.status_code == 200
    assert "New Research" in res_form.text

    # 2. POST /research/new submits new investigation
    form_data = {
        "objective": "Assess global sodium-ion cell supply chain constraints",
        "domain": "energy",
        "depth": "quick",
        "max_sources": "10",
        "max_time": "15",
    }
    res_submit = await web_client.post(
        "/research/new", data=form_data, cookies=cookies, follow_redirects=False
    )
    assert res_submit.status_code == 303
    loc = res_submit.headers["location"]
    assert loc.startswith("/research/")

    # 3. POST /research/trigger-autonomous triggers background run and redirects to /research/{run_id}
    res_auto = await web_client.post(
        "/research/trigger-autonomous", cookies=cookies, follow_redirects=False
    )
    assert res_auto.status_code == 303
    assert res_auto.headers["location"].startswith("/research/")


@pytest.mark.asyncio
async def test_web_job_detail_report_and_cancellation(
    web_client: AsyncClient, seeded_web_keys: dict
):
    """Verify job viewing, markdown report rendering, and cancellation."""
    cookies = seeded_web_keys["admin_cookie"]
    sessionmaker = get_sessionmaker()

    # Create test run in database
    async with sessionmaker() as session:
        run = await RunRepo.create_run(
            session=session,
            objective="Inspect quantum computing superconductor thermal noise",
            scope_json={"domain": "quantum"},
        )
        await session.commit()
        run_id = run.id

    # 1. GET /research/{job_id} renders job page
    res_job = await web_client.get(f"/research/{run_id}", cookies=cookies)
    assert res_job.status_code == 200
    assert "quantum" in res_job.text.lower()

    # 2. GET /research/{job_id}/report renders markdown report
    res_report = await web_client.get(f"/research/{run_id}/report", cookies=cookies)
    assert res_report.status_code == 200

    # 3. POST /research/{job_id}/cancel cancels run
    res_cancel = await web_client.post(
        f"/research/{run_id}/cancel", cookies=cookies, follow_redirects=False
    )
    assert res_cancel.status_code == 303
    assert res_cancel.headers["location"] == f"/research/{run_id}"

    # Verify run is CANCELLED in DB
    async with sessionmaker() as session:
        updated = await RunRepo.get_run(session, run_id)
        assert updated is not None
        assert updated.status == RunStatus.CANCELLED


@pytest.mark.asyncio
async def test_web_citation_resolver_endpoint(web_client: AsyncClient, seeded_web_keys: dict):
    """Verify /api/citation/S/{token} and /api/citation/C/{token} resolution."""
    cookies = seeded_web_keys["admin_cookie"]
    sessionmaker = get_sessionmaker()

    # Create Source, Document, Chunk, and Claim
    async with sessionmaker() as session:
        src = await SourceRepo.create_source(
            session=session,
            kind=SourceKind.WEB,
            location="https://science.org/battery-breakthrough-2026",
            title="Science Battery 2026",
        )
        quote_text = "Cathode energy reaches 240 Wh/kg."
        doc = await SourceRepo.create_document(session, src.id, quote_text)
        chunk = await SourceRepo.create_chunk(session, doc.id, 0, 0, len(quote_text), quote_text)

        run = await RunRepo.create_run(session, objective="Citation test run")
        claim = await ClaimRepo.create_claim(
            session=session,
            run_id=run.id,
            source_id=src.id,
            document_id=doc.id,
            chunk_id=chunk.id,
            text_content="Sodium cathode energy density reaches 240 Wh/kg.",
            quote=quote_text,
            span_start=0,
            span_end=len(quote_text),
            claim_type=ClaimType.FACT,
            status=ClaimStatus.ACTIVE,
        )
        await session.commit()
        src_id = src.id
        claim_id = claim.id

    # 1. Resolve source by ID prefix
    res_src = await web_client.get(f"/api/citation/S/{src_id[:8]}", cookies=cookies)
    assert res_src.status_code == 200
    src_data = res_src.json()
    assert src_data["id"] == src_id
    assert src_data["title"] == "Science Battery 2026"

    # 2. Resolve claim by ID prefix
    res_claim = await web_client.get(f"/api/citation/C/{claim_id[:8]}", cookies=cookies)
    assert res_claim.status_code == 200
    cl_data = res_claim.json()
    assert cl_data["id"] == claim_id
    assert "240 Wh/kg" in cl_data["text"]

    # 3. Invalid kind -> 400
    res_inv_kind = await web_client.get(f"/api/citation/Z/{src_id[:8]}", cookies=cookies)
    assert res_inv_kind.status_code == 400

    # 4. Unknown token -> 404
    res_unknown = await web_client.get("/api/citation/S/nonexistent-token", cookies=cookies)
    assert res_unknown.status_code == 404


@pytest.mark.asyncio
async def test_web_review_queue_and_admin_authorization(
    web_client: AsyncClient, seeded_web_keys: dict
):
    """Verify role-based access control and review gate actions."""
    admin_cookies = seeded_web_keys["admin_cookie"]
    reader_cookies = seeded_web_keys["reader_cookie"]
    sessionmaker = get_sessionmaker()

    # 1. Non-admin user gets 403 Forbidden on review page
    res_forbidden = await web_client.get("/review", cookies=reader_cookies)
    assert res_forbidden.status_code == 403

    # 2. Admin user accesses /review successfully
    res_admin = await web_client.get("/review", cookies=admin_cookies)
    assert res_admin.status_code == 200
    assert "Review" in res_admin.text

    # Create run and source needing review
    async with sessionmaker() as session:
        run = await RunRepo.create_run(session, objective="Review decision target")
        run.status = RunStatus.REVIEW_REQUIRED
        src = await SourceRepo.create_source(
            session=session,
            kind=SourceKind.WEB,
            location="https://unknown-blog.com/post",
            title="Quarantine Source",
        )
        src.trust_tier = TrustTier.QUARANTINE
        await session.commit()
        run_id = run.id
        src_id = src.id

    # 3. Submit review decision for job -> APPROVED
    res_dec = await web_client.post(
        f"/review/job/{run_id}",
        data={"decision": "APPROVED", "notes": "Approved after manual audit"},
        cookies=admin_cookies,
        follow_redirects=False,
    )
    assert res_dec.status_code == 303
    assert res_dec.headers["location"] == "/review"

    # Verify run re-queued with decision
    async with sessionmaker() as session:
        reviewed_run = await RunRepo.get_run(session, run_id)
        assert reviewed_run is not None
        assert reviewed_run.status == RunStatus.QUEUED
        assert reviewed_run.scope_json["review_decision"] == "APPROVED"

    # 4. Submit source trust update -> STANDARD
    res_src_tier = await web_client.post(
        f"/review/source/{src_id}",
        data={"tier": "STANDARD"},
        cookies=admin_cookies,
        follow_redirects=False,
    )
    assert res_src_tier.status_code == 303
    assert res_src_tier.headers["location"] == "/review"

    # Verify source trust updated
    async with sessionmaker() as session:
        updated_src = await SourceRepo.get_source(session, src_id)
        assert updated_src is not None
        assert updated_src.trust_tier == TrustTier.STANDARD


@pytest.mark.asyncio
async def test_web_knowledge_and_admin_audit_ledger(web_client: AsyncClient, seeded_web_keys: dict):
    """Verify knowledge base search and audit ledger rendering."""
    admin_cookies = seeded_web_keys["admin_cookie"]

    # 1. Knowledge search empty query
    res_k_empty = await web_client.get("/knowledge", cookies=admin_cookies)
    assert res_k_empty.status_code == 200
    assert "Knowledge" in res_k_empty.text

    # 2. Knowledge search with query string
    res_k_query = await web_client.get("/knowledge?q=lithium", cookies=admin_cookies)
    assert res_k_query.status_code == 200

    # 3. Admin audit ledger
    res_audit = await web_client.get("/admin/audit", cookies=admin_cookies)
    assert res_audit.status_code == 200
    assert "Audit" in res_audit.text
