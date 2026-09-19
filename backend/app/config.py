"""
ARTH — AI Financial Intelligence Platform
Application configuration via pydantic-settings.

All configuration is loaded from environment variables with sensible defaults
for local development. In production, these are set via Render env vars.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LLMTier(str, Enum):
    LOCAL = "local"       # Ollama only
    CLOUD = "cloud"       # Groq primary
    HYBRID = "hybrid"     # Ollama for quick, Groq for complex
    PREMIUM = "premium"   # Claude/GPT-4 for deep research


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──
    app_name: str = "ARTH"
    app_env: Environment = Environment.DEVELOPMENT
    debug: bool = True
    log_level: str = "INFO"

    # ── FastAPI ──
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = "/api/v1"
    allowed_origins: str = "http://localhost:3000,https://arth.vercel.app,https://arth-five.vercel.app,https://arth-chandradeep05s-projects.vercel.app,https://arth-git-main-chandradeep05s-projects.vercel.app"

    @property
    def cors_origins(self) -> List[str]:
        """Parse comma-separated origins into a list."""
        return [origin.strip() for origin in self.allowed_origins.split(",")]

    # ── Database (TimescaleDB) ──
    # Default uses localhost with no credentials — production URL set via DATABASE_URL env var
    database_url: str = "postgresql+asyncpg://localhost:5432/arth"
    database_pool_size: int = 10
    database_max_overflow: int = 20

    @property
    def database_url_sync(self) -> str:
        """Synchronous URL for Alembic migrations."""
        return self.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")

    # ── Redis ──
    redis_url: str = "redis://localhost:6379/0"
    redis_cache_ttl_tick: int = 300         # 5 min (was 15s — too short for blocked IPs)
    redis_cache_ttl_indicators: int = 600   # 10 min (was 60s)
    redis_cache_ttl_fundamentals: int = 86400  # 24 hours

    # ── Upstash Redis (Phase 3 — persistent cache across Render cold starts) ──
    upstash_redis_url: str = ""     # Set via UPSTASH_REDIS_URL env var
    upstash_redis_token: str = ""   # Set via UPSTASH_REDIS_TOKEN env var

    # ── Yahoo Finance Proxy ──
    # Set YAHOO_PROXY_URL env var on Render to route through a clean IP.
    # Format: http://user:pass@host:port  (e.g. Webshare, SmartProxy, etc.)
    # Without this, Render's shared IP gets 429'd by Yahoo immediately.
    yahoo_proxy_url: str = ""

    # ── Twelve Data API (US stocks) ──
    # Free tier: 8 credits/min, 800/day. Used for US stocks only.
    # Indian stocks (NSE/BSE) still use yfinance (free tier doesn't cover India).
    twelvedata_api_key: str = ""

    # ── LLM Configuration ──
    llm_tier: LLMTier = LLMTier.CLOUD

    # Groq (Primary — Production-tier models only. No Preview-tier models in any chain.)
    groq_api_key: str = ""
    groq_model_research: str = "openai/gpt-oss-120b"   # Production-tier, large context for deep reports
    groq_model_chat: str = "openai/gpt-oss-20b"         # Production-tier, faster/cheaper for chat
    groq_model: str = ""  # DEPRECATED — use groq_model_research or groq_model_chat
    groq_max_tokens: int = 1000  # Default to 1000 to respect Groq free tier output-tokens-per-minute (OTPM) ceiling
    groq_fallback_models: str = "openai/gpt-oss-20b,openai/gpt-oss-120b"  # Cross-fallback chain

    # Ollama (Local dev fallback)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:3b"

    # Claude API (Phase 2+)
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-20250514"

    # OpenAI (Phase 2+ embeddings)
    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"

    # ── Data Sources ──
    yahoo_finance_enabled: bool = False     # Deprecated — migrated to MarketDataProvider (TwelveData, Finnhub, FMP, NSE)
    alpha_vantage_api_key: str = ""         # Phase 2+ placeholder
    alpha_vantage_daily_budget: int = 20    # Phase 2+ placeholder
    alpha_vantage_enabled: bool = False     # Phase 2+ — not active
    newsapi_key: str = ""                   # Reserved for future news provider integration
    newsapi_enabled: bool = False           # No adapter yet — set True when a ToS-compliant provider is added

    # Finnhub API (US news, company profiles, metrics)
    finnhub_api_key: str = ""
    finnhub_enabled: bool = True

    # Financial Modeling Prep API (Financial statements, ratios)
    fmp_api_key: str = ""
    fmp_enabled: bool = True

    # ── Security ──
    # JWT secret: empty default forces explicit configuration before use.
    # The application does not currently enforce JWT auth (personal-use, Phase 3+),
    # but if JWT is ever enabled, this must be set to a strong random value.
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    rate_limit_per_minute: int = 100

    # Admin API key for gating /system/debug and /system/metrics endpoints
    # Set via ADMIN_API_KEY env var in Render dashboard
    admin_api_key: str = ""

    # ── Supabase (Phase 4 — Auth + Postgres) ──
    # All three are required for Phase 4 auth to function.
    # SUPABASE_URL: your project URL, e.g. https://abc123.supabase.co
    # SUPABASE_ANON_KEY: safe to expose to browser (used for auth callbacks)
    # SUPABASE_SERVICE_KEY: backend-only, never in frontend, bypasses RLS on purpose
    # SUPABASE_JWT_SECRET: from Supabase Settings → API → JWT Settings (used for HS256)
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_key: str = ""
    supabase_jwt_secret: str = ""

    # Initial admin bootstrap — set INITIAL_ADMIN_EMAIL to your Google account email.
    # On startup, if this email matches a profile, it is promoted to role='admin'.
    # Idempotent — safe to leave set after first run.
    initial_admin_email: str = ""

    # ── Upstox (Phase 4 — Indian Market Data) ──
    upstox_api_key: str = ""
    upstox_api_secret: str = ""
    upstox_access_token: str = ""   # Analytics Token (read-only, long-lived)
    upstox_enabled: bool = False    # Set True via UPSTOX_ENABLED=true once token is configured

    # ── Internal Job Secret ──
    # Used to authenticate GitHub Actions → /internal/jobs/* calls.
    # Separate from ADMIN_API_KEY — machine-to-machine only, never browser-facing.
    internal_job_secret: str = ""

    # ── Per-User Quotas (configurable via env vars) ──
    quota_chat_per_hour: int = 30
    quota_research_per_day: int = 10
    quota_prediction_per_day: int = 20

    # ── Data Quality ──
    data_freshness_threshold_live: int = 60        # seconds
    data_freshness_threshold_fundamentals: int = 86400  # seconds
    price_anomaly_threshold_pct: float = 20.0

    @model_validator(mode="after")
    def _migrate_groq_model(self):
        """Backward compat: if only GROQ_MODEL is set (non-Preview), use it for both."""
        if self.groq_model and not self.groq_model.startswith("qwen"):
            if self.groq_model_research == "openai/gpt-oss-120b":  # still default
                self.groq_model_research = self.groq_model
            if self.groq_model_chat == "openai/gpt-oss-20b":  # still default
                self.groq_model_chat = self.groq_model
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.app_env == Environment.DEVELOPMENT


@lru_cache()
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()
