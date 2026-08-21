"""18SMA Agent - Nifty/BankNifty/Sensex, 18-SMA + 2-candle breakout, ATM CE/PE, PAPER mode."""
import datetime as dt, json, time, requests
from zoneinfo import ZoneInfo
from fyers_apiv3 import fyersModel

import store
from config import settings
from strategy import INSTRUMENTS, fetch_candles, check_breakout, fetch_atm_option

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


def target_price(entry):
    if settings.TARGET_MODE == "RR":
        return round(entry + settings.SL_POINTS * settings.TARGET_VALUE, 2)
    if settings.TARGET_MODE == "POINTS":
        return round(entry + settings.TARGET_VALUE, 2)
    return round(entry * (1 + settings.TARGET_VALUE / 100), 2)


def try_entry(inst, fy, token):
    if store.n_open(inst["name"]) > 0:
        return
    df = fetch_candles(fy, inst["index"])
    side = check_breakout(df)
    if not side:
        return
    chain = fetch_atm_option(settings.FYERS_CLIENT_ID, token, inst["index"])
    if not chain:
        log(f"{inst['name']}: {side} breakout but option chain fetch failed")
        return
    leg = chain[side]
    entry = leg["ltp"]
    if not entry:
        return
    qty = inst["lots"] * inst["lot_size"]
    sl = round(entry - settings.SL_POINTS, 2)
    tgt = target_price(entry)
    reason = (f"18SMA {side} breakout: {inst['name']} 2-candle "
              f"{'high' if side == 'CE' else 'low'} break, {settings.TIMEFRAME}min TF. "
              f"Entry {entry} SL {sl} Target {tgt}.")
    store.open_trade(
        order_id=f"18SMA-PAPER-{inst['name']}-{int(time.time())}",
        symbol=leg["symbol"], underlying=inst["name"], strike=leg.get("strike_price", 0),
        expiry=chain["expiry"], direction="BUY", qty=qty,
        entry_price=entry, entry_time=dt.datetime.now(IST).isoformat(),
        sl_price=sl, reason=reason)
    log(f"ENTRY {inst['name']} {side} {leg['symbol']} @ {entry} qty {qty}")
    telegram(
        f"18SMA Signal\nAction: TRADE\nSymbol: {leg['symbol']}\nDirection: BUY\n"
        f"Entry: {entry}  SL: {sl}  Target: {tgt}\nQty: {qty}\n{reason}")


def monitor_exits(client_id, token):
    opens = store.open_trades()
    if not opens:
        return
    symbols = [t["symbol"] for t in opens]
    url = "https://api-t1.fyers.in/data/quotes"
    headers = {"Authorization": f"{client_id}:{token}"}
    resp = requests.get(url, headers=headers, params={"symbols": ",".join(symbols)}, timeout=10)
    j = resp.json()
    prices = {}
    if j.get("s") == "ok":
        for d in j.get("d", []):
            v = d.get("v", {})
            if "lp" in v:
                prices[d["n"]] = v["lp"]
    for t in opens:
        ltp = prices.get(t["symbol"])
        if ltp is None:
            continue
        sl = round(t["entry_price"] - settings.SL_POINTS, 2)
        tgt = target_price(t["entry_price"])
        if ltp <= sl:
            pnl = store.close_trade(t["id"], ltp, dt.datetime.now(IST).isoformat(), "SL HIT")
            log(f"EXIT SL {t['symbol']} @ {ltp} pnl {pnl}")
            telegram(f"18SMA EXIT (SL): {t['symbol']} @ {ltp} pnl Rs.{pnl}")
        elif ltp >= tgt:
            pnl = store.close_trade(t["id"], ltp, dt.datetime.now(IST).isoformat(), "TARGET HIT")
            log(f"EXIT TARGET {t['symbol']} @ {ltp} pnl {pnl}")
            telegram(f"18SMA EXIT (Target): {t['symbol']} @ {ltp} pnl Rs.{pnl}")


def main():
    store.init()
    log(f"18SMA Agent started (mode={settings.MODE}) timeframe={settings.TIMEFRAME}min")
    telegram(
        f"18SMA Agent Started\nMode: {settings.MODE}\n"
        f"Instruments: NIFTY, BANKNIFTY, SENSEX\n"
        f"Timeframe: {settings.TIMEFRAME}min | SMA: {settings.SMA_PERIOD}")
    while True:
        try:
            if not in_market_hours():
                time.sleep(30)
                continue
            token = json.load(open(settings.FYERS_TOKEN_PATH))["token"]
            fy = fyers()
            if store.today_pnl() <= -abs(settings.DAILY_LOSS_LIMIT):
                log("Daily loss limit hit - skipping new entries")
            else:
                for inst in INSTRUMENTS:
                    try_entry(inst, fy, token)
            monitor_exits(settings.FYERS_CLIENT_ID, token)
        except Exception as e:
            log(f"Loop error: {e}")
        time.sleep(settings.SCAN_EVERY_SEC)


if __name__ == "__main__":
    main()
