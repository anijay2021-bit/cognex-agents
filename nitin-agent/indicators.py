"""
Indicators from the Nitin R / Ankur Patel swing-trading masterclass.

Expects a pandas DataFrame with columns: open, high, low, close, volume
indexed by date (ascending).
"""
import numpy as np
import pandas as pd


# ---------- basics ----------
def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


# ---------- Daily Closing Range: (Close - Low) / (High - Low) ----------
def dcr(df: pd.DataFrame) -> pd.Series:
    rng = (df["high"] - df["low"]).replace(0, np.nan)
    return ((df["close"] - df["low"]) / rng).fillna(0.5)


# ---------- Volume events ----------
def hvy(df: pd.DataFrame, lookback: int = 252) -> pd.Series:
    """Highest Volume in a Year: today's volume is the max of the last year."""
    return df["volume"] >= df["volume"].rolling(lookback, min_periods=60).max()


def lvq(df: pd.DataFrame, lookback: int = 63) -> pd.Series:
    """Lowest Volume in a Quarter: today's volume is the min of the last quarter."""
    return df["volume"] <= df["volume"].rolling(lookback, min_periods=30).min()


def pocket_pivot(df: pd.DataFrame, lookback: int = 10) -> pd.Series:
    """Up-day volume greater than the highest down-day volume of the last N days."""
    down_vol = df["volume"].where(df["close"] < df["close"].shift(1))
    max_down = down_vol.rolling(lookback, min_periods=5).max()
    up_day = df["close"] > df["close"].shift(1)
    return up_day & (df["volume"] > max_down)


# ---------- Turnover (liquidity) ----------
def avg_turnover_cr(df: pd.DataFrame, n: int = 20) -> float:
    """Average daily turnover in INR crore."""
    t = (df["close"] * df["volume"]).rolling(n).mean()
    return float(t.iloc[-1] / 1e7) if len(t) else 0.0


# ---------- Stage analysis (Weinstein): 10-wk MA > 40-wk MA, both rising ----------
def is_stage2(df: pd.DataFrame) -> bool:
    if len(df) < 210:
        return False
    ma50 = sma(df["close"], 50)    # ~10-week
    ma200 = sma(df["close"], 200)  # ~40-week
    c = df["close"].iloc[-1]
    return bool(
        ma50.iloc[-1] > ma200.iloc[-1]
        and ma50.iloc[-1] > ma50.iloc[-21]
        and ma200.iloc[-1] >= ma200.iloc[-21]
        and c > ma50.iloc[-1]
    )


# ---------- Relative strength vs benchmark ----------
def relative_strength(df: pd.DataFrame, bench: pd.DataFrame, n: int = 63) -> float:
    """Stock return minus benchmark return over n days (0.05 = outperformed by 5%)."""
    if len(df) < n + 1 or len(bench) < n + 1:
        return 0.0
    r_s = df["close"].iloc[-1] / df["close"].iloc[-n - 1] - 1
    r_b = bench["close"].iloc[-1] / bench["close"].iloc[-n - 1] - 1
    return float(r_s - r_b)


# ---------- Volatility contraction (VCP-style tightness) ----------
def range_contraction(df: pd.DataFrame, w: int = 5, n_windows: int = 3) -> bool:
    """True if successive w-day high-low ranges are shrinking (supply absorption)."""
    if len(df) < w * n_windows:
        return False
    ranges = []
    for i in range(n_windows):
        seg = df.iloc[-(i + 1) * w: len(df) - i * w]
        ranges.append((seg["high"].max() - seg["low"].min()) / seg["close"].iloc[-1])
    # ranges[0] is the most recent window; each older window should be larger
    return all(ranges[i] < ranges[i + 1] for i in range(n_windows - 1))


# ---------- Market breadth (computed across the whole universe) ----------
def breadth_quadrant(universe: dict[str, pd.DataFrame]) -> dict:
    """
    % of stocks above 20-DMA (short) and 200-DMA (long).
    Easy money  : both high (>60%)   -> trade aggressively
    Hard money  : long high, short low -> pullback phase, be selective
    No money    : both low (<40%)    -> sit out / tiny size
    """
    above20 = above200 = total = 0
    for df in universe.values():
        if len(df) < 200:
            continue
        total += 1
        c = df["close"].iloc[-1]
        if c > sma(df["close"], 20).iloc[-1]:
            above20 += 1
        if c > sma(df["close"], 200).iloc[-1]:
            above200 += 1
    if total == 0:
        return {"pct_above_20": 0, "pct_above_200": 0, "phase": "unknown"}
    p20, p200 = 100 * above20 / total, 100 * above200 / total
    if p200 > 60 and p20 > 60:
        phase = "easy_money"
    elif p200 > 60:
        phase = "hard_money"
    elif p200 < 40 and p20 < 40:
        phase = "no_money"
    else:
        phase = "transition"
    return {"pct_above_20": round(p20, 1), "pct_above_200": round(p200, 1), "phase": phase}


def net_new_highs(universe: dict[str, pd.DataFrame], lookback: int = 63) -> int:
    """(# stocks at N-day high) - (# stocks at N-day low) today."""
    nh = nl = 0
    for df in universe.values():
        if len(df) < lookback:
            continue
        c = df["close"].iloc[-1]
        if c >= df["high"].iloc[-lookback:].max():
            nh += 1
        if c <= df["low"].iloc[-lookback:].min():
            nl += 1
    return nh - nl
