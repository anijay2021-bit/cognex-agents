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

def fetch_candles(fy, symbol, lookback_days=5):
    """Intraday candles at settings.TIMEFRAME resolution (same TF drives SMA and breakout)."""
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

def check_breakout(df):
    """Returns 'CE', 'PE', or None.
    Rule: last 2 completed candles (c1,c2) both close on the same side of the 18-SMA
    and are both same-colour candles; c3 (latest completed) must break their high/low.
    """
    if df is None or len(df) < settings.SMA_PERIOD + 5:
        return None
    df = df.copy()
    df["sma18"] = df["close"].rolling(settings.SMA_PERIOD).mean()
    c1, c2, c3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    if pd.isna(c1["sma18"]) or pd.isna(c2["sma18"]):
        return None

    bull = (c1["close"] > c1["sma18"] and c2["close"] > c2["sma18"]
            and c1["close"] > c1["open"] and c2["close"] > c2["open"])
    if bull and c3["high"] > max(c1["high"], c2["high"]):
        return "CE"

    bear = (c1["close"] < c1["sma18"] and c2["close"] < c2["sma18"]
            and c1["close"] < c1["open"] and c2["close"] < c2["open"])
    if bear and c3["low"] < min(c1["low"], c2["low"]):
        return "PE"
    return None

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
