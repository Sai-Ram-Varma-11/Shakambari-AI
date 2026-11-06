from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Shakambari AI"
    app_version: str = "1.0.0"
    app_env: str = "development"
    database_url: str = "sqlite:///./shakambari.db"
    secret_key: str = "dev-only-shakambari-secret-key-32chars-minimum-length"
    access_token_minutes: int = 480
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    timezone: str = "Asia/Kolkata"
    trust_proxy: bool = True

    # Uploads & Storage
    storage_backend: str = "local"
    upload_dir: str = "uploads"
    model_dir: str = "model_store"
    max_upload_mb: int = 5
    s3_bucket: Optional[str] = None
    s3_endpoint_url: Optional[str] = None
    s3_access_key_id: Optional[str] = None
    s3_secret_access_key: Optional[str] = None

    # Rate Limiting
    rate_limit_backend: str = "memory"  # memory | db | redis
    redis_url: Optional[str] = None

    # Authentication & OTP
    login_otp_enabled: bool = True
    dev_log_otp: bool = True
    debug_return_reset_token: bool = False

    # Email provider (smtp | resend | brevo)
    email_provider: str = "smtp"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    mail_from_name: str = "Shakambari AI"
    mail_from_address: Optional[str] = None
    resend_api_key: Optional[str] = None
    brevo_api_key: Optional[str] = None

    # Vision provider (heuristic | llm)
    vision_provider: str = "heuristic"
    vision_api_key: Optional[str] = None
    vision_model: str = "gemini-1.5-flash"

    # Scheduling, Startup & Demo
    scheduler_enabled: bool = False
    seed_demo_on_empty: bool = True
    seed_demo_password: str = "Demo@12345"
    co2e_per_kg_food: float = 2.5

    @property
    def origins(self):
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()

# Hardened production verification
KNOWN_PLACEHOLDERS = ("change-me", "dev-only", "secret", "test")
if settings.app_env == "production":
    key = settings.secret_key.strip()
    if len(key) < 32 or any(key.lower().startswith(p) for p in KNOWN_PLACEHOLDERS):
        raise RuntimeError("In production, SECRET_KEY must be at least 32 characters and cannot match known placeholders.")
