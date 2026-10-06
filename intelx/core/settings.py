"""INTELX Application Settings and Configuration Management."""

import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Credentials published in source, docs, .env.example, or seed scripts. They must
# never authenticate a production deployment: anyone who can read the repository
# already knows these values, so their length is irrelevant.
INSECURE_PRODUCTION_SECRETS = frozenset(
    {
        "change-me",
        "changeme",
        "secret",
        "password",
        "intelx_api",
        # Seed value shipped by intelx.core.auth and referenced in tests.
        "intelx-super-secret-key-change-in-production",
        "dev-admin-key",
        "dev-member-key",
        "intelx_dev_secret_key_admin",
    }
)


class Settings(BaseSettings):
    """Central configuration for INTELX platform."""

    model_config = SettingsConfigDict(
        env_prefix="INTELX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Core Environment & Database
    ENV: str = Field(
        default="development",
        validation_alias=AliasChoices("INTELX_ENV", "ENVIRONMENT", "ENV"),
        description="Runtime environment: development | staging | production",
    )
    DB_URL: str = Field(
        default="sqlite+aiosqlite:///./data/intelx.db",
        validation_alias=AliasChoices("INTELX_DB_URL", "DATABASE_URL", "DB_URL"),
        description="Async SQLAlchemy database URL (SQLite or PostgreSQL)",
    )
    TURSO_DATABASE_URL: str | None = Field(
        default="https://intelx-db-surendra2304.aws-ap-south-1.turso.io",
        validation_alias=AliasChoices("TURSO_DATABASE_URL", "INTELX_TURSO_DATABASE_URL"),
        description="Turso LibSQL cloud database URL",
    )
    TURSO_AUTH_TOKEN: str | None = Field(
        default=None,
        validation_alias=AliasChoices("TURSO_AUTH_TOKEN", "INTELX_TURSO_AUTH_TOKEN"),
        description="Turso LibSQL cloud database auth token",
    )
    SECRET_KEY: str | None = Field(
        default=None,
        description="Secret key used for crypto and session signing",
    )
    DATA_DIR: str = Field(
        default="./data",
        description="Local root directory for data, raw files, and artifacts",
    )

    # Mock & Provider Controls
    MOCK_MODE: bool = Field(
        default=True,
        validation_alias=AliasChoices("INTELX_MOCK_MODE", "MOCK_MODE"),
        description="When true, all LLM & search calls use local synthetic mock data",
    )
    LLM_PROVIDER: Literal[
        "mock",
        "openai_compatible",
        "openai",
        "groq",
        "vllm",
        "ollama",
        "openrouter",
        "anthropic",
        "inference",
        "ai_universe",
        "aiuniverse",
    ] = Field(
        default="inference",
        validation_alias=AliasChoices(
            "INTELX_LLM_PROVIDER", "LLM_PROVIDER", "INTELX_MODEL_PROVIDER", "MODEL_PROVIDER"
        ),
        description="Active LLM provider backend",
    )
    LLM_BASE_URL: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_LLM_BASE_URL", "OPENAI_BASE_URL", "LLM_BASE_URL"),
        description="Custom base URL for OpenAI-compatible endpoints",
    )
    LLM_API_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_LLM_API_KEY", "LLM_API_KEY"),
        description="Generic API key for an LLM provider when no provider-specific key is set",
    )
    OPENAI_API_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_OPENAI_API_KEY", "OPENAI_API_KEY"),
        description="OpenAI or OpenAI-compatible provider credential",
    )
    ANTHROPIC_API_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY"),
        description="Anthropic provider credential",
    )
    LLM_MODEL: str = Field(
        default="mock-gpt-4o",
        validation_alias=AliasChoices("INTELX_LLM_MODEL", "LLM_MODEL"),
        description="Default LLM model name",
    )
    ALLOW_MOCK_FALLBACK: bool = Field(
        default=False,
        validation_alias=AliasChoices("INTELX_ALLOW_MOCK_FALLBACK", "ALLOW_MOCK_FALLBACK"),
        description="Allow non-production provider failures to fall back to synthetic mock answers",
    )

    # Inference Multi-Agent Gateway Provider
    INFERENCE_URL: str = Field(
        default="https://inference-h7bn.onrender.com",
        validation_alias=AliasChoices(
            "INTELX_INFERENCE_URL",
            "INFERENCE_URL",
            "INTELX_AI_UNIVERSE_BASE_URL",
            "AI_UNIVERSE_BASE_URL",
            "AI_UNIVERSE_URL",
        ),
        description="Base URL for Inference multi-agent intelligence server",
    )
    INFERENCE_API_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "INTELX_INFERENCE_API_KEY",
            "INFERENCE_API_KEY",
            "INTELX_AI_UNIVERSE_API_KEY",
            "AI_UNIVERSE_API_KEY",
        ),
        description="API key for Inference service",
    )

    @property
    def AI_UNIVERSE_BASE_URL(self) -> str:
        return self.INFERENCE_URL

    @property
    def AI_UNIVERSE_API_KEY(self) -> str | None:
        return self.INFERENCE_API_KEY

    def get_llm_api_key(self, provider: str | None = None) -> str | None:
        """Resolve the credential for one provider without mixing unrelated provider keys."""
        normalized = (provider or self.LLM_PROVIDER or "").lower().strip()
        if normalized == "anthropic":
            return self.ANTHROPIC_API_KEY or self.LLM_API_KEY
        if normalized in {
            "openai",
            "openai_compatible",
            "groq",
            "vllm",
            "ollama",
            "openrouter",
        }:
            return self.OPENAI_API_KEY or self.LLM_API_KEY
        return self.LLM_API_KEY

    # Memora Cloud Memory Integration
    MEMORA_URL: str = Field(
        default="https://memora-cavc.onrender.com",
        validation_alias=AliasChoices("INTELX_MEMORA_URL", "MEMORA_URL", "MEMORA_BASE_URL"),
        description="Base URL for Memora persistent memory server",
    )
    MEMORA_API_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_MEMORA_API_KEY", "MEMORA_API_KEY"),
        description="API key for Memora service",
    )

    # Futuris Forecasting Integration
    FUTURIS_BASE_URL: str = Field(
        default="https://futuris-th6f.onrender.com",
        validation_alias=AliasChoices("INTELX_FUTURIS_BASE_URL", "FUTURIS_BASE_URL", "FUTURIS_URL"),
        description="Base URL for Futuris predictive forecasting engine",
    )
    FUTURIS_API_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_FUTURIS_API_KEY", "FUTURIS_API_KEY"),
        description="API key for Futuris integration",
    )
    FUTURIS_WEBHOOK_URL: str | None = Field(
        default="https://futuris-th6f.onrender.com/api/v1/webhooks/research-finding-relevant",
        validation_alias=AliasChoices("INTELX_FUTURIS_WEBHOOK_URL", "FUTURIS_WEBHOOK_URL"),
        description="Webhook URL on Futuris for research-triggered notifications",
    )

    # StrateX Algorithmic Trading Integration
    STRATEX_BASE_URL: str = Field(
        default="https://stratex-8wj1.onrender.com",
        validation_alias=AliasChoices("INTELX_STRATEX_BASE_URL", "STRATEX_BASE_URL", "STRATEX_URL"),
        description="Base URL for StrateX trading engine",
    )
    STRATEX_API_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_STRATEX_API_KEY", "STRATEX_API_KEY"),
        description="API key for StrateX integration",
    )
    STRATEX_WEBHOOK_URL: str | None = Field(
        default="https://stratex-8wj1.onrender.com/api/v1/webhooks/intelx-signal",
        validation_alias=AliasChoices("INTELX_STRATEX_WEBHOOK_URL", "STRATEX_WEBHOOK_URL"),
        description="Webhook URL on StrateX for automated trade execution triggers",
    )

    # Per-Role LLM Model Overrides
    LLM_MODEL_PLANNER: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_LLM_MODEL_PLANNER", "LLM_MODEL_PLANNER"),
        description="Model override for Planner agent",
    )
    LLM_MODEL_EXTRACTOR: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_LLM_MODEL_EXTRACTOR", "LLM_MODEL_EXTRACTOR"),
        description="Model override for Extractor agent",
    )
    LLM_MODEL_VERIFIER: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_LLM_MODEL_VERIFIER", "LLM_MODEL_VERIFIER"),
        description="Model override for Verifier agent",
    )
    LLM_MODEL_ANALYST: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_LLM_MODEL_ANALYST", "LLM_MODEL_ANALYST"),
        description="Model override for Analyst agent",
    )
    LLM_MODEL_SYNTHESIZER: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_LLM_MODEL_SYNTHESIZER", "LLM_MODEL_SYNTHESIZER"),
        description="Model override for Synthesizer agent",
    )
    LLM_MODEL_CRITIC: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_LLM_MODEL_CRITIC", "LLM_MODEL_CRITIC"),
        description="Model override for Critic agent",
    )

    # Search Provider
    TAVILY_API_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_TAVILY_API_KEY", "TAVILY_API_KEY", "SEARCH_API_KEY"),
        description="Tavily Search API key (optional)",
    )

    # Research Execution Budgets
    MAX_RUN_USD: float = Field(
        default=2.0,
        description="Max USD budget per research run",
    )
    MAX_RUN_MINUTES: int = Field(
        default=15,
        description="Max execution timeout in minutes per run",
    )
    MAX_TOOL_CALLS: int = Field(
        default=60,
        description="Max allowed tool calls per run",
    )
    MAX_SOURCES_PER_RUN: int = Field(
        default=25,
        description="Max external sources collected per run",
    )

    # Crawl & Scraping Policy
    RESPECT_ROBOTS: bool = Field(
        default=True,
        description="Enforce robots.txt rules during web fetching",
    )
    USER_AGENT: str = Field(
        default="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (compatible; IntelXResearch/2.0; +https://github.com/surendra2304/IntelX)",
        description="HTTP User-Agent identifier sent with crawler requests",
    )
    DOMAIN_ALLOWLIST: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="Permitted domain patterns (empty allows all non-denied domains)",
    )
    DOMAIN_DENYLIST: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="Forbidden domain patterns",
    )
    FETCH_TIMEOUT_S: float = Field(
        default=20.0,
        description="HTTP request timeout in seconds",
    )
    MAX_PAGE_BYTES: int = Field(
        default=2_000_000,
        description="Maximum allowed page download size in bytes",
    )
    PER_DOMAIN_DELAY_S: float = Field(
        default=1.0,
        description="Politeness delay between requests to same domain",
    )
    MAX_CONCURRENT_FETCHES: int = Field(
        default=4,
        description="Max concurrent asynchronous page fetches",
    )
    ENABLE_DEMO_SEEDER: bool = Field(
        default=False,
        description="Seed fake demonstration runs on startup (disabled by default to ensure only genuine research)",
    )
    RUN_EMBEDDED_WORKER: bool | None = Field(
        default=None,
        description="Run the worker inside the API process; defaults on outside production only",
    )
    ENABLE_NEWS_INGESTER: bool = Field(
        default=False,
        description="Enable outbound RSS ingestion loop in this process",
    )
    ENABLE_AUTONOMOUS_RESEARCH: bool = Field(
        default=False,
        description="Enable autonomous research generation loop in this process",
    )

    # Auth & Storage
    SESSION_TTL_SECONDS: int = Field(
        default=28_800,
        description="Maximum lifetime of a signed web session in seconds",
    )
    INTELX_API_KEY: str = Field(
        default="",
        validation_alias=AliasChoices("INTELX_API_KEY", "API_KEY"),
        description="Master API authentication key for IntelX service",
    )
    API_KEYS: Annotated[list[str], NoDecode] = Field(
        default_factory=list,
        description="Comma-separated API keys allowed for client access",
    )
    FRIDAY_API_KEY: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_FRIDAY_API_KEY", "FRIDAY_API_KEY"),
        description="Delegation API key for FRIDAY autonomous system integration",
    )
    # Concurrency & Production Infrastructure
    MAX_CONCURRENT_RUNS: int = Field(
        default=5,
        validation_alias=AliasChoices("INTELX_MAX_CONCURRENT_RUNS", "MAX_CONCURRENT_RUNS"),
        description="Maximum concurrent active research investigations in flight",
    )
    REDIS_URL: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_REDIS_URL", "REDIS_URL"),
        description="Redis connection URL for queue orchestration and pub/sub events",
    )
    RETENTION_DAYS_RAW_DOCS: int = Field(
        default=30,
        validation_alias=AliasChoices("INTELX_RETENTION_DAYS_RAW_DOCS", "RETENTION_DAYS_RAW_DOCS"),
        description="Retention period in days for raw ingested document bodies",
    )
    RETENTION_DAYS_REPORTS: int = Field(
        default=365,
        validation_alias=AliasChoices("INTELX_RETENTION_DAYS_REPORTS", "RETENTION_DAYS_REPORTS"),
        description="Retention period in days for completed intelligence reports and findings",
    )
    RAW_RETENTION_DAYS: int = Field(
        default=90,
        description="Retention window for raw scraped data in days",
    )

    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.ENV.strip().lower() in ("production", "prod")

    def is_dev_or_test(self) -> bool:
        """Check if running in development or testing mode."""
        return self.ENV.strip().lower() in ("development", "dev", "test", "testing")

    def validate_production_security(self) -> None:
        """Enforce strict production security rules: no weak secrets, no demo keys, no mock mode."""
        if not self.is_production():
            return
        if self.MOCK_MODE:
            raise RuntimeError(
                "CRITICAL SECURITY VIOLATION: MOCK_MODE cannot be enabled in production. "
                "Disable INTELX_MOCK_MODE immediately."
            )
        if (self.LLM_MODEL and self.LLM_MODEL.startswith("mock-")) or self.LLM_PROVIDER == "mock":
            raise RuntimeError(
                "CRITICAL SECURITY VIOLATION: Mock LLM models cannot be used in production. "
                "Configure a valid production LLM provider and model."
            )
        if self.ALLOW_MOCK_FALLBACK:
            raise RuntimeError(
                "CRITICAL SECURITY VIOLATION: Synthetic mock fallback is never allowed in production."
            )
        if any(
            k in {"dev-admin-key", "dev-member-key", "intelx_dev_secret_key_admin"}
            for k in (self.API_KEYS or [])
        ):
            raise RuntimeError(
                "CRITICAL SECURITY VIOLATION: Insecure development API keys configured in production."
            )
        secret_values = [self.SECRET_KEY or "", self.INTELX_API_KEY or "", *(self.API_KEYS or [])]
        if len(set(secret_values)) != len(secret_values) or any(
            len(value) < 32
            or value.strip().lower() in INSECURE_PRODUCTION_SECRETS
            or len(set(value)) < 2
            for value in secret_values
        ):
            raise RuntimeError(
                "CRITICAL SECURITY VIOLATION: Production signing/API secrets must be unique, distinct values of at least 32 characters. "
                "Configure INTELX_SECRET_KEY and INTELX_API_KEY, plus any API_KEYS, in the deployment environment."
            )
        if self.LLM_PROVIDER == "anthropic" and not self.get_llm_api_key("anthropic"):
            raise RuntimeError(
                "CRITICAL SECURITY VIOLATION: Anthropic requires INTELX_ANTHROPIC_API_KEY "
                "or INTELX_LLM_API_KEY in production."
            )
        if self.LLM_PROVIDER in {
            "openai_compatible",
            "openai",
            "groq",
            "vllm",
            "ollama",
            "openrouter",
        } and not self.get_llm_api_key("openai_compatible"):
            raise RuntimeError(
                "CRITICAL SECURITY VIOLATION: an OpenAI-compatible provider requires "
                "INTELX_OPENAI_API_KEY or INTELX_LLM_API_KEY in production."
            )
        if (
            self.LLM_PROVIDER in ("inference", "ai_universe", "aiuniverse")
            and not self.INFERENCE_API_KEY
        ):
            raise RuntimeError(
                "CRITICAL SECURITY VIOLATION: the inference provider requires "
                "INTELX_INFERENCE_API_KEY in production."
            )

    @field_validator("DB_URL", mode="before")
    @classmethod
    def normalize_async_database_url(cls, value: Any) -> str:
        """Normalize provider PostgreSQL URLs to SQLAlchemy's asyncpg driver."""
        if not isinstance(value, str):
            raise ValueError("DB_URL must be a string")
        normalized = value.strip()
        if normalized.startswith("postgres://"):
            return "postgresql+asyncpg://" + normalized[len("postgres://") :]
        if normalized.startswith("postgresql://"):
            return "postgresql+asyncpg://" + normalized[len("postgresql://") :]
        return normalized

    @field_validator("DOMAIN_ALLOWLIST", "DOMAIN_DENYLIST", "API_KEYS", mode="before")
    @classmethod
    def parse_comma_separated_list(cls, value: Any) -> list[str]:
        """Parse comma-separated strings or JSON arrays without env-source pre-decoding."""
        if isinstance(value, str):
            cleaned = value.strip()
            if not cleaned:
                return []
            if cleaned.startswith(("[", "{")):
                try:
                    decoded = json.loads(cleaned)
                except json.JSONDecodeError as exc:
                    raise ValueError("expected a comma-separated string or JSON array") from exc
                if not isinstance(decoded, list):
                    raise ValueError("expected a comma-separated string or JSON array")
                value = decoded
            else:
                value = cleaned.split(",")
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    def get_model_for_role(self, role: str) -> str:
        """Resolve the appropriate LLM model for a given agent role, falling back to LLM_MODEL."""
        normalized_role = role.strip().upper()
        role_map = {
            "PLANNER": self.LLM_MODEL_PLANNER,
            "EXTRACTOR": self.LLM_MODEL_EXTRACTOR,
            "VERIFIER": self.LLM_MODEL_VERIFIER,
            "ANALYST": self.LLM_MODEL_ANALYST,
            "SYNTHESIZER": self.LLM_MODEL_SYNTHESIZER,
            "CRITIC": self.LLM_MODEL_CRITIC,
        }
        return role_map.get(normalized_role) or self.LLM_MODEL

    def get_redacted_dict(self) -> dict[str, Any]:
        """Return a dictionary of settings with sensitive credentials redacted."""
        data = self.model_dump()
        sensitive_keys = {
            "SECRET_KEY",
            "API_KEYS",
            "DB_URL",
            "REDIS_URL",
            "TURSO_AUTH_TOKEN",
        }
        sensitive_keys.update(key for key in data if key.endswith("_API_KEY"))
        sensitive_keys.add("AI_UNIVERSE_API_KEY")
        for k in sensitive_keys:
            if k in data and data[k]:
                data[k] = "[REDACTED]"
        return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton getter for application settings."""
    return Settings()


IntelXSettings = Settings


def validate_production_security(settings: Settings | None = None) -> None:
    """Validate that the given or current settings conform to strict production security standards."""
    s = settings or get_settings()
    s.validate_production_security()
