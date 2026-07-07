from datetime import datetime, date
import pytz
from loguru import logger
from config.settings import settings
from utils.expiry_calculator import is_trading_day

class RiskCheckResult:
    def __init__(self, passed: bool, reason: str = ""):
        self.passed = passed
        self.reason = reason
    def __bool__(self):
        return self.passed

class RiskGuard:
    def __init__(self):
        self.max_daily_loss = settings.max_daily_loss_rs
        self.max_capital = settings.max_capital_deployed_rs
        self.max_positions = settings.max_open_positions
        self.vix_ceiling = settings.vix_ceiling
        self.max_loss_per_trade = settings.max_loss_per_trade_rs

    def check_all(self, vix, current_positions, proposed_margin_rs, proposed_max_loss_rs, is_expiry_day=False):
        checks = [
            self.check_market_hours(),
            # self.check_vix(vix),  # VIX entry filter DISABLED — re-enable when needed
            self.check_daily_loss(),
            self.check_position_count(current_positions),
            self.check_capital(proposed_margin_rs),
            self.check_per_trade_loss(proposed_max_loss_rs),
        ]
        for check in checks:
            if not check.passed:
                logger.warning(f"RISK BLOCK: {check.reason}")
                return check
        logger.info("All risk checks PASSED")
        return RiskCheckResult(True, "All checks passed")

    def check_market_hours(self):
        now = datetime.now(settings.ist_timezone)
        weekday = now.weekday()
        if weekday >= 5:
            return RiskCheckResult(False, f"Weekend — market closed")
        if not is_trading_day(now.date()):
            return RiskCheckResult(False, f"NSE Holiday — market closed today ({now.date()})")
        market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        if now < market_open:
            return RiskCheckResult(False, f"Pre-market — opens at 9:15am IST (now {now.strftime('%H:%M')} IST)")
        if now > market_close:
            return RiskCheckResult(False, f"Post-market — closed at 3:30pm IST (now {now.strftime('%H:%M')} IST)")
        return RiskCheckResult(True, "Market is open")

    def check_vix(self, vix):
        if vix <= 0:
            return RiskCheckResult(False, f"VIX data unavailable ({vix})")
        if vix > self.vix_ceiling:
            return RiskCheckResult(False, f"VIX {vix:.1f} exceeds ceiling {self.vix_ceiling}")
        return RiskCheckResult(True, f"VIX {vix:.1f} within safe range")

    def check_daily_loss(self):
        today_pnl = self._get_today_pnl()
        if today_pnl <= -self.max_daily_loss:
            return RiskCheckResult(False, f"Daily loss limit hit: Rs{today_pnl:.0f}")
        return RiskCheckResult(True, f"Daily PnL: Rs{today_pnl:.0f}")

    def check_position_count(self, current_count):
        if current_count >= self.max_positions:
            return RiskCheckResult(False, f"Max positions reached: {current_count}/{self.max_positions}")
        return RiskCheckResult(True, f"Positions: {current_count}/{self.max_positions}")

    def check_capital(self, proposed_margin_rs):
        if proposed_margin_rs > self.max_capital:
            return RiskCheckResult(False, f"Margin Rs{proposed_margin_rs:.0f} exceeds max Rs{self.max_capital:.0f}")
        return RiskCheckResult(True, f"Capital OK: Rs{proposed_margin_rs:.0f}")

    def check_per_trade_loss(self, max_loss_rs):
        if max_loss_rs > self.max_loss_per_trade:
            return RiskCheckResult(False, f"Trade risk Rs{max_loss_rs:.0f} exceeds limit Rs{self.max_loss_per_trade:.0f}")
        return RiskCheckResult(True, f"Per-trade risk OK")

    def emergency_stop(self):
        with open("logs/EMERGENCY_STOP", "w") as f:
            f.write(f"STOPPED at {datetime.now().isoformat()}")
        logger.critical("EMERGENCY STOP ACTIVATED")
        return True

    def is_emergency_stopped(self):
        import os
        return os.path.exists("logs/EMERGENCY_STOP")

    def clear_emergency_stop(self):
        import os
        if os.path.exists("logs/EMERGENCY_STOP"):
            os.remove("logs/EMERGENCY_STOP")
            logger.info("Emergency stop cleared")

    def _get_today_pnl(self):
        try:
            from core.database import SessionLocal, Trade
            from datetime import datetime as _dt
            db = SessionLocal()
            start = _dt.combine(date.today(), _dt.min.time())
            trades = db.query(Trade).filter(
                Trade.status == "CLOSED",
                Trade.exit_time >= start,
            ).all()
            db.close()
            return float(sum((t.pnl_rs or 0.0) for t in trades))
        except Exception as e:
            logger.error(f"Could not fetch today PnL: {e}")
            return 0.0

    def get_risk_summary(self, vix, positions):
        today_pnl = self._get_today_pnl()
        remaining = self.max_daily_loss + today_pnl
        return (
            f"Risk Status\n"
            f"VIX: {vix:.1f} (ceiling: {self.vix_ceiling})\n"
            f"Open Positions: {positions}/{self.max_positions}\n"
            f"Today PnL: Rs{today_pnl:.0f}\n"
            f"Daily loss budget remaining: Rs{remaining:.0f}\n"
            f"Mode: {'PAPER' if settings.is_paper_mode else 'LIVE'}"
        )

risk_guard = RiskGuard()
