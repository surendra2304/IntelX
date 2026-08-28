"""INTELX Application Settings and Configuration Management."""

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, field_validator
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

    # Mock & Provider Controls
    MOCK_MODE: bool = Field(
        default=True,
        description="When true, all LLM & search calls use local synthetic mock data",
    )
    LLM_PROVIDER: Literal["mock", "openai_compatible", "anthropic"] = Field(
        default="mock",
        description="Active LLM provider backend",
    )
    LLM_BASE_URL: str | None = Field(
        default=None,
        description="Custom base URL for OpenAI-compatible endpoints",
    )
    LLM_API_KEY: str | None = Field(
        default=None,
        description="API key for LLM provider",
    )
    LLM_MODEL: str = Field(
        default="mock-gpt-4o",
        description="Default LLM model name",
    )

    # Per-Role LLM Model Overrides
    LLM_MODEL_PLANNER: str | None = Field(
        default=None,
        description="Model override for Planner agent",
    )
    LLM_MODEL_EXTRACTOR: str | None = Field(
        default=None,
        description="Model override for Extractor agent",
    )
    LLM_MODEL_VERIFIER: str | None = Field(
        default=None,
        description="Model override for Verifier agent",
    )
    LLM_MODEL_ANALYST: str | None = Field(
        default=None,
        description="Model override for Analyst agent",
    )
    LLM_MODEL_SYNTHESIZER: str | None = Field(
        default=None,
        description="Model override for Synthesizer agent",
    )
    LLM_MODEL_CRITIC: str | None = Field(
        default=None,
        description="Model override for Critic agent",
    )

    # Search Provider
    TAVILY_API_KEY: str | None = Field(
        default=None,
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
    API_KEYS: list[str] = Field(
        default_factory=list,
        description="Comma-separated API keys allowed for client access",
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
        sensitive_keys = {"SECRET_KEY", "LLM_API_KEY", "TAVILY_API_KEY", "API_KEYS"}
        for k in sensitive_keys:
            if k in data and data[k]:
                data[k] = "[REDACTED]"
        return data


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Singleton getter for application settings."""
    return Settings()
