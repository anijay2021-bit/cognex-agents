"""18SMA Agent - Nifty/BankNifty/Sensex, 18-SMA + 2-candle breakout, ATM CE/PE, PAPER mode."""
import datetime as dt, json, time, requests
from zoneinfo import ZoneInfo
from fyers_apiv3 import fyersModel

import store
from config import settings
import sys, os
from strategy import INSTRUMENTS, fetch_candles, check_breakout, check_option_confirmation, fetch_atm_option
sys.path.insert(0, os.path.expanduser("~/cognex-shared"))
import fyers_guard as guard
from fyers_ws import LivePrices
import strategy as _strategy

SCAN_SEC = getattr(settings, "ENTRY_SCAN_SEC", 60)
MONITOR_SEC = getattr(settings, "MONITOR_EVERY_SEC", 3)
_LIVE = None
_LAST_REST = [0.0]
_EOD_WARNED = set()


def rest_quotes(client_id, token, symbols, kind):
    out = {}
    url = "https://api-t1.fyers.in/data/quotes"
    headers = {"Authorization": f"{client_id}:{token}"}
    for i in range(0, len(symbols), 50):
        chunk = symbols[i:i + 50]
        for att in range(3):
            if not guard.acquire(kind, telegram):
                return out
            try:
                r = requests.get(url, headers=headers, params={"symbols": ",".join(chunk)}, timeout=10)
                j = r.json()
            except Exception as e:
                log(f"Quote error: {e}")
                time.sleep(1)
                continue
            if j.get("s") == "ok":
                for d in j.get("d", []):
                    v = d.get("v", {})
                    if "lp" in v:
                        out[d["n"]] = v["lp"]
                break
            log(f"Quote not ok (try {att + 1}): {j.get('code')} {str(j.get('message'))[:60]}")
            if "day" in str(j.get("message")):
                return out
            time.sleep(1.2)
    return out


def get_prices(client_id, token, symbols, kind):
    """WebSocket prices first; budgeted REST only for symbols with no live price."""
    global _LIVE
    if _LIVE is None:
        _LIVE = LivePrices(client_id, lambda: json.load(open(settings.FYERS_TOKEN_PATH))["token"], log)
    prices, stale = {}, []
    try:
        _LIVE.sync(symbols)
    except Exception as e:
        log(f"WS sync error: {e}")
    for s in symbols:
        p = _LIVE.get(s)
        if p is None:
            stale.append(s)
        else:
            prices[s] = p
    if stale and time.time() - _LAST_REST[0] >= 15:
        _LAST_REST[0] = time.time()
        prices.update(rest_quotes(client_id, token, stale, kind))
    return prices



IST = ZoneInfo(settings.IST)


