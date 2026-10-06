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


def test_mock_mode_defaults_to_offline_without_environment_overrides(monkeypatch):
    """A fresh developer install remains deterministic and makes no provider calls."""
    monkeypatch.delenv("INTELX_MOCK_MODE", raising=False)
    monkeypatch.delenv("MOCK_MODE", raising=False)
    assert Settings(_env_file=None).MOCK_MODE is True


def test_deployment_environment_and_postgres_url_aliases(monkeypatch):
    """Render environment markers and provider PostgreSQL URLs are interpreted correctly."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("INTELX_ENV", raising=False)
    assert Settings(_env_file=None).ENV == "production"

    settings = Settings(
        _env_file=None,
        INTELX_DB_URL="postgres://intelx:secret@db.example:5432/intelx",
    )
    assert settings.DB_URL == "postgresql+asyncpg://intelx:secret@db.example:5432/intelx"


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


def test_list_environment_values_parse_empty_csv_and_json(monkeypatch):
    """Empty Compose values, CSV lists, and JSON arrays all load through BaseSettings."""
    monkeypatch.setenv("INTELX_API_KEYS", "")
    assert Settings(_env_file=None).API_KEYS == []

    monkeypatch.setenv("INTELX_API_KEYS", "key-1, key-2")
    assert Settings(_env_file=None).API_KEYS == ["key-1", "key-2"]

    monkeypatch.setenv("INTELX_API_KEYS", '["key-1", "key-2"]')
    monkeypatch.setenv("INTELX_DOMAIN_ALLOWLIST", '["example.com", "news.example"]')
    assert Settings(_env_file=None).API_KEYS == ["key-1", "key-2"]
    assert Settings(_env_file=None).DOMAIN_ALLOWLIST == ["example.com", "news.example"]


def test_provider_specific_key_environment_aliases(monkeypatch):
    """OpenAI and Anthropic environment keys remain distinct in BaseSettings."""
    for name in (
        "INTELX_LLM_API_KEY",
        "LLM_API_KEY",
        "INTELX_OPENAI_API_KEY",
        "INTELX_ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "local-openai-env-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "local-anthropic-env-key")

    settings = Settings(_env_file=None)
    assert settings.OPENAI_API_KEY == "local-openai-env-key"
    assert settings.ANTHROPIC_API_KEY == "local-anthropic-env-key"
    assert settings.get_llm_api_key("openai_compatible") == "local-openai-env-key"
    assert settings.get_llm_api_key("anthropic") == "local-anthropic-env-key"


def test_redacted_dict_hides_secrets():
    """Verify secret keys and tokens are redacted when exporting settings."""
    settings = Settings(
        SECRET_KEY="super-secret-key-123",
        INTELX_API_KEY="local-service-key",
        LLM_API_KEY="local-generic-llm-key",
        OPENAI_API_KEY="local-openai-key",
        ANTHROPIC_API_KEY="local-anthropic-key",
        INFERENCE_API_KEY="local-inference-key",
        MEMORA_API_KEY="local-memora-key",
        FUTURIS_API_KEY="local-futuris-key",
        STRATEX_API_KEY="local-stratex-key",
        TAVILY_API_KEY="tvly-fake-search-key",
        API_KEYS="client-key-1,client-key-2",
        DB_URL="postgresql+asyncpg://intelx:local-db-test-pass@database/intelx",
        REDIS_URL="redis://:local-redis-test-pass@redis:6379/0",
        TURSO_AUTH_TOKEN="local-turso-test-token",
    )
    redacted = settings.get_redacted_dict()
    for key in (
        "SECRET_KEY",
        "INTELX_API_KEY",
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "INFERENCE_API_KEY",
        "MEMORA_API_KEY",
        "FUTURIS_API_KEY",
        "STRATEX_API_KEY",
        "TAVILY_API_KEY",
        "API_KEYS",
        "DB_URL",
        "REDIS_URL",
        "TURSO_AUTH_TOKEN",
    ):
        assert redacted[key] == "[REDACTED]"
    assert redacted["LLM_MODEL"] == "mock-gpt-4o"
