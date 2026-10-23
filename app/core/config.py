"""Application settings, loaded from environment variables (and `.env` locally)."""

from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.ratelimit import parse_rate


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["local", "test", "production"] = "local"
    log_level: str = "INFO"
    # Deployed commit. Render injects RENDER_GIT_COMMIT; the deploy smoke test waits for it.
    git_commit: str = Field(
        default="dev", validation_alias=AliasChoices("GIT_COMMIT", "RENDER_GIT_COMMIT")
    )

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
    rate_limit_auth: str = "10/minute"
    rate_limit_enabled: bool = True
    max_body_bytes: int = 16 * 1024

    # Public origin of this app: used for links in emails and as the trusted
    # Origin for cookie-authenticated writes (CSRF check).
    public_base_url: str = "http://localhost:8000"
    clinic_name: str = "The Clinic"

    session_idle_minutes: int = Field(default=30, gt=0)
    session_max_hours: int = Field(default=12, gt=0)
    login_max_failures: int = Field(default=5, gt=0)
    login_lockout_minutes: int = Field(default=15, gt=0)
    # Off where the mail provider can't reach arbitrary inboxes (a demo without a sending
    # domain): new accounts sign in at once. Claiming a walk-in record always needs it.
    require_email_verification: bool = True
    # Optional: seed creates/updates one staff account from these (never committed).
    staff_email: str | None = None
    staff_password: SecretStr | None = None
    # Optional: seed gives the demo patient a verified login with this password.
    demo_patient_password: SecretStr | None = None

    # SMTP. Dev: Mailpit (docker compose). Production: Gmail (smtp.gmail.com, port 587,
    # security "starttls", user = the Gmail address, password = a Google app password).
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_security: Literal["none", "starttls", "ssl"] = "none"
    smtp_user: str | None = None
    smtp_password: SecretStr | None = None
    mail_from: str = "The Clinic <no-reply@clinic.localhost>"

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

    @field_validator("rate_limit_writes", "rate_limit_auth")
    @classmethod
    def _valid_rate(cls, value: str) -> str:
        parse_rate(value)
        return value

    @field_validator("public_base_url")
    @classmethod
    def _origin_only(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in ("http", "https") or not parts.netloc or parts.path not in ("", "/"):
            raise ValueError("PUBLIC_BASE_URL must be an origin like https://clinic.example")
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def trusted_origins(self) -> frozenset[str]:
        return frozenset([self.public_base_url, *self.cors_origins])

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
