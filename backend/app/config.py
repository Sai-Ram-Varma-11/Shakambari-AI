from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    database_url: str = "sqlite:///./platesense.db"
    secret_key: str = "dev-only-change-me"
    access_token_minutes: int = 480
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    timezone: str = "Asia/Kolkata"
    upload_dir: str = "uploads"
    model_dir: str = "model_store"
    max_upload_mb: int = 5
    debug_return_reset_token: bool = False  # dev only: no email provider is wired up
    scheduler_enabled: bool = False
    co2e_per_kg_food: float = 2.5  # configurable ESTIMATE factor (kg CO2e per kg food); verify before citing
    seed_demo_password: str = "Demo@12345"

    @property
    def origins(self):
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
if settings.app_env == "production" and settings.secret_key.startswith("dev-only"):
    raise RuntimeError("SECRET_KEY must be set in production")
