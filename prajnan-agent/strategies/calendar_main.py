"""
calendar_main.py
----------------
Scheduler for the Nifty Calendar Spread strategy.

Schedule (all IST, Mon-Fri):
  15:24 → exit_weekly_legs()  on weekly expiry day
  15:24 → exit_all()          on monthly expiry day (overrides weekly)
  15:26 → roll_weekly()       on weekly expiry day
  15:26 → enter()             on monthly expiry day (first entry)
  Every 5 min (09:20→15:20)  → check_sl()

Run in background:
  cd ~/prajnan-agent && source venv/bin/activate
  nohup python3 strategies/calendar_main.py >> logs/calendar_spread.log 2>&1 &

Check logs:
  tail -f logs/calendar_spread.log
"""

import logging
import os
import sys
import datetime

sys.path.insert(0, os.path.expanduser("~/prajnan-agent"))

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from strategies.calendar_spread_strategy import (
    CalendarSpreadStrategy,
    ENTRY_TIME,
    WEEKLY_EXIT_TIME,
    MONTHLY_EXIT_TIME,
    SL_CANDLE_TF,
    SL_CHECK_MODE,
    LOTS,
    PRODUCT_TYPE,
)
from brokers.fyers_connector import fyers_connector
from config.settings import settings

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

os.makedirs(os.path.expanduser("~/prajnan-agent/logs"), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s IST [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.expanduser("~/prajnan-agent/logs/calendar_spread.log")),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("calendar_main")
IST = pytz.timezone("Asia/Kolkata")

# ─────────────────────────────────────────────
# GLOBALS
# ─────────────────────────────────────────────

strategy:  CalendarSpreadStrategy = None
scheduler: BlockingScheduler      = None


# ─────────────────────────────────────────────
# JOBS
# ─────────────────────────────────────────────

def job_15_24():
    """
    15:24 IST — fires every expiry day.
    Monthly expiry → exit_all()
    Weekly expiry  → exit_weekly_legs()
    """
    logger.info("⏰ 15:24 job fired")
    try:
        if strategy.is_on_monthly_expiry():
            logger.info("Monthly expiry day → exiting ALL positions")
            strategy.exit_all()
        elif strategy.is_on_weekly_expiry():
            logger.info("Weekly expiry day → exiting weekly legs")
            strategy.exit_weekly_legs()
        else:
            logger.debug("Not an expiry day — 15:24 job skipped")
    except Exception as e:
        logger.error(f"Error in 15:24 job: {e}", exc_info=True)


def job_15_26():
    """
    15:26 IST — fires every expiry day, 2 minutes after exit.
    Monthly expiry → enter() new month
    Weekly expiry  → roll_weekly()
    """
    logger.info("⏰ 15:26 job fired")
    try:
        if strategy.is_on_monthly_expiry():
            logger.info("Monthly expiry day → entering new month")
            strategy.enter()
        elif strategy.is_on_weekly_expiry():
            logger.info("Weekly expiry day → rolling to next weekly")
            strategy.roll_weekly()
        else:
            logger.debug("Not an expiry day — 15:26 job skipped")
    except Exception as e:
        logger.error(f"Error in 15:26 job: {e}", exc_info=True)


def job_check_sl():
    """Every 5 min during market hours — SL check and hedge loop."""
    try:
        if SL_CHECK_MODE == "candle_close":
            strategy.check_sl()
    except Exception as e:
        logger.error(f"Error in check_sl: {e}", exc_info=True)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def parse_hhmm(t: str):
    h, m = t.split(":")
    return int(h), int(m)


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    global strategy, scheduler

    logger.info("=" * 60)
    logger.info("COGNEX Calendar Spread Strategy — Starting")
    logger.info(f"Exit time      : {WEEKLY_EXIT_TIME} IST (weekly) / {MONTHLY_EXIT_TIME} IST (monthly)")
    logger.info(f"Entry time     : {ENTRY_TIME} IST")
    logger.info(f"SL check mode  : {SL_CHECK_MODE} ({SL_CANDLE_TF} min)")
    logger.info(f"Product type   : {PRODUCT_TYPE}")
    logger.info(f"Lots           : {LOTS} ({LOTS * 25} qty)")
    logger.info(f"Paper trading  : {settings.trading_mode == 'PAPER'}")
    logger.info("=" * 60)

    # Connect Fyers
    logger.info("Connecting to Fyers...")
    if not fyers_connector.connect():
        logger.error("Fyers connection failed — exiting.")
        sys.exit(1)
    logger.info("Fyers connected ✓")

    fyers  = fyers_connector.fyers
    paper  = (settings.trading_mode == "PAPER")

    strategy = CalendarSpreadStrategy(fyers=fyers, paper_trading=paper)
    logger.info(f"Strategy loaded — phase: {strategy.state['phase']}")
    logger.info(f"Monthly expiry : {strategy.state.get('monthly_expiry', 'not set')}")
    logger.info(f"Weekly expiry  : {strategy.state.get('weekly_expiry', 'not set')}")

    # ── Build scheduler ──────────────────────────────────────────────────
    scheduler = BlockingScheduler(timezone=IST)

    exit_h,  exit_m  = parse_hhmm(WEEKLY_EXIT_TIME)   # 15:24
    entry_h, entry_m = parse_hhmm(ENTRY_TIME)          # 15:26

    # 15:24 — exit job (weekly or monthly)
    scheduler.add_job(
        job_15_24,
        CronTrigger(hour=exit_h, minute=exit_m, day_of_week="mon-fri", timezone=IST),
        id="exit_1524",
        name="Exit at 15:24",
        misfire_grace_time=60,
    )

    # 15:26 — entry/roll job
    scheduler.add_job(
        job_15_26,
        CronTrigger(hour=entry_h, minute=entry_m, day_of_week="mon-fri", timezone=IST),
        id="entry_1526",
        name="Enter/Roll at 15:26",
        misfire_grace_time=60,
    )

    # Every 5 min 09:20→15:20 — SL check
    scheduler.add_job(
        job_check_sl,
        CronTrigger(
            minute=f"*/{SL_CANDLE_TF}",
            hour="9-15",
            day_of_week="mon-fri",
            timezone=IST,
        ),
        id="sl_check",
        name=f"SL Check every {SL_CANDLE_TF} min",
        misfire_grace_time=30,
    )

    logger.info("Scheduled jobs:")
    for job in scheduler.get_jobs():
        logger.info(f"  [{job.id}] {job.name}")

    logger.info("Scheduler running — waiting for market events...")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
        scheduler.shutdown()


if __name__ == "__main__":
    main()
