"""
Entry setups from the masterclass: flag breakout, base breakout with HVY
(entry on the ONP pullback), and descending-trend-line (DTL) breakout.

Every signal carries entry / stop / T1 / T2 so the scanner and executor
never have to guess.
"""
from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd

from indicators import dcr, ema, hvy, lvq, pocket_pivot, range_contraction, sma


@dataclass
class Signal:
    symbol: str
    setup: str
    entry: float          # buy-stop / limit level
    stop: float           # initial stop loss
    target1: float        # 2R - book partial / move SL to breakeven
    target2: float        # 3R - or switch to trailing
    risk_per_share: float
    notes: str = ""

    def dict(self):
        return asdict(self)


def _make_signal(symbol, setup, entry, stop, notes=""):
    entry, stop = round(float(entry), 2), round(float(stop), 2)
    r = entry - stop
    if r <= 0:
        return None
    return Signal(symbol, setup, entry, stop,
                  round(entry + 2 * r, 2), round(entry + 3 * r, 2),
                  round(r, 2), notes)


# ---------------- 1. Flag breakout ----------------
def flag_breakout(symbol: str, df: pd.DataFrame,
                  pole_days: int = 15, flag_days: int = 8,
                  min_pole_gain: float = 0.15, max_flag_depth: float = 0.10):
    """
    Sharp advance (pole) then a tight, low-volume drift (flag).
    Entry : buy stop above flag high.
    Stop  : below flag low (capped at 8% by position sizing).
    """
    if len(df) < pole_days + flag_days + 5:
        return None
    flag = df.iloc[-flag_days:]
    pole = df.iloc[-(pole_days + flag_days):-flag_days]
    pole_gain = pole["close"].iloc[-1] / pole["close"].iloc[0] - 1
    flag_depth = 1 - flag["low"].min() / pole["high"].max()
    vol_dry = flag["volume"].mean() < pole["volume"].mean() * 0.7
    if pole_gain >= min_pole_gain and flag_depth <= max_flag_depth and vol_dry:
        return _make_signal(
            symbol, "FLAG_BREAKOUT",
            entry=flag["high"].max() * 1.002,          # small buffer above flag high
            stop=flag["low"].min() * 0.998,
            notes=f"pole +{pole_gain:.0%}, flag depth {flag_depth:.0%}, volume drying up",
        )
    return None


# ---------------- 2. Base breakout (HVY) -> ONP pullback entry ----------------
def base_breakout_pullback(symbol: str, df: pd.DataFrame,
                           base_days: int = 40, max_base_depth: float = 0.20,
                           pullback_days: int = 5):
    """
    Nitin's preferred entry: do NOT chase the O'Neil pivot breakout day.
    Wait for the breakout (ideally on HVY / pocket-pivot volume), then buy
    the pullback toward the pivot with a stop under the pullback low.
    """
    if len(df) < base_days + pullback_days + 10:
        return None
    base = df.iloc[-(base_days + pullback_days):-pullback_days]
    recent = df.iloc[-pullback_days:]
    pivot = base["high"].max()
    depth = 1 - base["low"].min() / pivot
    if depth > max_base_depth:
        return None
    broke_out = base["close"].iloc[-1] > pivot * 0.99 or recent["high"].max() > pivot
    vol_confirm = bool(hvy(df).iloc[-pullback_days:].any() or
                       pocket_pivot(df).iloc[-pullback_days:].any())
    pulling_back = recent["close"].iloc[-1] < recent["high"].max() * 0.99
    near_pivot = recent["close"].iloc[-1] >= pivot * 0.97
    if broke_out and vol_confirm and pulling_back and near_pivot:
        return _make_signal(
            symbol, "BASE_BREAKOUT_ONP_PULLBACK",
            entry=recent["high"].iloc[-1] * 1.002,     # resume above yesterday's high
            stop=min(recent["low"].min(), pivot * 0.97),
            notes=f"pivot {pivot:.2f}, base depth {depth:.0%}, HVY/pocket-pivot volume confirmed",
        )
    return None


# ---------------- 3. Descending trend line breakout ----------------
def dtl_breakout(symbol: str, df: pd.DataFrame, lookback: int = 60):
    """
    Fit a line through descending highs; signal when close crosses above it
    with a DCR close near the top of the day's range.
    """
    if len(df) < lookback + 5:
        return None
    win = df.iloc[-lookback:]
    idx = np.arange(lookback)
    highs = win["high"].to_numpy()
    slope, intercept = np.polyfit(idx, highs, 1)
    if slope >= 0:                          # need a DESCENDING line
        return None
    line_today = slope * (lookback - 1) + intercept
    line_prev = slope * (lookback - 2) + intercept
    c, c_prev = win["close"].iloc[-1], win["close"].iloc[-2]
    strong_close = dcr(df).iloc[-1] >= 0.6
    if c_prev <= line_prev and c > line_today and strong_close:
        return _make_signal(
            symbol, "DTL_BREAKOUT",
            entry=win["high"].iloc[-1] * 1.002,
            stop=win["low"].iloc[-5:].min() * 0.998,   # under recent swing low
            notes=f"closed above descending trendline ({line_today:.2f}), DCR {dcr(df).iloc[-1]:.2f}",
        )
    return None


# ---------------- 4. Tight VCP watch (pre-breakout alert) ----------------
def vcp_watch(symbol: str, df: pd.DataFrame):
    """Volatility contraction + LVQ inside a base: alert BEFORE the breakout."""
    if len(df) < 60:
        return None
    if range_contraction(df) and bool(lvq(df).iloc[-5:].any()):
        pivot = df["high"].iloc[-15:].max()
        return _make_signal(
            symbol, "VCP_WATCH",
            entry=pivot * 1.002,
            stop=df["low"].iloc[-10:].min() * 0.998,
            notes="ranges contracting + LVQ: supply absorbed, watch for breakout",
        )
    return None


ALL_SETUPS = [flag_breakout, base_breakout_pullback, dtl_breakout, vcp_watch]


# ---------------- Exit rules (for open positions) ----------------
def trailing_stop(df: pd.DataFrame, mode: str = "structural") -> float:
    """
    structural : last confirmed swing low (10-day rolling low).
    ma         : 20-EMA 'decisive exit' - exit only on a CLOSE below it.
    """
    if mode == "ma":
        return float(ema(df["close"], 20).iloc[-1])
    return float(df["low"].rolling(10).min().iloc[-1])


def decisive_ma_exit(df: pd.DataFrame, n: int = 20) -> bool:
    """True when price CLOSES below the n-EMA (not just an intraday touch)."""
    return bool(df["close"].iloc[-1] < ema(df["close"], n).iloc[-1])