def log(msg):
    print(f"[{dt.datetime.now(IST).strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def telegram(msg):
    try:
        cfg = json.load(open(settings.TELEGRAM_CONFIG))
        requests.post(
            f"https://api.telegram.org/bot{cfg['bot_token']}/sendMessage",
            json={"chat_id": cfg["chat_id"], "text": msg}, timeout=10)
    except Exception as e:
        log(f"Telegram error: {e}")


def fyers():
    token = json.load(open(settings.FYERS_TOKEN_PATH))["token"]
    return fyersModel.FyersModel(token=token, is_async=False,
                                  client_id=settings.FYERS_CLIENT_ID, log_path="")


def in_market_hours():
    now = dt.datetime.now(IST).strftime("%H:%M")
    return settings.MARKET_OPEN <= now <= settings.MARKET_CLOSE


def sl_price(entry):
    if settings.SL_MODE == "PERCENT":
        return round(entry * (1 - settings.SL_VALUE / 100), 2)
    return round(entry - settings.SL_VALUE, 2)


def _risk_points(entry):
    if settings.SL_MODE == "PERCENT":
        return entry * settings.SL_VALUE / 100
    return settings.SL_VALUE


def target_price(entry):
    if settings.TARGET_MODE == "RR":
        return round(entry + _risk_points(entry) * settings.TARGET_VALUE, 2)
    if settings.TARGET_MODE == "POINTS":
        return round(entry + settings.TARGET_VALUE, 2)
    return round(entry * (1 + settings.TARGET_VALUE / 100), 2)


def try_entry(inst, fy, token):
    if store.n_open(inst["name"]) > 0:
        return
    df = fetch_candles(fy, inst["index"])
    side, signal_id, cross_time, trig_time = check_breakout(df)
    if not side:
        return
    if store.signal_traded(inst["name"], signal_id):
        return  # already traded this exact 2-candle setup once -- one signal, one trade
    chain = fetch_atm_option(settings.FYERS_CLIENT_ID, token, inst["index"])
    if not chain:
        log(f"{inst['name']}: {side} breakout but option chain fetch failed")
        return
    leg = chain[side]
    entry = leg["ltp"]
    if not entry:
        return
    df_opt = fetch_candles(fy, leg["symbol"])
    if not check_option_confirmation(df_opt, cross_time, trig_time, side):
        log(f"{inst['name']}: spot {side} breakout confirmed but option {leg['symbol']} "
            f"hasn't broken its own 2-candle level yet -- waiting (signal {signal_id})")
        return
    chain = fetch_atm_option(settings.FYERS_CLIENT_ID, token, inst["index"], force=True)
    if not chain or chain[side]["symbol"] != leg["symbol"]:
        return
    leg = chain[side]
    entry = leg["ltp"]
    if not entry:
        return
    qty = inst["lots"] * inst["lot_size"]
    sl = sl_price(entry)
    tgt = target_price(entry)
    reason = (f"18SMA {side} breakout: {inst['name']} price crossed the "
              f"{'high' if side == 'CE' else 'low'} of the 2-candle setup "
              f"(signal {signal_id}), {settings.TIMEFRAME}min TF. "
              f"Entry {entry} SL {sl} Target {tgt}.")
    store.open_trade(
        order_id=f"18SMA-PAPER-{inst['name']}-{int(time.time())}",
        symbol=leg["symbol"], underlying=inst["name"], strike=leg.get("strike_price", 0),
        expiry=chain["expiry"], direction="BUY", qty=qty,
        entry_price=entry, entry_time=dt.datetime.now(IST).isoformat(),
        sl_price=sl, reason=reason, signal_id=signal_id)
    log(f"ENTRY {inst['name']} {side} {leg['symbol']} @ {entry} qty {qty} signal={signal_id}")
    telegram(
        f"18SMA Signal\nAction: TRADE\nSymbol: {leg['symbol']}\nDirection: BUY\n"
        f"Entry: {entry}  SL: {sl}  Target: {tgt}\nQty: {qty}\n{reason}")


def monitor_exits(client_id, token):
    opens = store.open_trades()
    if not opens:
        return
    symbols = list(dict.fromkeys(t["symbol"] for t in opens))
    prices = get_prices(client_id, token, symbols, "exit")
    for t in opens:
        ltp = prices.get(t["symbol"])
        if ltp is None:
            continue
        sl = sl_price(t["entry_price"])
        tgt = target_price(t["entry_price"])
        if ltp <= sl:
            pnl = store.close_trade(t["id"], ltp, dt.datetime.now(IST).isoformat(), "SL HIT")
            log(f"EXIT SL {t['symbol']} @ {ltp} pnl {pnl}")
            telegram(f"18SMA EXIT (SL): {t['symbol']} @ {ltp} pnl Rs.{pnl}")
        elif ltp >= tgt:
            pnl = store.close_trade(t["id"], ltp, dt.datetime.now(IST).isoformat(), "TARGET HIT")
            log(f"EXIT TARGET {t['symbol']} @ {ltp} pnl {pnl}")
            telegram(f"18SMA EXIT (Target): {t['symbol']} @ {ltp} pnl Rs.{pnl}")


def eod_squareoff(client_id, token):
    """Force-close any still-open trades once market hours end, so nothing carries overnight."""
    opens = store.open_trades()
    if not opens:
        return
    symbols = list(dict.fromkeys(t["symbol"] for t in opens))
    prices = get_prices(client_id, token, symbols, "exit")
    now_hm = dt.datetime.now(IST).strftime("%H:%M")
    for t in opens:
        ltp = prices.get(t["symbol"])
        if ltp is None:
            if t["symbol"] not in _EOD_WARNED:
                _EOD_WARNED.add(t["symbol"])
                log(f"EOD: no price for {t['symbol']}, leaving OPEN until a quote is available")
                telegram(f"18SMA EOD: no price for {t['symbol']} - left OPEN, will retry")
            continue
        pnl = store.close_trade(t["id"], ltp, dt.datetime.now(IST).isoformat(), "EOD SQUAREOFF")
        log(f"EXIT EOD {t['symbol']} @ {ltp} pnl {pnl}")
        telegram(f"18SMA EXIT (EOD Squareoff): {t['symbol']} @ {ltp} pnl Rs.{pnl}")


def main():
    store.init()
    _strategy.ALERT = telegram
    log(f"18SMA Agent started (mode={settings.MODE}) timeframe={settings.TIMEFRAME}min")
    telegram(
        f"18SMA Agent Started\nMode: {settings.MODE}\n"
        f"Instruments: NIFTY, BANKNIFTY, SENSEX\n"
        f"Timeframe: {settings.TIMEFRAME}min | SMA: {settings.SMA_PERIOD}")
    last_scan = 0.0
    while True:
        try:
            token = json.load(open(settings.FYERS_TOKEN_PATH))["token"]
            if in_market_hours():
                monitor_exits(settings.FYERS_CLIENT_ID, token)
                if time.time() - last_scan >= SCAN_SEC:
                    last_scan = time.time()
                    fy = fyers()
                    if store.today_pnl() <= -abs(settings.DAILY_LOSS_LIMIT):
                        log("Daily loss limit hit - skipping new entries")
                    else:
                        for inst in INSTRUMENTS:
                            try_entry(inst, fy, token)
            else:
                eod_squareoff(settings.FYERS_CLIENT_ID, token)
        except Exception as e:
            log(f"Loop error: {e}")
        time.sleep(MONITOR_SEC)

if __name__ == "__main__":
    main()
