"""Minimal settings for fyers-auth-service."""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings

ROOT_DIR = Path(__file__).parent.parent


class Settings(BaseSettings):
    fyers_client_id: str = Field(default="")
    fyers_secret_key: str = Field(default="")
    fyers_redirect_uri: str = Field(default="https://trade.fyers.in/api-login/redirect-uri/index.html")
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")
    timezone: str = Field(default="Asia/Kolkata")
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/fyers-auth.log")

    class Config:
        env_file = ROOT_DIR / "config" / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False
        extra = "ignore"


settings = Settings()
