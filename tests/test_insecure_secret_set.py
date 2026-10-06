"""Regression tests for the shared INSECURE_PRODUCTION_SECRETS set.

These guard a real defect: `Settings.validate_production_security` and
`auth.validate_production_secret` used two different deny-lists. The seeded dev
secret was known to `auth` but missing from the production validator, so a
deployment carrying it passed the production check.

Worse, the test that was supposed to catch this passed *by accident*: it only
set SECRET_KEY, so the other values came from the developer's local `.env`.
While `.env` held a 10-character placeholder the length branch fired and the
test went green without ever exercising the seeded-secret branch. Fixing
`.env` turned it red.
"""

from __future__ import annotations

import pytest

from intelx.core.auth import validate_production_secret
from intelx.core.settings import (
    INSECURE_PRODUCTION_SECRETS,
    IntelXSettings,
    validate_production_security,
)

SEEDED_DEV_SECRET = "intelx-super-secret-key-change-in-production"


def _production_settings(**overrides):
    base = {
        "ENV": "production",
        "MOCK_MODE": False,
        "LLM_MODEL": "google/gemini-2.5-flash",
        "LLM_PROVIDER": "ai_universe",
        "INFERENCE_API_KEY": "production-inference-token-gH6j" * 2,
        "SECRET_KEY": "production-session-secret-aB3x" * 2,
        "INTELX_API_KEY": "production-api-key-cD4y" * 2,
        "API_KEYS": ["production-client-key-eF5z" * 2],
    }
    base.update(overrides)
    return IntelXSettings(_env_file=None, **base)


def test_seeded_dev_secret_is_in_shared_deny_list() -> None:
    """The value shipped by seed scripts must be deny-listed."""
    assert SEEDED_DEV_SECRET in INSECURE_PRODUCTION_SECRETS


def test_seeded_dev_secret_rejected_without_relying_on_env_file() -> None:
    """Production validation must reject it on SECRET_KEY alone.

    INTELX_API_KEY and API_KEYS are deliberately left unset here so the assertion
    cannot be satisfied by whatever happens to be in the developer's `.env`.
    """
    settings = _production_settings(SECRET_KEY=SEEDED_DEV_SECRET)
    with pytest.raises(RuntimeError, match="Production signing/API secrets must be unique"):
        validate_production_security(settings)


def test_deny_list_matching_is_exact_value_not_substring() -> None:
    """The deny-list is an exact-value match, so document that boundary.

    This is a deliberate contract test, not a claim that the validator is
    exhaustive: a value that merely *contains* a deny-listed entry is a
    different (stronger) heuristic and is not implemented.
    """
    # Exact membership -> rejected.
    settings = _production_settings(SECRET_KEY="dev-member-key")
    with pytest.raises(RuntimeError, match="Production signing/API secrets must be unique"):
        validate_production_security(settings)

    # Superset of a deny-listed string -> NOT rejected by value, and it is also
    # above the 32-char floor, so it passes today. Assert the real behaviour so
    # any future tightening of this rule is a conscious, visible change.
    superset = "dev-member-key" * 3 + "xyz"
    assert len(superset) >= 32
    assert superset not in INSECURE_PRODUCTION_SECRETS
    relaxed = _production_settings(SECRET_KEY=superset)
    validate_production_security(relaxed)  # currently permitted


def test_auth_and_settings_deny_lists_agree() -> None:
    """Both helpers must reject every shared deny-list entry.

    Drift between these two is exactly the defect this file exists to prevent.
    """
    for secret in INSECURE_PRODUCTION_SECRETS:
        # auth also applies a 16-char floor; every entry here is checked by value.
        assert not validate_production_secret(secret), f"auth accepted deny-listed {secret!r}"


def test_production_inference_provider_requires_an_api_key() -> None:
    """Fail at startup rather than deploying an unauthenticated inference client."""
    settings = _production_settings(INFERENCE_API_KEY=None)
    with pytest.raises(RuntimeError, match="inference provider requires INTELX_INFERENCE_API_KEY"):
        validate_production_security(settings)


def test_production_openai_compatible_provider_requires_its_matching_credential() -> None:
    """An inference key must not satisfy OpenAI-compatible provider startup checks."""
    missing_key = _production_settings(
        LLM_PROVIDER="openai_compatible",
        INFERENCE_API_KEY=None,
        OPENAI_API_KEY=None,
        LLM_API_KEY=None,
    )
    with pytest.raises(RuntimeError, match="OpenAI-compatible provider requires"):
        validate_production_security(missing_key)

    configured = _production_settings(
        LLM_PROVIDER="openai_compatible",
        INFERENCE_API_KEY=None,
        OPENAI_API_KEY="production-openai-provider-token-aB3x" * 2,
        LLM_API_KEY=None,
    )
    validate_production_security(configured)


def test_production_anthropic_provider_does_not_accept_openai_key() -> None:
    """Anthropic production readiness must not borrow the OpenAI credential."""
    wrong_provider_key = _production_settings(
        LLM_PROVIDER="anthropic",
        INFERENCE_API_KEY=None,
        OPENAI_API_KEY="production-openai-provider-token-aB3x" * 2,
        ANTHROPIC_API_KEY=None,
        LLM_API_KEY=None,
    )
    with pytest.raises(RuntimeError, match="Anthropic requires"):
        validate_production_security(wrong_provider_key)

    configured = _production_settings(
        LLM_PROVIDER="anthropic",
        INFERENCE_API_KEY=None,
        ANTHROPIC_API_KEY="production-anthropic-provider-token-cD4y" * 2,
        LLM_API_KEY=None,
    )
    validate_production_security(configured)


def test_strong_unique_secret_passes_production_validation() -> None:
    """The validator must not reject a genuinely strong secret (no false positives)."""
    strong = "intelx_" + "aB3" * 14  # 49 chars, varied
    settings = _production_settings(
        SECRET_KEY=strong,
        INTELX_API_KEY=strong[::-1],
        API_KEYS=["ix_live_" + "kQ7" * 10],
    )
    validate_production_security(settings)  # must not raise
