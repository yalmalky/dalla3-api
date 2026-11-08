from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql://localhost/dalla3"
    jwt_secret: str = "dalla3-dev-secret-change-me"
    jwt_alg: str = "HS256"
    jwt_expire_hours: int = 720  # 30 days for family test
    cors_origins: str = "*"
    commission_rate: float = 0.15
    payment_provider: str = "mock"  # mock | moyasar later
    # Sign in with Apple: accepted `aud` values (iOS bundle id; add a Services ID later for web)
    apple_client_ids: str = "com.yalmalky.dalla3"
    # Google Sign-In: comma-separated OAuth client IDs (iOS + web). Empty = Google login disabled.
    google_client_ids: str = ""
    # Exact Apple reviewer mailboxes, comma-separated. Empty = nobody. Domains are ignored.
    apple_reviewer_emails: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
