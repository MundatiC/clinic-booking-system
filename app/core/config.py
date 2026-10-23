"""Application settings, loaded from environment variables (and `.env` locally)."""

from functools import lru_cache
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.ratelimit import parse_rate


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"

    database_url: str = "postgresql+psycopg://clinic:clinic@localhost:55432/clinic"
    db_pool_size: int = 5
    db_max_overflow: int = 5
    db_pool_timeout_seconds: int = 10
    db_statement_timeout_ms: int = 5000

    clinic_timezone: str = "Africa/Nairobi"
    slot_minutes: int = Field(default=30, gt=0, le=240)
    min_lead_time_minutes: int = Field(default=60, ge=0)
    max_advance_days: int = Field(default=90, gt=0)

    # Comma-separated list in the env var, e.g. "https://a.example,https://b.example".
    cors_origins: Annotated[list[str], NoDecode] = []
    rate_limit_writes: str = "30/minute"
    rate_limit_enabled: bool = True
    max_body_bytes: int = 16 * 1024

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [o.strip() for o in value.split(",") if o.strip()]
        return value

    @field_validator("cors_origins")
    @classmethod
    def _no_wildcard(cls, value: list[str]) -> list[str]:
        if "*" in value:
            raise ValueError("CORS wildcard is not allowed; list explicit origins")
        return value

    @field_validator("rate_limit_writes")
    @classmethod
    def _valid_rate(cls, value: str) -> str:
        parse_rate(value)
        return value

    @field_validator("database_url")
    @classmethod
    def _psycopg_driver(cls, value: str) -> str:
        # Render (and most hosts) hand out postgres:// or postgresql:// URLs.
        for prefix in ("postgres://", "postgresql://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix) :]
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.clinic_timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()
