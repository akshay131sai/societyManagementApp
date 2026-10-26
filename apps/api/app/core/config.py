"""Application configuration.

All configuration comes from the environment. Nothing is hard-coded, and the
settings object refuses to construct in an unsafe combination rather than
booting insecurely.
"""

from __future__ import annotations

import re
from enum import StrEnum
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

DB_NAME_PATTERN = re.compile(r"^nestflow_society_[0-9]{4,10}$")
"""Tenant database names are generated, never accepted from input.

``CREATE DATABASE`` cannot be parameterised in PostgreSQL, so every name that
reaches DDL is validated against this pattern first. See
docs/architecture/tenant-isolation.md section 3.
"""


_DEV_JWT_SECRET = "nestflow-development-only-signing-key-do-not-deploy"


class Environment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class AuthProvider(StrEnum):
    FIREBASE = "firebase"
    PASSWORD = "password"
    """Email and password checked by NestFlow against ``platform_users.password_hash``."""
    DEV = "dev"
    """Local-only verifier. Refused in production by ``_validate_safety``."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---------------------------------------------------------
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    DEBUG: bool = False
    APP_NAME: str = "NestFlow API"
    APP_VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # --- Central database ----------------------------------------------------
    CENTRAL_DATABASE_URL: PostgresDsn

    # --- Tenant databases ----------------------------------------------------
    # Tenant DSNs are *built* from these parts plus the generated database name.
    # A full tenant DSN is never stored in the registry, so a database dump
    # carries no usable credentials.
    TENANT_DB_HOST: str = "localhost"
    TENANT_DB_PORT: int = 5432
    TENANT_DB_USER: str
    TENANT_DB_PASSWORD: str
    TENANT_DB_MAINTENANCE_DB: str = "postgres"
    """Database connected to for ``CREATE DATABASE`` / ``DROP DATABASE``."""

    # --- Pooling -------------------------------------------------------------
    CENTRAL_POOL_SIZE: int = 10
    CENTRAL_POOL_MAX_OVERFLOW: int = 5
    TENANT_ENGINE_CACHE_SIZE: int = Field(default=15, ge=1, le=200)
    TENANT_POOL_SIZE: int = Field(default=2, ge=1, le=20)
    TENANT_POOL_MAX_OVERFLOW: int = Field(default=3, ge=0, le=20)
    POOL_RECYCLE_SECONDS: int = 1800
    POOL_TIMEOUT_SECONDS: int = 30

    # --- Authentication ------------------------------------------------------
    AUTH_PROVIDER: AuthProvider = AuthProvider.DEV
    FIREBASE_PROJECT_ID: str | None = None
    FIREBASE_CLIENT_EMAIL: str | None = None
    FIREBASE_PRIVATE_KEY: str | None = None
    FIREBASE_CHECK_REVOKED: bool = True

    # --- Session tokens --------------------------------------------------------
    # The identity provider above is consulted once, at /auth/login. Every other
    # request carries a NestFlow access token signed with this key.
    JWT_SECRET_KEY: str | None = None
    """HS256 signing key. Required outside development; at least 32 characters."""
    JWT_ISSUER: str = "nestflow"
    JWT_AUDIENCE: str = "nestflow-api"
    ACCESS_TOKEN_TTL_MINUTES: int = Field(default=15, ge=1, le=120)
    REFRESH_TOKEN_TTL_DAYS: int = Field(default=14, ge=1, le=90)

    # --- CORS ----------------------------------------------------------------
    # NoDecode: keep pydantic-settings from JSON-decoding the dotenv value so
    # the comma-separated form below stays valid.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # --- Rate limiting -------------------------------------------------------
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_ANON_PER_MIN: int = 20
    RATE_LIMIT_USER_PER_MIN: int = 300
    RATE_LIMIT_WRITE_PER_MIN: int = 60

    # --- Storage -------------------------------------------------------------
    STORAGE_PROVIDER: Literal["local", "s3"] = "local"
    STORAGE_LOCAL_PATH: str = "./var/uploads"
    STORAGE_BUCKET: str | None = None
    STORAGE_PUBLIC_BASE_URL: str = "/static/uploads"

    # --- Payments (Phase 4; declared so .env.example stays complete) ----------
    PAYMENT_PROVIDER: str | None = None
    PAYMENT_PROVIDER_KEY: str | None = None
    PAYMENT_PROVIDER_SECRET: str | None = None

    # --- Scheduling (Phase 6) ------------------------------------------------
    SCHEDULER_ENABLED: bool = True
    """In-process APScheduler. Switch it off on every web worker but one — two
    processes running the same nightly sweep double every notification it
    sends. The tests disable it for the same reason."""

    # --- Logging -------------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False

    # --- Locale --------------------------------------------------------------
    DEFAULT_TIMEZONE: str = "Asia/Kolkata"
    DEFAULT_LOCALE: str = "en-IN"
    DEFAULT_CURRENCY: str = "INR"

    # ------------------------------------------------------------------ #
    # Validators
    # ------------------------------------------------------------------ #

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, v: object) -> object:
        """Accept a comma-separated string so .env stays readable."""
        if isinstance(v, str):
            if v.startswith("["):
                return v
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("JWT_SECRET_KEY", mode="before")
    @classmethod
    def _blank_secret_is_unset(cls, v: object) -> object:
        """``JWT_SECRET_KEY=`` in a copied .env.example means "not set"."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("FIREBASE_PRIVATE_KEY", mode="before")
    @classmethod
    def _unescape_private_key(cls, v: object) -> object:
        r"""``.env`` files carry the PEM with literal ``\n``; restore them."""
        if isinstance(v, str):
            return v.replace("\\n", "\n")
        return v

    @model_validator(mode="after")
    def _validate_safety(self) -> Settings:
        """Refuse to construct in an unsafe combination.

        These are not warnings. A misconfigured production process must fail to
        start, because a process that boots with the dev auth verifier accepts
        ``dev:anyone@example.com`` as a valid identity.
        """
        if self.ENVIRONMENT is Environment.PRODUCTION:
            if self.AUTH_PROVIDER is AuthProvider.DEV:
                raise ValueError(
                    "AUTH_PROVIDER=dev is refused when ENVIRONMENT=production. "
                    "The dev verifier accepts any identity without a credential."
                )
            if self.DEBUG:
                raise ValueError("DEBUG=true is refused when ENVIRONMENT=production.")
            if "*" in self.CORS_ORIGINS:
                raise ValueError("Wildcard CORS origin is refused in production.")

        if self.JWT_SECRET_KEY is None:
            if not self.is_development:
                raise ValueError(
                    "JWT_SECRET_KEY is required outside development. Generate one with "
                    "`python -c \"import secrets; print(secrets.token_urlsafe(48))\"`."
                )
        elif len(self.JWT_SECRET_KEY) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters.")

        if self.AUTH_PROVIDER is AuthProvider.FIREBASE:
            missing = [
                name
                for name in ("FIREBASE_PROJECT_ID", "FIREBASE_CLIENT_EMAIL", "FIREBASE_PRIVATE_KEY")
                if not getattr(self, name)
            ]
            if missing:
                raise ValueError(
                    f"AUTH_PROVIDER=firebase requires {', '.join(missing)} to be set."
                )

        return self

    # ------------------------------------------------------------------ #
    # Derived values
    # ------------------------------------------------------------------ #

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT is Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT is Environment.DEVELOPMENT

    @property
    def docs_url(self) -> str | None:
        return None if self.is_production else "/docs"

    @property
    def redoc_url(self) -> str | None:
        return None if self.is_production else "/redoc"

    @property
    def jwt_secret(self) -> str:
        """The signing key. Development falls back to a fixed, public key so a
        fresh checkout runs; ``_validate_safety`` refuses that anywhere else."""
        return self.JWT_SECRET_KEY or _DEV_JWT_SECRET

    @property
    def central_dsn_async(self) -> str:
        return self._as_async(str(self.CENTRAL_DATABASE_URL))

    @property
    def central_dsn_sync(self) -> str:
        return self._as_sync(str(self.CENTRAL_DATABASE_URL))

    def tenant_dsn_async(self, database_name: str) -> str:
        return self._tenant_dsn(database_name, driver="postgresql+psycopg")

    def tenant_dsn_sync(self, database_name: str) -> str:
        return self._tenant_dsn(database_name, driver="postgresql+psycopg")

    def maintenance_dsn_sync(self) -> str:
        """DSN for the maintenance database used to issue CREATE/DROP DATABASE."""
        return self._tenant_dsn(
            self.TENANT_DB_MAINTENANCE_DB,
            driver="postgresql+psycopg",
            validate=False,
        )

    def _tenant_dsn(self, database_name: str, *, driver: str, validate: bool = True) -> str:
        if validate and not DB_NAME_PATTERN.match(database_name):
            raise ValueError(
                f"Refusing to build a DSN for unsafe database name {database_name!r}. "
                f"Tenant database names must match {DB_NAME_PATTERN.pattern}."
            )
        from urllib.parse import quote

        user = quote(self.TENANT_DB_USER, safe="")
        password = quote(self.TENANT_DB_PASSWORD, safe="")
        return (
            f"{driver}://{user}:{password}"
            f"@{self.TENANT_DB_HOST}:{self.TENANT_DB_PORT}/{database_name}"
        )

    @staticmethod
    def _as_async(dsn: str) -> str:
        for prefix in ("postgresql+psycopg://", "postgresql+asyncpg://"):
            if dsn.startswith(prefix):
                return dsn.replace(prefix, "postgresql+psycopg://", 1)
        return dsn.replace("postgresql://", "postgresql+psycopg://", 1)

    @staticmethod
    def _as_sync(dsn: str) -> str:
        return dsn.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1).replace(
            "postgresql+psycopg://", "postgresql+psycopg://", 1
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton. Import this, never construct ``Settings()``."""
    return Settings()  # type: ignore[call-arg]


SettingsDep = Annotated[Settings, Field()]
