"""Application configuration.

All configuration comes from the environment (12-factor). No secrets or
machine-specific paths are hardcoded here - see SECURITY_SPEC.md Section 2/8.
"""

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Environment -------------------------------------------------------
    ENVIRONMENT: Literal["development", "test", "production"] = "development"
    DEBUG: bool = False

    PROJECT_NAME: str = "DealFlow360"
    API_V1_PREFIX: str = "/api/v1"

    # --- Database ----------------------------------------------------------
    POSTGRES_USER: str = "dealflow"
    # No default: a missing password must fail loudly at startup rather than
    # silently falling back to a value baked into the source
    # (SECURITY_SPEC.md Section 8 - never hardcode secrets).
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str = "dealflow360"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432

    # Bounded pool - SECURITY_SPEC.md Section 6.
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    DB_ECHO: bool = False

    # --- JWT (wired up in Phase 6; declared here so config is complete) -----
    # No default, for the same reason as POSTGRES_PASSWORD. Generate with:
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ISSUER: str = "dealflow360"
    JWT_AUDIENCE: str = "dealflow360-api"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # --- CORS --------------------------------------------------------------
    # Explicit allowlist only. SECURITY_SPEC.md Section 5: never wildcard when
    # credentials are allowed.
    #
    # NoDecode is required: without it pydantic-settings tries to JSON-parse
    # any complex-typed env var *before* validators run, so the plain
    # comma-separated CORS_ORIGINS in .env raises a SettingsError at startup.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """Accept a comma-separated string from the environment."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def database_url(self) -> str:
        """Async (asyncpg) URL used by the application at runtime."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
