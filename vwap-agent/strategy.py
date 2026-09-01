"""VWAP Agent - NIFTY/BankNifty/Sensex ATM CE+PE, session VWAP + SD-band
mean reversion, long only. Signal runs on the OPTION's own OHLCV (not the
underlying index) -- same as 18SMA's option-side confirmation."""
import datetime as dt
import requests
import pandas as pd
import numpy as np
from zoneinfo import ZoneInfo
from config import settings

IST = ZoneInfo(settings.IST)

INSTRUMENTS = [
    {"name": "NIFTY",     "index": settings.NIFTY_INDEX,     "lots": settings.NIFTY_LOTS,     "lot_size": settings.NIFTY_LOT_SIZE},
    {"name": "BANKNIFTY", "index": settings.BANKNIFTY_INDEX, "lots": settings.BANKNIFTY_LOTS, "lot_size": settings.BANKNIFTY_LOT_SIZE},
    {"name": "SENSEX",    "index": settings.SENSEX_INDEX,    "lots": settings.SENSEX_LOTS,    "lot_size": settings.SENSEX_LOT_SIZE},
]

MAX_LOOKBACK_CANDLES = 60


def fetch_candles(fy, symbol, lookback_days=1):
    """Intraday candles at settings.TIMEFRAME resolution, TODAY only (VWAP
    is a session indicator and must never see a prior day's candles)."""
    now = dt.datetime.now(IST)
    start = now - dt.timedelta(days=lookback_days)
    data = {
        "symbol": symbol,
        "resolution": str(settings.TIMEFRAME),
        "date_format": "1",
        "range_from": start.strftime("%Y-%m-%d"),
        "range_to": now.strftime("%Y-%m-%d"),
        "cont_flag": "1",
    }
    r = fy.history(data=data)
    if r.get("s") != "ok" or not r.get("candles"):
        return None
    df = pd.DataFrame(r["candles"], columns=["ts", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="s").dt.tz_localize("UTC").dt.tz_convert(IST)
    df = df.set_index("date").sort_index()
    today = dt.datetime.now(IST).date()
    return df[df.index.date == today]


def calculate_vwap_bands(df):
    """Session VWAP + 1SD/2SD bands, computed cumulatively from the day's
    first candle. Resets every session because fetch_candles already filters
    to today only."""
    df = df.copy()
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, 1)
    cum_vol = vol.cumsum()
    vwap = (tp * vol).cumsum() / cum_vol
    variance = ((tp - vwap) ** 2 * vol).cumsum() / cum_vol
    sd = np.sqrt(variance)
    df["vwap"] = vwap
    df["sd"] = sd
    df["upper1"] = vwap + sd
    df["lower1"] = vwap - sd
    df["upper2"] = vwap + 2 * sd
    df["lower2"] = vwap - 2 * sd
    return df


def check_vwap_signal(df, max_lookback=MAX_LOOKBACK_CANDLES):
    """One trade per below-VWAP excursion (mirrors 18SMA's regime-based
    dedup). An excursion is a contiguous run of closed candles with
    close < vwap. Fires when, within the most recent excursion, price has
    touched lower1 (-1SD) and the latest closed candle has reclaimed back
    above lower1 with a bullish body (close>open).
    Returns (signal_id, trig_candle) or (None, None).
    """
    b = calculate_vwap_bands(df).dropna(subset=["vwap", "sd"])
    n = len(b)
    if n < 3:
        return None, None
    lo = max(1, n - max_lookback)
    below = b["close"] < b["vwap"]
    regime_start = None
    for i in range(n - 1, lo, -1):
        if below.iloc[i] != below.iloc[i - 1]:
            regime_start = i
            break
    if regime_start is None or not below.iloc[regime_start]:
        return None, None
    excursion = b.iloc[regime_start:]
    if len(excursion) < 1:
        return None, None
    touched = bool((excursion["low"] <= excursion["lower1"]).any())
    if not touched:
        return None, None
    trig = excursion.iloc[-1]
    if not (trig["close"] > trig["lower1"] and trig["close"] > trig["open"]):
        return None, None
    sig_time = b.index[regime_start]
    signal_id = f"vwap-excursion-{sig_time.isoformat()}"
    return signal_id, trig


def fetch_atm_option(client_id, token, index_symbol):
    """Fyers option-chain-v3 (strikecount=1 -> ATM only). Returns dict CE/PE rows + expiry."""
    url = "https://api-t1.fyers.in/data/options-chain-v3"
    headers = {"Authorization": f"{client_id}:{token}"}
    params = {"symbol": index_symbol, "strikecount": 1}
    resp = requests.get(url, headers=headers, params=params, timeout=10)
    j = resp.json()
    if j.get("s") != "ok":
        return None
    data = j.get("data", {})
    chain = data.get("optionsChain", [])
    expiry_list = data.get("expiryData", [])
    expiry = expiry_list[0]["date"] if expiry_list else ""
    out = {}
    for row in chain:
        ot = row.get("option_type")
        if ot in ("CE", "PE"):
            out[ot] = row
    if "CE" not in out or "PE" not in out:
        return None
    out["expiry"] = expiry
    return out
