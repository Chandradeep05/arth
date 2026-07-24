"""
ARTH — AI Research & Trading Hub
Application configuration via pydantic-settings.

All configuration is loaded from environment variables with sensible defaults
for local development. In production, these are set via Railway/Render env vars.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import List

from pydantic import field_validator
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
    database_url: str = "postgresql+asyncpg://arth_user:arth_dev_password@localhost:5432/arth"
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

    # Groq (Primary — using Qwen reasoning model. <think> tags stripped in groq_client.py)
    groq_api_key: str = ""
    groq_model: str = "qwen/qwen3.6-27b"  # Reasoning model — emits <think> tags, stripped client-side
    groq_max_tokens: int = 4096

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
    jwt_secret_key: str = "change-this-to-a-random-secret-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    rate_limit_per_minute: int = 100

    # ── WebSocket ──
    ws_heartbeat_interval: int = 30
    ws_reconnect_max_retries: int = 5

    # ── Data Quality ──
    data_freshness_threshold_live: int = 60        # seconds
    data_freshness_threshold_fundamentals: int = 86400  # seconds
    price_anomaly_threshold_pct: float = 20.0

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
