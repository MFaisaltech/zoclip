import base64
import re
from pathlib import Path
from typing import Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import EmailStr, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="forbid",
        hide_input_in_errors=True,
        secrets_dir="/run/secrets" if Path("/run/secrets").is_dir() else None,
    )

    app_env: Literal["development", "test", "production"] = "development"
    private_staging: bool = False
    staging_site_domain: str = ""
    staging_invite_epoch: UUID | None = (
        None  # Rotate outside DB after any restore; old tokens fail.
    )
    registration_enabled: bool = False  # Production registration is explicit opt-in.
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
    email_mode: Literal["disabled", "development", "smtp"] = "disabled"
    dev_mailbox_dir: str = "var/mailbox"
    smtp_host: str = ""
    smtp_port: Literal[465, 587] = 465
    smtp_tls: Literal["implicit", "starttls"] = "implicit"
    smtp_username: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: EmailStr | None = None
    smtp_timeout_seconds: int = Field(default=15, ge=1, le=30)
    email_queue_key: SecretStr = SecretStr("")
    google_client_id: str = ""
    google_client_secret: SecretStr = SecretStr("")
    google_redirect_uri: str = ""
    enable_live_payments: bool = False
    enable_trial_credits: bool = False
    payment_provider: Literal["disabled", "mock", "jazzcash"] = "disabled"
    payment_mock_webhook_secret: SecretStr = SecretStr("")
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
    ffmpeg_binary: str = "ffmpeg"
    render_deadline_seconds: int = Field(default=240, ge=10, le=300)
    render_threads: int = Field(default=4, ge=1, le=16)
    render_max_bytes: int = Field(default=256 * 1024**2, ge=1024**2, le=512 * 1024**2)
    ai_enabled: bool = False
    transcription_provider: Literal["whisper", "deepgram"] = "whisper"
    # Only the reviewed CPU configuration has an image-pinned model in this phase.
    whisper_model: Literal["small"] = "small"
    whisper_compute_type: Literal["int8"] = "int8"
    whisper_device: Literal["cpu"] = "cpu"
    whisper_model_path: str = "/opt/models/faster-whisper-small"
    whisper_chunk_seconds: int = Field(default=120, ge=30, le=180)
    whisper_overlap_seconds: float = Field(default=1.0, ge=0, le=2)
    deepgram_api_key: SecretStr = SecretStr("")
    deepgram_model: str = Field(default="", pattern=r"^[a-zA-Z0-9._-]{0,60}$")
    deepgram_version: str = Field(default="", pattern=r"^[a-zA-Z0-9._-]{0,60}$")
    deepgram_language: str = Field(default="en", pattern=r"^[a-zA-Z0-9-]{2,20}$")
    ai_approved_languages: list[str] = ["en"]
    deepgram_diarize: bool = False
    deepgram_utterances: bool = False
    deepgram_mip_opt_out: bool = True
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = Field(default="", pattern=r"^[a-zA-Z0-9._-]{0,100}$")
    ai_provider_timeout_seconds: int = Field(default=120, ge=1, le=180)
    ai_calls_per_minute: int = Field(default=30, ge=1, le=60)
    ai_chunk_bytes: int = Field(default=65536, ge=1000, le=262144)
    ai_max_chunks: int = Field(default=64, ge=1, le=256)
    ai_max_output_tokens: int = Field(default=2048, ge=128, le=8192)
    ai_max_candidates: int = Field(default=10, ge=1, le=20)
    ai_min_clip_seconds: int = Field(default=15, ge=1, le=60)
    ai_max_clip_seconds: int = Field(default=90, ge=1, le=180)

    @field_validator("smtp_from", mode="before")
    @classmethod
    def blank_smtp_from(cls, value: str | None) -> str | None:
        return value or None

    @property
    def ai_configured(self) -> bool:
        return self.ai_enabled and bool(
            self.gemini_api_key.get_secret_value()
            and self.gemini_model
            and (
                self.transcription_provider == "whisper"
                or (
                    self.deepgram_api_key.get_secret_value()
                    and self.deepgram_model
                    and self.deepgram_version
                )
            )
        )

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id)

    @model_validator(mode="after")
    def validate_deployment(self) -> Self:
        if self.email_mode == "smtp":
            try:
                queue_key = base64.b64decode(
                    self.email_queue_key.get_secret_value(), altchars=b"-_", validate=True
                )
                if len(queue_key) != 32:
                    raise ValueError
            except ValueError:
                raise ValueError(
                    "SMTP delivery requires a private 32-byte base64 EMAIL_QUEUE_KEY"
                ) from None
        if self.email_mode == "smtp":
            if (
                not self.smtp_host
                or len(self.smtp_host) > 253
                or any(
                    not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", part)
                    for part in self.smtp_host.split(".")
                )
                or not self.smtp_username
                or "\r" in self.smtp_username
                or "\n" in self.smtp_username
                or not self.smtp_password.get_secret_value()
                or self.smtp_from is None
                or (self.smtp_tls, self.smtp_port) not in {("implicit", 465), ("starttls", 587)}
                or not self.public_app_url.startswith("https://")
            ):
                raise ValueError("SMTP requires complete credentials, verified TLS and HTTPS links")
        if self.app_env == "production" and self.registration_enabled and self.email_mode != "smtp":
            raise ValueError("Production signup requires configured transactional email delivery")
        if self.payment_provider == "mock":
            sandbox_secret = self.payment_mock_webhook_secret.get_secret_value()
            if len(sandbox_secret) < 32 or sandbox_secret.lower().startswith(
                ("change", "placeholder", "set_")
            ):
                raise ValueError("Explicit sandbox payments require a private webhook secret")
        if self.deepgram_language not in self.ai_approved_languages:
            raise ValueError("Deepgram language must be explicitly approved")
        if self.ai_min_clip_seconds > self.ai_max_clip_seconds:
            raise ValueError("AI clip duration bounds are invalid")
        if self.ai_enabled and not self.ai_configured:
            raise ValueError(
                "AI enablement requires the selected provider and pinned Gemini configuration"
            )
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
            for secret in (self.deepgram_api_key, self.gemini_api_key):
                if secret.get_secret_value() and (
                    len(secret.get_secret_value()) < 20
                    or secret.get_secret_value()
                    .lower()
                    .startswith(("change", "test", "placeholder", "synthetic", "fictional", "set_"))
                ):
                    raise ValueError("Production provider keys must be configured privately")
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
        if self.private_staging:
            domain = self.staging_site_domain
            if (
                self.app_env != "production"
                or self.ai_enabled
                or self.registration_enabled
                or self.email_mode != "disabled"
                or self.payment_provider != "disabled"
                or self.google_enabled
                or self.media_allowed_import_hosts
                or self.deepgram_api_key.get_secret_value()
                or self.gemini_api_key.get_secret_value()
            ):
                raise ValueError(
                    "Private staging forbids public signup, AI, payments and integrations"
                )
            label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
            if (
                len(domain) > 253
                or not re.fullmatch(rf"{label}(?:\.{label})+", domain)
                or domain
                in {
                    "vercel.app",
                    "localhost",
                }
            ):
                raise ValueError("Private staging requires an explicitly owned same-site domain")
            for origin in (self.public_app_url, self.api_public_url):
                parsed = urlsplit(origin)
                host = parsed.hostname or ""
                port = f":{parsed.port}" if parsed.port not in {None, 443} else ""
                if origin != f"https://{host}{port}":
                    raise ValueError("Private staging requires canonical exact HTTPS origins")
                if host != domain and not host.endswith("." + domain):
                    raise ValueError("Frontend and API must use the owned staging site domain")
                if len(host) > 253 or not re.fullmatch(rf"{label}(?:\.{label})+", host):
                    raise ValueError("Staging origins require exact valid DNS hostnames")
            if urlsplit(self.public_app_url).hostname == urlsplit(self.api_public_url).hostname:
                raise ValueError("Separate frontend/API subdomains required for host-only cookies")
            if self.allowed_hosts != [urlsplit(self.api_public_url).hostname]:
                raise ValueError("Private staging ALLOWED_HOSTS must contain only the API hostname")
        return self
