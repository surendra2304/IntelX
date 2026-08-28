"""Tests for Settings, role overrides, list parsing, and redactions."""

from intelx.core.settings import Settings


def test_default_settings():
    """Verify default configurations and mock mode state."""
    settings = Settings()
    assert settings.ENV == "testing" or settings.ENV == "development"
    assert settings.MOCK_MODE is True
    assert settings.MAX_RUN_USD == 2.0
    assert settings.MAX_RUN_MINUTES == 15
    assert settings.MAX_TOOL_CALLS == 60
    assert settings.MAX_SOURCES_PER_RUN == 25
    assert settings.RESPECT_ROBOTS is True
    assert settings.FETCH_TIMEOUT_S == 20.0
    assert settings.RAW_RETENTION_DAYS == 90


def test_role_model_fallback():
    """Verify role model resolution falls back to LLM_MODEL when specific role model is None."""
    settings = Settings(
        LLM_MODEL="default-test-model",
        LLM_MODEL_PLANNER="custom-planner-model",
        LLM_MODEL_SYNTHESIZER=None,
    )
    assert settings.get_model_for_role("planner") == "custom-planner-model"
    assert settings.get_model_for_role("PLANNER") == "custom-planner-model"
    assert settings.get_model_for_role("synthesizer") == "default-test-model"
    assert settings.get_model_for_role("unknown_role") == "default-test-model"


def test_comma_separated_list_parsing():
    """Verify comma-separated env values parse into clean string lists."""
    settings = Settings(
        DOMAIN_ALLOWLIST="example.com, docs.python.org , wikipedia.org",
        DOMAIN_DENYLIST="malicious.com, spam.org",
        API_KEYS="key-1, key-2 ,key-3",
    )
    assert settings.DOMAIN_ALLOWLIST == ["example.com", "docs.python.org", "wikipedia.org"]
    assert settings.DOMAIN_DENYLIST == ["malicious.com", "spam.org"]
    assert settings.API_KEYS == ["key-1", "key-2", "key-3"]


def test_redacted_dict_hides_secrets():
    """Verify secret keys and tokens are redacted when exporting settings."""
    settings = Settings(
        SECRET_KEY="super-secret-key-123",
        LLM_API_KEY="sk-fake-llm-key",
        TAVILY_API_KEY="tvly-fake-search-key",
        API_KEYS="client-key-1,client-key-2",
    )
    redacted = settings.get_redacted_dict()
    assert redacted["SECRET_KEY"] == "[REDACTED]"
    assert redacted["LLM_API_KEY"] == "[REDACTED]"
    assert redacted["TAVILY_API_KEY"] == "[REDACTED]"
    assert redacted["API_KEYS"] == "[REDACTED]"
    assert redacted["LLM_MODEL"] == "mock-gpt-4o"
