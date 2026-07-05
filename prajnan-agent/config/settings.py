from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Literal
import pytz
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent

class Settings(BaseSettings):
    anthropic_api_key: str = Field(default="")
    claude_model: str = Field(default="claude-haiku-4-5-20251001")
    fyers_client_id: str = Field(default="")
    fyers_secret_key: str = Field(default="")
    fyers_redirect_uri: str = Field(default="https://trade.fyers.in/api-login/redirect-uri/index.html")
    fyers_totp_secret: str = Field(default="")
    fyers_pin: str = Field(default="")
    angelone_api_key: str = Field(default="")
    angelone_client_id: str = Field(default="")
    angelone_password: str = Field(default="")
    angelone_totp_secret: str = Field(default="")
    telegram_bot_token: str = Field(default="")
    telegram_chat_id: str = Field(default="")
    finnhub_api_key: str = Field(default="")
    max_daily_loss_rs: float = Field(default=5000.0)
    max_capital_deployed_rs: float = Field(default=50000.0)
    max_open_positions: int = Field(default=3)
    vix_ceiling: float = Field(default=20.0)
    max_loss_per_trade_rs: float = Field(default=2000.0)
    trading_mode: Literal["PAPER", "LIVE"] = Field(default="PAPER")
    decision_cycle_minutes: int = Field(default=15)
    news_scan_minutes: int = Field(default=10)
    timezone: str = Field(default="Asia/Kolkata")
    market_open_time: str = Field(default="09:15")
    market_close_time: str = Field(default="15:30")
    pre_market_scan_time: str = Field(default="08:30")
    database_url: str = Field(default="sqlite:///cognex_agent.db")
    log_level: str = Field(default="INFO")
    log_file: str = Field(default="logs/cognex_agent.log")

    class Config:
        env_file = ROOT_DIR / "config" / ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False

    @property
    def ist_timezone(self):
        return pytz.timezone(self.timezone)

    @property
    def is_paper_mode(self) -> bool:
        return self.trading_mode == "PAPER"

    @property
    def is_live_mode(self) -> bool:
        return self.trading_mode == "LIVE"

settings = Settings()
