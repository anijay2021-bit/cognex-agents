"""
options_selector.py
-------------------
Finds the ATM strike for Nifty and builds Fyers-compatible option symbols
for both the nearest weekly expiry and the next monthly expiry.

Nifty expiry day: TUESDAY (changed from Thursday)
Holiday rule: if Tuesday is an NSE holiday, expiry shifts to Monday.

Used by: calendar_spread_strategy.py
"""

import datetime
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

NIFTY_STRIKE_STEP = 50
NIFTY_LOT_SIZE    = 25
NIFTY_FNO_SYMBOL  = "NSE:NIFTY50-INDEX"

# NSE trading holidays — sourced from official NSE circulars.
# Source 2026: NSE/CMTR/71775 dated December 12, 2025
# If a Tuesday expiry falls on any of these dates, it shifts to Monday.
NSE_HOLIDAYS = {
    # ── 2025 ───────────────────────────────────────────────────────────────
    datetime.date(2025,  1, 14),  # Makar Sankranti / Pongal
    datetime.date(2025,  2, 26),  # Mahashivratri
    datetime.date(2025,  3, 14),  # Holi
    datetime.date(2025,  3, 31),  # Id-Ul-Fitr (Ramadan Eid)
    datetime.date(2025,  4, 10),  # Shri Ram Navami
    datetime.date(2025,  4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    datetime.date(2025,  4, 18),  # Good Friday
    datetime.date(2025,  5,  1),  # Maharashtra Day
    datetime.date(2025,  8, 15),  # Independence Day
    datetime.date(2025,  8, 27),  # Ganesh Chaturthi
    datetime.date(2025, 10,  2),  # Mahatma Gandhi Jayanti
    datetime.date(2025, 10, 24),  # Dussehra
    datetime.date(2025, 11,  5),  # Diwali Laxmi Pujan
    datetime.date(2025, 11,  6),  # Diwali-Balipratipada
    datetime.date(2025, 11, 24),  # Prakash Gurpurb Sri Guru Nanak Dev
    datetime.date(2025, 12, 25),  # Christmas
    # ── 2026 — NSE/CMTR/71775 official circular (Dec 12, 2025) ────────────
    datetime.date(2026,  1, 26),  # Republic Day
    datetime.date(2026,  3,  3),  # Holi
    datetime.date(2026,  3, 26),  # Shri Ram Navami
    datetime.date(2026,  3, 31),  # Shri Mahavir Jayanti  ← today's expiry shifted to Mar 30
    datetime.date(2026,  4,  3),  # Good Friday
    datetime.date(2026,  4, 14),  # Dr. Baba Saheb Ambedkar Jayanti
    datetime.date(2026,  5,  1),  # Maharashtra Day
    datetime.date(2026,  5, 28),  # Bakri Id
    datetime.date(2026,  6, 26),  # Muharram
    datetime.date(2026,  9, 14),  # Ganesh Chaturthi
    datetime.date(2026, 10,  2),  # Mahatma Gandhi Jayanti
    datetime.date(2026, 10, 20),  # Dussehra
    datetime.date(2026, 11, 10),  # Diwali-Balipratipada
    datetime.date(2026, 11, 24),  # Prakash Gurpurb Sri Guru Nanak Dev
    datetime.date(2026, 12, 25),  # Christmas
}


# ─────────────────────────────────────────────
# HOLIDAY ADJUSTMENT
# ─────────────────────────────────────────────

def adjust_for_holiday(expiry: datetime.date) -> datetime.date:
    """
    If expiry falls on an NSE holiday or weekend, shift backwards
    to the nearest valid trading day (typically Monday).

    Args:
        expiry: calculated expiry date (usually a Tuesday)

    Returns:
        datetime.date: adjusted expiry date
    """
    while expiry in NSE_HOLIDAYS or expiry.weekday() in (5, 6):  # Sat=5, Sun=6
        expiry -= datetime.timedelta(days=1)
    return expiry


# ─────────────────────────────────────────────
# ATM STRIKE
# ─────────────────────────────────────────────

def get_nifty_spot(fyers) -> float:
    """
    Fetch current Nifty spot price from Fyers.

    Args:
        fyers: authenticated Fyers API client instance

    Returns:
        float: current spot price
    """
    data = {"symbols": NIFTY_FNO_SYMBOL}
    response = fyers.quotes(data)

    if response.get("code") != 200:
        raise RuntimeError(f"Failed to fetch Nifty spot: {response}")

    ltp = response["d"][0]["v"]["lp"]
    logger.info(f"Nifty spot LTP: {ltp}")
    return float(ltp)


def get_atm_strike(spot_price: float, step: int = NIFTY_STRIKE_STEP) -> int:
    """
    Round spot price to nearest strike step to get ATM strike.

    Example: spot=22347 → ATM=22350

    Args:
        spot_price: current Nifty spot price
        step: strike interval (default 50 for Nifty)

    Returns:
        int: ATM strike price
    """
    atm = round(spot_price / step) * step
    logger.info(f"Spot: {spot_price} → ATM Strike: {atm}")
    return int(atm)


# ─────────────────────────────────────────────
# EXPIRY DATE FINDERS  (Tuesday-based)
# ─────────────────────────────────────────────

def get_nearest_weekly_expiry(from_date: Optional[datetime.date] = None) -> datetime.date:
    """
    Returns the nearest upcoming Tuesday (Nifty weekly expiry),
    adjusted for NSE holidays (shifts to Monday if Tuesday is holiday).

    NOTE: always returns the NEXT Tuesday from from_date,
    even if from_date is itself a Tuesday (to avoid same-day issues at entry).

    Args:
        from_date: date to calculate from (defaults to today IST)

    Returns:
        datetime.date: nearest weekly expiry (adjusted)
    """
    if from_date is None:
        from_date = _today_ist()

    # Tuesday = weekday 1
    days_until_tuesday = (1 - from_date.weekday()) % 7
    if days_until_tuesday == 0:
        days_until_tuesday = 7   # if today is Tuesday, get next Tuesday

    raw_expiry = from_date + datetime.timedelta(days=days_until_tuesday)
    expiry = adjust_for_holiday(raw_expiry)

    logger.info(f"Nearest weekly expiry: {expiry} (raw Tuesday: {raw_expiry})")
    return expiry


def get_next_monthly_expiry(from_date: Optional[datetime.date] = None) -> datetime.date:
    """
    Returns the last Tuesday of the current month (Nifty monthly expiry),
    adjusted for NSE holidays.
    If that date has already passed, returns last Tuesday of next month.

    Args:
        from_date: date to calculate from (defaults to today IST)

    Returns:
        datetime.date: next monthly expiry date (adjusted)
    """
    if from_date is None:
        from_date = _today_ist()

    raw_expiry = _last_tuesday_of_month(from_date.year, from_date.month)
    expiry = adjust_for_holiday(raw_expiry)

    # If this month's expiry already passed, move to next month
    if expiry <= from_date:
        year  = from_date.year + (1 if from_date.month == 12 else 0)
        month = 1 if from_date.month == 12 else from_date.month + 1
        raw_expiry = _last_tuesday_of_month(year, month)
        expiry = adjust_for_holiday(raw_expiry)

    logger.info(f"Next monthly expiry: {expiry} (raw last Tuesday: {raw_expiry})")
    return expiry


def _last_tuesday_of_month(year: int, month: int) -> datetime.date:
    """Find the last Tuesday of a given month (before holiday adjustment)."""
    if month == 12:
        last_day = datetime.date(year + 1, 1, 1) - datetime.timedelta(days=1)
    else:
        last_day = datetime.date(year, month + 1, 1) - datetime.timedelta(days=1)

    days_back = (last_day.weekday() - 1) % 7    # 1 = Tuesday
    return last_day - datetime.timedelta(days=days_back)


def _today_ist() -> datetime.date:
    """Return today's date in IST (UTC+5:30)."""
    ist_offset = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
    return datetime.datetime.now(ist_offset).date()


# ─────────────────────────────────────────────
# FYERS SYMBOL BUILDER
# ─────────────────────────────────────────────

def build_fyers_option_symbol(
    expiry_date: datetime.date,
    strike: int,
    option_type: str          # "CE" or "PE"
) -> str:
    """
    Build a Fyers-compatible option symbol string.

    Monthly format : NSE:NIFTY{YY}{MON}{STRIKE}{TYPE}
                     e.g. NSE:NIFTY26APR22350CE

    Weekly format  : NSE:NIFTY{YY}{M_CODE}{DD}{STRIKE}{TYPE}
                     e.g. NSE:NIFTY2640122350CE  (Apr 1 weekly)

    Auto-detects monthly vs weekly by comparing against last Tuesday of month
    (after holiday adjustment).

    Args:
        expiry_date: expiry date of the contract (holiday-adjusted)
        strike: strike price (e.g. 22350)
        option_type: "CE" or "PE"

    Returns:
        str: Fyers symbol string
    """
    option_type = option_type.upper()
    assert option_type in ("CE", "PE"), "option_type must be CE or PE"

    yy    = expiry_date.strftime("%y")
    month = expiry_date.month
    dd    = expiry_date.strftime("%d")

    # Determine monthly vs weekly
    last_tue     = _last_tuesday_of_month(expiry_date.year, expiry_date.month)
    adjusted_tue = adjust_for_holiday(last_tue)
    is_monthly   = (expiry_date == adjusted_tue)

    if is_monthly:
        mon_str = expiry_date.strftime("%b").upper()   # e.g. "APR"
        symbol  = f"NSE:NIFTY{yy}{mon_str}{strike}{option_type}"
    else:
        # Weekly month codes: Oct=O, Nov=N, Dec=D, rest are digits
        weekly_month_codes = {
            1: "1", 2: "2", 3: "3", 4: "4", 5: "5",
            6: "6", 7: "7", 8: "8", 9: "9",
            10: "O", 11: "N", 12: "D"
        }
        m_code = weekly_month_codes[month]
        symbol = f"NSE:NIFTY{yy}{m_code}{dd}{strike}{option_type}"

    logger.info(f"Built symbol: {symbol} (monthly={is_monthly})")
    return symbol


# ─────────────────────────────────────────────
# CONVENIENCE: BUILD FULL STRADDLE PAIR
# ─────────────────────────────────────────────

def get_straddle_symbols(expiry_date: datetime.date, strike: int) -> dict:
    """
    Returns CE and PE symbols for a straddle at a given strike + expiry.

    Returns:
        dict: {"CE": symbol_str, "PE": symbol_str}
    """
    return {
        "CE": build_fyers_option_symbol(expiry_date, strike, "CE"),
        "PE": build_fyers_option_symbol(expiry_date, strike, "PE"),
    }


# ─────────────────────────────────────────────
# MAIN SELECTOR: CALLED AT STRATEGY ENTRY TIME
# ─────────────────────────────────────────────

def select_calendar_legs(fyers) -> dict:
    """
    Master function called at first entry time.
    Returns everything the strategy needs to place its 4 legs.

    Returns:
        {
            "atm_strike"    : int,
            "spot_at_entry" : float,
            "weekly_expiry" : str (ISO date),
            "monthly_expiry": str (ISO date),
            "buy_legs"      : {"CE": symbol, "PE": symbol},   # next monthly
            "sell_legs"     : {"CE": symbol, "PE": symbol},   # nearest weekly
            "lot_size"      : int,
        }
    """
    spot           = get_nifty_spot(fyers)
    atm            = get_atm_strike(spot)
    weekly_expiry  = get_nearest_weekly_expiry()
    monthly_expiry = get_next_monthly_expiry()

    buy_legs  = get_straddle_symbols(monthly_expiry, atm)
    sell_legs = get_straddle_symbols(weekly_expiry,  atm)

    result = {
        "atm_strike":     atm,
        "spot_at_entry":  spot,
        "weekly_expiry":  weekly_expiry.isoformat(),
        "monthly_expiry": monthly_expiry.isoformat(),
        "buy_legs":       buy_legs,
        "sell_legs":      sell_legs,
        "lot_size":       NIFTY_LOT_SIZE,
    }

    logger.info(f"Calendar legs selected: {result}")
    return result


# ─────────────────────────────────────────────
# QUICK TEST (run directly: python options_selector.py)
# ─────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== ATM Rounding ===")
    for spot in [22347, 22375, 22301, 22450, 22225]:
        print(f"  Spot {spot} → ATM {get_atm_strike(spot)}")

    print("\n=== Expiry Dates from Today ===")
    today = _today_ist()
    w = get_nearest_weekly_expiry(today)
    m = get_next_monthly_expiry(today)
    print(f"  Today          : {today} ({today.strftime('%A')})")
    print(f"  Weekly expiry  : {w} ({w.strftime('%A')})")
    print(f"  Monthly expiry : {m} ({m.strftime('%A')})")

    print("\n=== Holiday Shift Test ===")
    test_dates = [
        datetime.date(2026,  3, 30),  # Monday → weekly is Tue Mar 31
        datetime.date(2026,  4,  1),  # Wednesday → weekly is Tue Apr 7
        datetime.date(2026,  4,  7),  # Tuesday itself → get next Tuesday Apr 14
        datetime.date(2026,  4, 14),  # Apr 14 is holiday → should shift
        datetime.date(2026,  4, 28),  # Monthly April
    ]
    for d in test_dates:
        wk = get_nearest_weekly_expiry(d)
        mo = get_next_monthly_expiry(d)
        print(f"  From {d} ({d.strftime('%a')}) → weekly: {wk} ({wk.strftime('%a')}), monthly: {mo} ({mo.strftime('%a')})")

    print("\n=== Fyers Symbols ===")
    strike = 22350
    weekly  = get_nearest_weekly_expiry(today)
    monthly = get_next_monthly_expiry(today)
    for exp, label in [(weekly, "Weekly"), (monthly, "Monthly")]:
        for otype in ["CE", "PE"]:
            sym = build_fyers_option_symbol(exp, strike, otype)
            print(f"  {label} {otype}: {sym}")
