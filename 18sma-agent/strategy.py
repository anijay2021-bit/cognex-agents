"""18-SMA + 2-candle breakout scanner. ATM CE/PE via Fyers option chain v3."""
import datetime as dt
import requests
import pandas as pd
from zoneinfo import ZoneInfo
from config import settings

IST = ZoneInfo(settings.IST)

INSTRUMENTS = [
    {"name": "NIFTY",     "index": settings.NIFTY_INDEX,     "lots": settings.NIFTY_LOTS,     "lot_size": settings.NIFTY_LOT_SIZE},
    {"name": "BANKNIFTY", "index": settings.BANKNIFTY_INDEX, "lots": settings.BANKNIFTY_LOTS, "lot_size": settings.BANKNIFTY_LOT_SIZE},
    {"name": "SENSEX",    "index": settings.SENSEX_INDEX,    "lots": settings.SENSEX_LOTS,    "lot_size": settings.SENSEX_LOT_SIZE},
]

# How many completed candles back we're willing to search for the most recent
# qualifying 2-candle setup. Bounds the scan to roughly the current trading day
# (30min TF => ~13 candles/day) with headroom, so a stale multi-day-old setup
# can never fire.
MAX_LOOKBACK_CANDLES = 20


def fetch_candles(fy, symbol, lookback_days=5):
    """Intraday candles at settings.TIMEFRAME resolution (same TF drives SMA and candles)."""
    now = dt.datetime.now(IST)
    start = now - dt.timedelta(days=lookback_days)
    data = {
        "symbol": symbol,
        "resolution": str(settings.TIMEFRAME),
        "date_format": "1",
        "range_from": start.strftime("%Y-%m-%d"),
        "range_to":   now.strftime("%Y-%m-%d"),
        "cont_flag": "1",
    }
    r = fy.history(data=data)
    if r.get("s") != "ok" or not r.get("candles"):
        return None
    df = pd.DataFrame(r["candles"], columns=["ts", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="s")
    return df.set_index("date").sort_index()


def check_breakout(df, max_lookback=MAX_LOOKBACK_CANDLES):
    """Returns (side, signal_id) where side is 'CE', 'PE', or None.

    Setup: the most recent 2 consecutive *completed* candles (p1, p2) that are
    both same-colour and both close on the same side of the 18-SMA (e.g. the
    "2nd red candle below the 18-SMA"). That setup stays armed -- irrespective
    of how many further candles (3rd, 4th, 5th, ...) pass -- until either:
      * the current price crosses p2's high (bull) / p1&p2's combined low (bear)
        -> a signal fires, or
      * a fresher qualifying pair forms later, which supersedes it.

    signal_id uniquely identifies the (p1, p2) pair so the caller can enforce
    "one trade per signal per instrument" even across restarts (it's checked
    against the trades DB, not just in-memory state).
    """
    if df is None or len(df) < settings.SMA_PERIOD + 3:
        return None, None
    df = df.copy()
    df["sma18"] = df["close"].rolling(settings.SMA_PERIOD).mean()

    cur = df.iloc[-1]  # current / still-forming candle -- live price we test against
    n = len(df)
    lo = max(1, n - 1 - max_lookback)

    for i in range(n - 2, lo - 1, -1):
        p1, p2 = df.iloc[i - 1], df.iloc[i]
        if pd.isna(p1["sma18"]) or pd.isna(p2["sma18"]):
            break  # ran out of valid SMA history within the lookback window

        bull = (p1["close"] > p1["sma18"] and p2["close"] > p2["sma18"]
                and p1["close"] > p1["open"] and p2["close"] > p2["open"])
        if bull:
            sig = f"CE-{df.index[i-1].isoformat()}-{df.index[i].isoformat()}"
            if cur["high"] > max(p1["high"], p2["high"]):
                return "CE", sig
            return None, None  # setup found but not yet broken -- keep watching it

        bear = (p1["close"] < p1["sma18"] and p2["close"] < p2["sma18"]
                and p1["close"] < p1["open"] and p2["close"] < p2["open"])
        if bear:
            sig = f"PE-{df.index[i-1].isoformat()}-{df.index[i].isoformat()}"
            if cur["low"] < min(p1["low"], p2["low"]):
                return "PE", sig
            return None, None  # setup found but not yet broken -- keep watching it

    return None, None  # no qualifying pair found within the lookback window


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
