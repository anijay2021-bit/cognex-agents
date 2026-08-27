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
    """One trade per SMA-crossover regime. Returns (side, signal_id, cross_time, trig_time)
    or (None, None, None, None). cross_time/trig_time are the timestamps of the
    two reference candles so the option's own price can be checked at the same
    two candles (see check_option_confirmation).
    """
    df = df.copy()
    df["sma18"] = df["close"].rolling(settings.SMA_PERIOD).mean()
    cur = df.iloc[-1]
    n = len(df)
    lo = max(1, n - 1 - max_lookback)
    closed = df.iloc[lo:n - 1].dropna(subset=["sma18"])
    if len(closed) < 2:
        return None, None, None, None
    above = closed["close"] > closed["sma18"]
    cross_pos = None
    for i in range(len(closed) - 1, 0, -1):
        if above.iloc[i] != above.iloc[i - 1]:
            cross_pos = i
            break
    if cross_pos is None:
        return None, None, None, None
    cross_candle = closed.iloc[cross_pos]
    if cross_pos + 1 >= len(closed):
        return None, None, None, None
    trig_candle = closed.iloc[cross_pos + 1]
    cross_time = closed.index[cross_pos]
    trig_time = closed.index[cross_pos + 1]
    bull = bool(above.iloc[cross_pos])
    signal_id = f"{'CE' if bull else 'PE'}-cross-{cross_time.isoformat()}"
    if bull:
        trig_high = max(cross_candle["high"], trig_candle["high"])
        if cur["high"] > trig_high:
            return "CE", signal_id, cross_time, trig_time
    else:
        trig_low = min(cross_candle["low"], trig_candle["low"])
        if cur["low"] < trig_low:
            return "PE", signal_id, cross_time, trig_time
    return None, None, None, None


def check_option_confirmation(df_opt, cross_time, trig_time, side):
    """Mirror the spot breakout test on the option's own price. At the SAME two
    candle timestamps as the spot signal, has the option premium ALSO cleared
    its own 2-candle extreme in the same direction? Returns True/False.
    """
    if df_opt is None or len(df_opt) < 2:
        return False
    cur = df_opt.iloc[-1]
    closed = df_opt.iloc[:-1]
    if cross_time not in closed.index or trig_time not in closed.index:
        return False
    c1 = closed.loc[cross_time]
    c2 = closed.loc[trig_time]
    if side == "CE":
        trig_high = max(c1["high"], c2["high"])
        return bool(cur["high"] > trig_high)
    else:
        trig_low = min(c1["low"], c2["low"])
        return bool(cur["low"] < trig_low)


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
