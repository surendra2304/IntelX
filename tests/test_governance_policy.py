"""Tests for INTELX Policy Engine, Governance Rules, and Denial Audits."""

import pytest
from sqlalchemy import select

from intelx.core.policy import PolicyConfig, PolicyEngine
from intelx.db.models import AuditEvent
from intelx.db.session import get_sessionmaker


@pytest.mark.asyncio
async def test_policy_config_defaults_and_validation():
    """Verify default policy configuration properties and custom instantiation."""
    default_cfg = PolicyConfig()
    assert default_cfg.max_sources_per_run == 50
    assert default_cfg.max_run_usd == 10.0
    assert default_cfg.max_run_minutes == 30
    assert "HTTP" in default_cfg.allowed_connector_kinds
    assert ".exe" in default_cfg.blocked_file_extensions

    custom_cfg = PolicyConfig(
        domain_allowlist=["nature.com", "arxiv.org"],
        domain_denylist=["malicious.cc"],
        max_run_usd=25.0,
        allowed_connector_kinds=["HTTP"],
    )
    assert custom_cfg.max_run_usd == 25.0
    assert "arxiv.org" in custom_cfg.domain_allowlist


@pytest.mark.asyncio
async def test_policy_engine_get_and_update_config():
    """Verify loading from cache/db, creating new config, and updating version with audit trail."""
    sessionmaker = get_sessionmaker()
    engine = PolicyEngine()

    # 1. No session returns cached config and version 1
    cfg, ver = await engine.get_config(session=None)
    assert ver == 1
    assert cfg.max_sources_per_run == 50

    async with sessionmaker() as session:
        # 2. Database empty initially -> returns cached config
        cfg_db, ver_db = await engine.get_config(session)
        assert ver_db == 1

        # 3. First update creates row version 1
        new_cfg = PolicyConfig(
            domain_allowlist=["reputable-science.org"],
            domain_denylist=["phishing.net"],
            max_run_usd=15.0,
        )
        policy_row = await engine.update_config(session, new_cfg, updated_by="sec_admin")
        assert policy_row.version == 1
        assert policy_row.updated_by == "sec_admin"
        await session.commit()

        # 4. Verify get_config reads updated row from database
        cfg_loaded, ver_loaded = await engine.get_config(session)
        assert ver_loaded == 1
        assert cfg_loaded.max_run_usd == 15.0
        assert "phishing.net" in cfg_loaded.domain_denylist

        # 5. Second update increments version to 2
        updated_cfg = PolicyConfig(
            domain_allowlist=["reputable-science.org", "ieee.org"],
            domain_denylist=["phishing.net", "botnet.org"],
            max_run_usd=20.0,
        )
        policy_row2 = await engine.update_config(session, updated_cfg, updated_by="lead_architect")
        assert policy_row2.version == 2
        await session.commit()

        # 6. Verify audit event was logged
        events = (
            (await session.execute(select(AuditEvent).where(AuditEvent.action == "policy.updated")))
            .scalars()
            .all()
        )
        assert len(events) >= 2


