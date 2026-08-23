"""Runtime configuration.

Secrets are loaded from environment variables only. They must never be logged or
returned by an API response. The defaults support local development; production
startup performs stricter validation in :mod:`app.main`.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    environment: Literal["development", "test", "production"] = "development"
    database_url: str = "sqlite:///./market_intelligence.db"
    api_prefix: str = "/api/v1"
    company_name: str = "Pilot Company"

    # Temporary pilot credentials. Authentication is deliberately isolated so
    # it can be replaced by client-selected SSO without touching domain logic.
    admin_username: str = "Admin"
    admin_password: str = "Password"

    whatsapp_api_version: str = ""
    whatsapp_access_token: str = ""
    whatsapp_app_secret: str = ""
    whatsapp_verify_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_graph_base_url: str = "https://graph.facebook.com"
    whatsapp_signature_required: bool = True

    openai_api_key: str = ""
    openai_monthly_budget_usd: float = Field(default=50.0, ge=0)

    aws_region: str = "ap-south-1"
    s3_bucket: str = "market-intelligence-media"
    clamav_host: str = ""
    clamav_port: int = 3310
    conversation_timeout_minutes: int = Field(default=30, ge=1, le=240)
    max_webhook_bytes: int = Field(default=2_000_000, ge=1_000)

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def production_errors(self) -> list[str]:
        if not self.is_production:
            return []
        errors: list[str] = []
        if self.database_url.startswith("sqlite"):
            errors.append("DATABASE_URL must point to PostgreSQL")
        if self.admin_password == "Password" or len(self.admin_password) < 12:
            errors.append("ADMIN_PASSWORD must be changed and contain at least 12 characters")
        required = {
            "WHATSAPP_API_VERSION": self.whatsapp_api_version,
            "WHATSAPP_APP_SECRET": self.whatsapp_app_secret,
            "WHATSAPP_VERIFY_TOKEN": self.whatsapp_verify_token,
            "WHATSAPP_PHONE_NUMBER_ID": self.whatsapp_phone_number_id,
        }
        errors.extend(f"{name} is required" for name, value in required.items() if not value)
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()
