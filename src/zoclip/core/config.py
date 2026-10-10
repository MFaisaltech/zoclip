from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="forbid", hide_input_in_errors=True)

    app_env: Literal["development", "test", "production"] = "development"
    database_url: SecretStr
    postgres_password: SecretStr = SecretStr("")  # Compose bootstrap; never exposed.
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    public_app_url: str = "http://localhost:3000"
    api_public_url: str = "http://localhost:8000"
    allowed_hosts: list[str] = ["localhost", "127.0.0.1", "testserver"]
    cookie_secure: bool = True
    session_ttl_seconds: int = Field(default=86400, ge=300, le=2592000)
    anonymous_ttl_seconds: int = Field(default=1800, ge=60, le=3600)
    auth_rate_limit: int = Field(default=10, ge=1, le=100)
    auth_rate_window_seconds: int = Field(default=900, ge=1, le=3600)
    email_mode: Literal["disabled", "development"] = "disabled"
    dev_mailbox_dir: str = "var/mailbox"
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_redirect_uri: str = ""
    enable_live_payments: bool = False
    enable_trial_credits: bool = False
    payment_provider: Literal["disabled", "mock"] = "disabled"
    media_root: str = "var/media"
    media_max_bytes: int = Field(default=4 * 1024**3, ge=1, le=4 * 1024**3)
    media_part_bytes: int = Field(default=8 * 1024**2, ge=65536, le=8 * 1024**2)
    media_headroom_bytes: int = Field(default=20 * 1024**3, ge=20 * 1024**3)
    media_retained_bytes: int = Field(default=40 * 1024**3, ge=1)
    media_ingestion_limit: int = Field(default=2, ge=1, le=2)
    media_user_ingestion_limit: int = Field(default=1, ge=1, le=1)
    media_pending_limit: int = Field(default=10, ge=1, le=100)
    media_user_processing_limit: int = Field(default=1, ge=1, le=1)
    media_upload_ttl_seconds: int = Field(default=86400, ge=300, le=86400)
    media_retention_seconds: int = Field(default=604800, ge=300, le=604800)
    media_allowed_import_hosts: list[str] = []
    ffprobe_binary: str = "ffprobe"

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id)

    @model_validator(mode="after")
    def validate_deployment(self) -> Self:
        db = make_url(self.database_url.get_secret_value())
        if db.drivername != "postgresql+psycopg":
            raise ValueError("DATABASE_URL must use postgresql+psycopg")
        if urlsplit(self.redis_url.get_secret_value()).scheme not in {"redis", "rediss"}:
            raise ValueError("REDIS_URL must use redis or rediss")
        for value in (self.public_app_url, self.api_public_url):
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise ValueError("Public URLs must be exact HTTP(S) origins")
        self.public_app_url = self.public_app_url.rstrip("/")
        self.api_public_url = self.api_public_url.rstrip("/")
        if not self.allowed_hosts or "*" in self.allowed_hosts:
            raise ValueError("Explicit ALLOWED_HOSTS required")
        google_values = (
            self.google_client_id,
            self.google_client_secret.get_secret_value(),
            self.google_redirect_uri,
        )
        if any(google_values) and not all(google_values):
            raise ValueError("Google configuration must be complete or entirely absent")
        if self.google_redirect_uri and self.google_redirect_uri != (
            self.api_public_url + "/api/v1/auth/google/callback"
        ):
            raise ValueError("GOOGLE_REDIRECT_URI must equal the API callback URL")
        if self.enable_live_payments or self.enable_trial_credits:
            raise ValueError(
                "Live payments and automatic trials remain disabled pending verification"
            )
        if any(
            not h or h != h.lower() or any(c in h for c in "/:*@\\") or h.endswith(".")
            for h in self.media_allowed_import_hosts
        ):
            raise ValueError("Import allowlist requires exact lowercase DNS hostnames")
        if self.app_env == "production":
            if not self.cookie_secure or self.email_mode == "development":
                raise ValueError("Production requires secure cookies and forbids development email")
            if self.payment_provider != "disabled":
                raise ValueError("Production mock payments forbidden")
            if any(
                not url.startswith("https://") for url in (self.public_app_url, self.api_public_url)
            ):
                raise ValueError("Production public URLs must use HTTPS")
            if any(host in {"localhost", "127.0.0.1", "testserver"} for host in self.allowed_hosts):
                raise ValueError("Production requires real allowed hosts")
            if not db.password or db.password.lower() in {"change_me", "password", "zoclip"}:
                raise ValueError("Production database credentials must be configured")
        return self