@pytest.mark.asyncio
async def test_policy_engine_domain_evaluations():
    """Verify domain allowlist and denylist enforcement with audit logging."""
    sessionmaker = get_sessionmaker()
    custom_cfg = PolicyConfig(
        domain_allowlist=["trusted-news.com", "gov.uk"],
        domain_denylist=["untrusted-scam.com", "malware.io"],
    )
    engine = PolicyEngine(cached_config=custom_cfg)

    async with sessionmaker() as session:
        # Denylisted domain (exact match)
        dec_deny = await engine.evaluate(
            action="web.fetch",
            context={"url": "https://untrusted-scam.com/article", "actor": "crawler_1"},
            session=session,
        )
        assert dec_deny.allowed is False
        assert "explicitly denylisted" in dec_deny.reason

        # Denylisted subdomain
        dec_sub_deny = await engine.evaluate(
            action="web.fetch",
            context={"url": "https://sub.malware.io/payload", "actor": "crawler_1"},
            session=session,
        )
        assert dec_sub_deny.allowed is False
        assert "explicitly denylisted" in dec_sub_deny.reason

        # Not on allowlist
        dec_not_allowed = await engine.evaluate(
            action="web.fetch",
            context={"url": "https://random-blog.xyz/post", "actor": "crawler_1"},
            session=session,
        )
        assert dec_not_allowed.allowed is False
        assert "not on the policy allowlist" in dec_not_allowed.reason

        # Matching allowlist (allowed)
        dec_ok = await engine.evaluate(
            action="web.fetch",
            context={"url": "https://trusted-news.com/tech-report", "actor": "crawler_1"},
            session=session,
        )
        assert dec_ok.allowed is True
        assert dec_ok.reason is None

        # Local file bypasses domain allowlist
        dec_local = await engine.evaluate(
            action="file.read",
            context={"url": "/local/data/notes.txt"},
            session=session,
        )
        assert dec_local.allowed is True

        # Check denial audit events were appended
        denials = (
            (await session.execute(select(AuditEvent).where(AuditEvent.action == "policy.denied")))
            .scalars()
            .all()
        )
        assert len(denials) >= 3


@pytest.mark.asyncio
async def test_policy_engine_file_extensions_and_connectors():
    """Verify blocked file extensions and connector kinds are denied with reasons."""
    sessionmaker = get_sessionmaker()
    cfg = PolicyConfig(
        blocked_file_extensions=[".exe", ".sh", ".ps1"],
        allowed_connector_kinds=["HTTP", "SEARCH"],
        max_run_usd=10.0,
    )
    engine = PolicyEngine(cached_config=cfg)

    async with sessionmaker() as session:
        # Blocked executable file
        dec_file = await engine.evaluate(
            action="file.ingest",
            context={"file_path": "/uploads/installer.EXE"},
            session=session,
        )
        assert dec_file.allowed is False
        assert "File extension '.exe' is blocked" in dec_file.reason

        # Allowed file
        dec_file_ok = await engine.evaluate(
            action="file.ingest",
            context={"file_path": "/uploads/dataset.csv"},
            session=session,
        )
        assert dec_file_ok.allowed is True

        # Disallowed connector kind
        dec_conn = await engine.evaluate(
            action="connector.execute",
            context={"connector_kind": "FTP"},
            session=session,
        )
        assert dec_conn.allowed is False
        assert "Connector kind 'FTP' is disabled" in dec_conn.reason

        # Allowed connector kind
        dec_conn_ok = await engine.evaluate(
            action="connector.execute",
            context={"connector_kind": "HTTP"},
            session=session,
        )
        assert dec_conn_ok.allowed is True

        # Exceeded budget cap
        dec_budget = await engine.evaluate(
            action="research.create",
            context={"max_usd": 50.0},
            session=session,
        )
        assert dec_budget.allowed is False
        assert "exceeds policy ceiling" in dec_budget.reason

        # Compliant budget
        dec_budget_ok = await engine.evaluate(
            action="research.create",
            context={"max_usd": 5.0},
            session=session,
        )
        assert dec_budget_ok.allowed is True


@pytest.mark.asyncio
async def test_policy_connector_guard_wrapper():
    """Verify create_connector_guard generates a working callable with and without session factory."""
    sessionmaker = get_sessionmaker()
    cfg = PolicyConfig(
        domain_denylist=["forbidden-origin.org"],
        blocked_file_extensions=[".sh"],
    )
    engine = PolicyEngine(cached_config=cfg)

    # 1. With session factory
    guard_with_session = engine.create_connector_guard(session_factory=sessionmaker)
    allowed_url = await guard_with_session("https://valid-origin.org/data")
    assert allowed_url is True

    denied_url = await guard_with_session("https://forbidden-origin.org/data")
    assert denied_url is False

    # 2. Without session factory (in-memory evaluation)
    guard_standalone = engine.create_connector_guard(session_factory=None)
    allowed_standalone = await guard_standalone("https://another-valid.org/test")
    assert allowed_standalone is True

    denied_file = await guard_standalone("/scripts/run.sh")
    assert denied_file is False
