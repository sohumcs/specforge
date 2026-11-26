"""Application settings, loaded from environment variables (12-factor).

Every setting has a safe development default except secrets, which must be
provided in production (`ENVIRONMENT=production` refuses the dev secret).
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Dev placeholder only; Settings refuses it when ENVIRONMENT=production.
DEV_SECRET = "dev-only-insecure-secret-change-me-0123456789"  # noqa: S105  # nosec B105


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    app_version: str = "0.1.0"
    git_sha: str = "dev"
    ci_run_url: str = ""
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://specforge:specforge@localhost:5432/specforge"
    redis_url: str = "redis://localhost:6379/0"

    jwt_secret: str = DEV_SECRET
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 15
    refresh_token_days: int = 7
    cookie_secure: bool = False
    refresh_cookie_name: str = "sf_refresh"

    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    demo_email: str = "demo@specforge.dev"
    sandbox_project_name: str = "Sandbox"

    max_graph_depth: int = 12

    @model_validator(mode="after")
    def _refuse_weak_secret_in_prod(self) -> "Settings":
        if self.environment == "production" and (
            self.jwt_secret == DEV_SECRET or len(self.jwt_secret) < 32
        ):
            raise ValueError("JWT_SECRET must be set to a 32+ character secret in production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
