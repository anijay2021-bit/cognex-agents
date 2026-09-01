"""VWAP Agent - NIFTY/BankNifty/Sensex ATM CE+PE, session VWAP + SD-band
mean reversion, long only, 3-tier sub-positions (VWAP/+1SD/+2SD), PAPER mode."""
import datetime as dt, json, time, requests
from zoneinfo import ZoneInfo
from fyers_apiv3 import fyersModel

import store
from config import settings
from strategy import INSTRUMENTS, fetch_candles, check_vwap_signal, fetch_atm_option

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


def split_qty(lots, lot_size):
    """3 sub-position lot split. If lots<3, later sub-positions get 0 qty
    and are simply skipped (fewer than 3 legs open that day)."""
    base, rem = divmod(lots, 3)
    parts_lots = [base + (1 if i < rem else 0) for i in range(3)]
    return [pl * lot_size for pl in parts_lots]


def try_entry(inst, side, fy, client_id, token):
    leg = f"{inst['name']}_{side}"
    if store.n_open(leg) > 0:
        return
    chain = fetch_atm_option(client_id, token, inst["index"])
    if not chain:
        return
    opt = chain[side]
    symbol = opt["symbol"]
    df = fetch_candles(fy, symbol)
    if df is None or df.empty:
        return
    signal_id, trig = check_vwap_signal(df)
    if not signal_id:
        return
    if store.signal_traded(leg, signal_id):
        return
    entry = float(opt.get("ltp") or trig["close"])
    if not entry:
        return
    sl = round(float(trig["low"]) - settings.SL_BUFFER_POINTS, 2)
    if sl >= entry:
        return
    targets = [round(float(trig["vwap"]), 2), round(float(trig["upper1"]), 2), round(float(trig["upper2"]), 2)]
    qtys = split_qty(inst["lots"], inst["lot_size"])
    opened = 0
    for i, (tgt, qty) in enumerate(zip(targets, qtys), start=1):
        if qty <= 0:
            continue
        reason = (f"VWAP mean-reversion {side}: {inst['name']} reclaimed lower band "
                  f"(signal {signal_id}), sub-position T{i}/3. "
                  f"Entry {entry} SL {sl} Target {tgt}.")
        store.open_trade(
            order_id=f"VWAP-PAPER-{leg}-T{i}-{int(time.time())}",
            symbol=symbol, underlying=leg, strike=opt.get("strike_price", 0),
            expiry=chain["expiry"], direction="BUY", qty=qty,
            entry_price=entry, entry_time=dt.datetime.now(IST).isoformat(),
            sl_price=sl, target_price=tgt, reason=reason,
            signal_id=f"{signal_id}-T{i}")
        opened += 1
    if opened:
        log(f"ENTRY {leg} {symbol} @ {entry} qtys={qtys} SL {sl} targets {targets} signal={signal_id}")
        telegram(f"VWAP Signal\nAction: TRADE\nSymbol: {symbol}\nDirection: BUY\n"
                 f"Entry: {entry}  SL: {sl}\nTargets: {targets}\nSub-positions opened: {opened}/3")


def monitor_exits(client_id, token):
    opens = store.open_trades()
    if not opens:
        return
    symbols = [t["symbol"] for t in opens]
    prices = {}
    try:
        url = "https://api-t1.fyers.in/data/quotes"
        headers = {"Authorization": f"{client_id}:{token}"}
        resp = requests.get(url, headers=headers, params={"symbols": ",".join(symbols)}, timeout=10)
        j = resp.json()
        if j.get("s") == "ok":
            for d in j.get("d", []):
                v = d.get("v", {})
                if "lp" in v:
                    prices[d["n"]] = v["lp"]
    except Exception as e:
        log(f"Quote fetch error: {e}")
        return
    for t in opens:
        ltp = prices.get(t["symbol"])
        if ltp is None:
            continue
        sl = t["sl_price"]
        tgt = t["target_price"]
        if sl is not None and ltp <= sl:
            pnl = store.close_trade(t["id"], ltp, dt.datetime.now(IST).isoformat(), "SL HIT")
            log(f"EXIT SL {t['symbol']} @ {ltp} pnl {pnl}")
            telegram(f"VWAP EXIT (SL): {t['symbol']} @ {ltp} pnl Rs.{pnl}")
        elif tgt is not None and ltp >= tgt:
            pnl = store.close_trade(t["id"], ltp, dt.datetime.now(IST).isoformat(), "TARGET HIT")
            log(f"EXIT TARGET {t['symbol']} @ {ltp} pnl {pnl}")
            telegram(f"VWAP EXIT (Target): {t['symbol']} @ {ltp} pnl Rs.{pnl}")


def eod_squareoff(client_id, token):
    """Force-close any still-open trades once market hours end."""
    opens = store.open_trades()
    if not opens:
        return
    symbols = [t["symbol"] for t in opens]
    prices = {}
    try:
        url = "https://api-t1.fyers.in/data/quotes"
        headers = {"Authorization": f"{client_id}:{token}"}
        resp = requests.get(url, headers=headers, params={"symbols": ",".join(symbols)}, timeout=10)
        j = resp.json()
        if j.get("s") == "ok":
            for d in j.get("d", []):
                v = d.get("v", {})
                if "lp" in v:
                    prices[d["n"]] = v["lp"]
    except Exception:
        pass
    for t in opens:
        ltp = prices.get(t["symbol"])
        if ltp is None:
            ltp = t["entry_price"]
        pnl = store.close_trade(t["id"], ltp, dt.datetime.now(IST).isoformat(), "EOD SQUAREOFF")
        log(f"EXIT EOD {t['symbol']} @ {ltp} pnl {pnl}")
        telegram(f"VWAP EXIT (EOD Squareoff): {t['symbol']} @ {ltp} pnl Rs.{pnl}")


def main():
    store.init()
    log(f"VWAP Agent started (mode={settings.MODE}) timeframe={settings.TIMEFRAME}min")
    telegram(f"VWAP Agent Started\nMode: {settings.MODE}\n"
             f"Instruments: NIFTY, BANKNIFTY, SENSEX (ATM CE+PE)\n"
             f"Timeframe: {settings.TIMEFRAME}min | 3-tier sub-positions")
    while True:
        try:
            token = json.load(open(settings.FYERS_TOKEN_PATH))["token"]
            if in_market_hours():
                fy = fyers()
                if store.today_pnl() <= -abs(settings.DAILY_LOSS_LIMIT):
                    log("Daily loss limit hit - skipping new entries")
                else:
                    for inst in INSTRUMENTS:
                        for side in ("CE", "PE"):
                            try_entry(inst, side, fy, settings.FYERS_CLIENT_ID, token)
                monitor_exits(settings.FYERS_CLIENT_ID, token)
            else:
                eod_squareoff(settings.FYERS_CLIENT_ID, token)
        except Exception as e:
            log(f"Loop error: {e}")
        time.sleep(settings.SCAN_EVERY_SEC)


if __name__ == "__main__":
    main()
