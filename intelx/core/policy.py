"""INTELX Dynamic Policy Engine, Governance Rules, and Denial Audit Logging."""

import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from intelx.db.models import Policy
from intelx.db.repos import AuditChain

logger = logging.getLogger(__name__)


class PolicyConfig(BaseModel):
    """Structured policy configuration model."""

    domain_allowlist: list[str] = Field(default_factory=list)
    domain_denylist: list[str] = Field(default_factory=list)
    max_sources_per_run: int = 50
    allowed_connector_kinds: list[str] = Field(default_factory=lambda: ["HTTP", "SEARCH", "FILE"])
    blocked_file_extensions: list[str] = Field(
        default_factory=lambda: [".exe", ".bat", ".cmd", ".sh", ".ps1", ".vbs", ".dll", ".so"]
    )
    max_run_usd: float = 10.0
    max_run_minutes: int = 30


class PolicyDecision(BaseModel):
    """Evaluation result with optional denial rationale."""

    allowed: bool
    reason: str | None = None


class PolicyEngine:
    """Evaluates security and governance constraints on retrieval, actions, and job submission."""

    DEFAULT_POLICY_KEY = "global_governance_policy"

    def __init__(self, cached_config: PolicyConfig | None = None) -> None:
        self._cached_config = cached_config or PolicyConfig()

    async def get_config(self, session: AsyncSession | None = None) -> tuple[PolicyConfig, int]:
        """Fetch active policy configuration from database or memory."""
        if not session:
            return self._cached_config, 1

        stmt = select(Policy).where(Policy.key == self.DEFAULT_POLICY_KEY)
        res = await session.execute(stmt)
        policy_row = res.scalar_one_or_none()
        if not policy_row:
            return self._cached_config, 1

        cfg = PolicyConfig.model_validate(policy_row.value_json)
        self._cached_config = cfg
        return cfg, policy_row.version

    async def update_config(
        self, session: AsyncSession, new_config: PolicyConfig, updated_by: str
    ) -> Policy:
        """Update and version policy configuration with audit logging."""
        stmt = select(Policy).where(Policy.key == self.DEFAULT_POLICY_KEY)
        res = await session.execute(stmt)
        policy_row = res.scalar_one_or_none()

        if policy_row:
            policy_row.version += 1
            policy_row.value_json = new_config.model_dump()
            policy_row.updated_by = updated_by
            policy_row.updated_at = datetime.now(UTC)
        else:
            policy_row = Policy(
                key=self.DEFAULT_POLICY_KEY,
                value_json=new_config.model_dump(),
                version=1,
                updated_by=updated_by,
                updated_at=datetime.now(UTC),
            )
            session.add(policy_row)

        await session.flush()
        self._cached_config = new_config

        # Record audit event
        await AuditChain.append_event(
            session=session,
            actor=updated_by,
            action="policy.updated",
            object_type="policy",
            object_id=policy_row.id,
            detail_json={
                "version": policy_row.version,
                "config": new_config.model_dump(),
            },
        )
        return policy_row

    async def evaluate(
        self,
        action: str,
        context: dict[str, Any],
        session: AsyncSession | None = None,
    ) -> PolicyDecision:
        """Evaluate policy constraints for a proposed action and record denials."""
        config, _ = await self.get_config(session)

        # 1. URL / Domain checks
        url = context.get("url") or context.get("location")
        if url:
            parsed = urlparse(str(url))
            domain = parsed.netloc.lower()
            if not domain and not parsed.scheme:
                # File path or raw location
                domain = "local"

            # Check denylist
            for blocked in config.domain_denylist:
                b_clean = blocked.strip().lower()
                if b_clean and (domain == b_clean or domain.endswith(f".{b_clean}")):
                    reason = f"Domain '{domain}' is explicitly denylisted by policy"
                    if session:
                        await AuditChain.append_event(
                            session=session,
                            actor=context.get("actor", "system"),
                            action="policy.denied",
                            object_type="domain",
                            object_id=domain,
                            detail_json={"action": action, "reason": reason, "url": str(url)},
                        )
                    return PolicyDecision(allowed=False, reason=reason)

            # Check allowlist if populated
            if config.domain_allowlist and domain != "local":
                matched = any(
                    domain == a.strip().lower() or domain.endswith(f".{a.strip().lower()}")
                    for a in config.domain_allowlist
                    if a.strip()
                )
                if not matched:
                    reason = f"Domain '{domain}' is not on the policy allowlist"
                    if session:
                        await AuditChain.append_event(
                            session=session,
                            actor=context.get("actor", "system"),
                            action="policy.denied",
                            object_type="domain",
                            object_id=domain,
                            detail_json={"action": action, "reason": reason, "url": str(url)},
                        )
                    return PolicyDecision(allowed=False, reason=reason)

        # 2. File extension checks
        file_path = context.get("file_path") or context.get("location")
        if file_path:
            p_str = str(file_path).lower()
            for ext in config.blocked_file_extensions:
                if p_str.endswith(ext.lower()):
                    reason = f"File extension '{ext}' is blocked by policy"
                    if session:
                        await AuditChain.append_event(
                            session=session,
                            actor=context.get("actor", "system"),
                            action="policy.denied",
                            object_type="file_extension",
                            object_id=ext,
                            detail_json={"action": action, "reason": reason, "path": p_str},
                        )
                    return PolicyDecision(allowed=False, reason=reason)

        # 3. Connector kind checks
        connector_kind = context.get("connector_kind")
        if connector_kind and config.allowed_connector_kinds:
            if str(connector_kind).upper() not in [
                k.upper() for k in config.allowed_connector_kinds
            ]:
                reason = f"Connector kind '{connector_kind}' is disabled by policy"
                if session:
                    await AuditChain.append_event(
                        session=session,
                        actor=context.get("actor", "system"),
                        action="policy.denied",
                        object_type="connector_kind",
                        object_id=str(connector_kind),
                        detail_json={"action": action, "reason": reason},
                    )
                return PolicyDecision(allowed=False, reason=reason)

        # 4. Budget cap checks
        requested_usd = context.get("max_usd")
        if requested_usd is not None and float(requested_usd) > config.max_run_usd:
            reason = (
                f"Requested budget (${requested_usd}) "
                f"exceeds policy ceiling (${config.max_run_usd})"
            )
            if session:
                await AuditChain.append_event(
                    session=session,
                    actor=context.get("actor", "system"),
                    action="policy.denied",
                    object_type="budget",
                    object_id=str(requested_usd),
                    detail_json={"action": action, "reason": reason},
                )
            return PolicyDecision(allowed=False, reason=reason)

        return PolicyDecision(allowed=True, reason=None)

    def create_connector_guard(self, session_factory: Any | None = None):
        """Create a callable guard suitable for injection into connectors."""

        async def _guard(location_or_url: str, context: dict[str, Any] | None = None) -> bool:
            ctx = dict(context or {})
            ctx["location"] = location_or_url
            if session_factory:
                async with session_factory() as session:
                    dec = await self.evaluate("connector.fetch", ctx, session=session)
                    await session.commit()
                    return dec.allowed
            dec = await self.evaluate("connector.fetch", ctx)
            return dec.allowed

        return _guard


# Global singleton instance
policy_engine = PolicyEngine()
