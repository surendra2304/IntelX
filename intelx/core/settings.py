"""INTELX Application Settings and Configuration Management."""

from functools import lru_cache
from typing import Any, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
        description="Runtime environment: development | staging | production",
    )
    DB_URL: str = Field(
        default="sqlite+aiosqlite:///./data/intelx.db",
        description="Async SQLAlchemy database URL (SQLite or PostgreSQL)",
    )
    SECRET_KEY: str = Field(
        default="intelx-super-secret-key-change-in-production",
        description="Secret key used for crypto and session signing",
    )
    DATA_DIR: str = Field(
        default="./data",
        description="Local root directory for data, raw files, and artifacts",
    )

    # Mock & Provider Controls
    MOCK_MODE: bool = Field(
        default=False,
        validation_alias=AliasChoices("INTELX_MOCK_MODE", "MOCK_MODE"),
        description="When true, all LLM & search calls use local synthetic mock data",
    )
    LLM_PROVIDER: Literal["mock", "openai_compatible", "anthropic", "inference", "ai_universe"] = Field(
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
        validation_alias=AliasChoices(
            "INTELX_LLM_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "LLM_API_KEY"
        ),
        description="API key for LLM provider",
    )
    LLM_MODEL: str = Field(
        default="mock-gpt-4o",
        validation_alias=AliasChoices("INTELX_LLM_MODEL", "LLM_MODEL"),
        description="Default LLM model name",
    )

    # Inference Multi-Agent Gateway Provider
    INFERENCE_URL: str = Field(
        default="https://inference-3i2b.onrender.com",
        validation_alias=AliasChoices("INTELX_INFERENCE_URL", "INFERENCE_URL", "INTELX_AI_UNIVERSE_BASE_URL", "AI_UNIVERSE_BASE_URL", "AI_UNIVERSE_URL"),
        description="Base URL for Inference multi-agent intelligence server",
    )
    INFERENCE_API_KEY: str | None = Field(
        default="inference_api",
        validation_alias=AliasChoices("INTELX_INFERENCE_API_KEY", "INFERENCE_API_KEY", "INTELX_AI_UNIVERSE_API_KEY", "AI_UNIVERSE_API_KEY"),
        description="API key for Inference service",
    )

    @property
    def AI_UNIVERSE_BASE_URL(self) -> str:
        return self.INFERENCE_URL

    @property
    def AI_UNIVERSE_API_KEY(self) -> str | None:
        return self.INFERENCE_API_KEY

    # Memora Cloud Memory Integration
    MEMORA_URL: str = Field(
        default="https://memora-9zr9.onrender.com",
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
        default="https://futuris-x4f4.onrender.com",
        validation_alias=AliasChoices("INTELX_FUTURIS_BASE_URL", "FUTURIS_BASE_URL", "FUTURIS_URL"),
        description="Base URL for Futuris predictive forecasting engine",
    )
    FUTURIS_API_KEY: str | None = Field(
        default="futuris_api",
        validation_alias=AliasChoices("INTELX_FUTURIS_API_KEY", "FUTURIS_API_KEY"),
        description="API key for Futuris integration",
    )
    FUTURIS_WEBHOOK_URL: str | None = Field(
        default=None,
        validation_alias=AliasChoices("INTELX_FUTURIS_WEBHOOK_URL", "FUTURIS_WEBHOOK_URL"),
        description="Webhook URL on Futuris for research-triggered notifications",
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
        default="INTELX/0.1 research-bot (+contact)",
        description="HTTP User-Agent identifier sent with crawler requests",
    )
    DOMAIN_ALLOWLIST: list[str] = Field(
        default_factory=list,
        description="Permitted domain patterns (empty allows all non-denied domains)",
    )
    DOMAIN_DENYLIST: list[str] = Field(
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

    # Auth & Storage
    INTELX_API_KEY: str = Field(
        default="intelx_api",
        validation_alias=AliasChoices("INTELX_API_KEY", "API_KEY"),
        description="Master API authentication key for IntelX service",
    )
    API_KEYS: list[str] = Field(
        default_factory=lambda: ["intelx_api"],
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

    @field_validator("DOMAIN_ALLOWLIST", "DOMAIN_DENYLIST", "API_KEYS", mode="before")
    @classmethod
    def parse_comma_separated_list(cls, value: Any) -> list[str]:
        """Convert comma-delimited strings to cleanly stripped string lists."""
        if isinstance(value, str):
            if not value.strip():
                return []
            return [item.strip() for item in value.split(",") if item.strip()]
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
            "LLM_API_KEY",
            "TAVILY_API_KEY",
            "API_KEYS",
            "FRIDAY_API_KEY",
            "AI_UNIVERSE_API_KEY",
        }
        for k in sensitive_keys:
            if k in data and data[k]:
                data[k] = "[REDACTED]"
        return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton getter for application settings."""
    return Settings()
