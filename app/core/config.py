"""Application settings, loaded from environment / .env via pydantic-settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["development", "staging", "production"]


class Settings(BaseSettings):
    """Typed application configuration.

    All values are read from environment variables (see ``.env.example``).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ── App ────────────────────────────────────────────────
    ENVIRONMENT: Environment = "development"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "http://localhost:3000"
    ENABLE_DOCS: bool = True
    SECRET_KEY: str = "change-me"

    # ── Feature flags ──────────────────────────────────────
    FEATURE_PHASE2: bool = False
    FEATURE_PHASE3: bool = False

    # ── Database ───────────────────────────────────────────
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "aih"
    POSTGRES_PASSWORD: str = "aih_password"
    POSTGRES_DB: str = "aih"
    POSTGRES_DIRECT_HOST: str | None = None
    POSTGRES_DIRECT_PORT: int | None = None
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_ECHO: bool = False

    # ── Redis ──────────────────────────────────────────────
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None

    # ── Encryption ─────────────────────────────────────────
    FIELD_ENCRYPTION_KEY: str = ""

    # ── Clerk ──────────────────────────────────────────────
    CLERK_JWKS_URL: str = ""
    CLERK_ISSUER: str = ""
    CLERK_AUDIENCE: str | None = None
    CLERK_SECRET_KEY: str = ""
    CLERK_WEBHOOK_SECRET: str = ""
    JWKS_CACHE_TTL_SECONDS: int = 600

    # ── OpenAI ─────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_CHAT_MODEL: str = "gpt-4o"
    OPENAI_CHAT_MODEL_CHEAP: str = "gpt-4o-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536

    # ── Langfuse ───────────────────────────────────────────
    LANGFUSE_PUBLIC_KEY: str = ""
    LANGFUSE_SECRET_KEY: str = ""
    LANGFUSE_HOST: str = ""

    # ── Cloudflare R2 ──────────────────────────────────────
    R2_ACCOUNT_ID: str = ""
    R2_ACCESS_KEY_ID: str = ""
    R2_SECRET_ACCESS_KEY: str = ""
    R2_BUCKET: str = "aih-documents"
    R2_ENDPOINT: str = ""
    R2_PRESIGN_EXPIRY_SECONDS: int = 900

    # ── Resend ─────────────────────────────────────────────
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = "no-reply@example.com"
    EMAIL_ADMIN_INBOX: str = "admin@example.com"

    # ── Sentry ─────────────────────────────────────────────
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1

    # ── News API (Phase 2) ─────────────────────────────────
    NEWS_API_KEY: str = ""

    # ── Rate limiting (requests / minute) ──────────────────
    RATE_LIMIT_PUBLIC: int = 30
    RATE_LIMIT_AUTH: int = 10
    RATE_LIMIT_AI: int = 20

    # ── AI tuning ──────────────────────────────────────────
    AI_RESPONSE_CACHE_TTL_SECONDS: int = 21600  # 6 hours
    AI_MAX_HISTORY_TURNS: int = 8
    RAG_ESCALATION_THRESHOLD: float = 0.72

    # ── Derived values ─────────────────────────────────────
    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    def _build_dsn(self, host: str, port: int, *, driver: str) -> str:
        return str(
            PostgresDsn.build(
                scheme=driver,
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=host,
                port=port,
                path=self.POSTGRES_DB,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async DSN used by the app (routes through PgBouncer in prod)."""
        return self._build_dsn(
            self.POSTGRES_HOST, self.POSTGRES_PORT, driver="postgresql+asyncpg"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def migration_database_url(self) -> str:
        """Sync DSN for Alembic; bypasses PgBouncer (DDL needs a direct conn)."""
        host = self.POSTGRES_DIRECT_HOST or self.POSTGRES_HOST
        port = self.POSTGRES_DIRECT_PORT or self.POSTGRES_PORT
        return self._build_dsn(host, port, driver="postgresql+asyncpg")

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        return f"redis://{auth}{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton."""
    return Settings()


settings = get_settings()
