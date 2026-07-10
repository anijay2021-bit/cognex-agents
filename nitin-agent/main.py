"""
Nitin Agent — swing-trading agent from the Nitin R / Ankur Patel masterclass.
Paper-trades NSE equities: EOD scan for setups (flag, base-ONP-pullback, DTL,
VCP), then intraday monitoring to trigger entries, stops and targets.
Fyers = market data. Mode: PAPER (no real orders anywhere in this agent).
"""
import datetime as dt
import json
import time
import traceback
from zoneinfo import ZoneInfo

import pandas as pd
import requests
from fyers_apiv3 import fyersModel

import store
from config import settings
from indicators import avg_turnover_cr, is_stage2, relative_strength
from setups import ALL_SETUPS

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


# ---------------- Fyers ----------------
def fyers():
    token = json.load(open(settings.FYERS_TOKEN_PATH))["token"]
    return fyersModel.FyersModel(token=token, is_async=False,
                                 client_id=settings.FYERS_CLIENT_ID, log_path="")


def history(fy, symbol, days=420):
    to_d = dt.date.today()
    frm = to_d - dt.timedelta(days=int(days * 1.6))
    r = fy.history({"symbol": symbol, "resolution": "D", "date_format": "1",
                    "range_from": frm.isoformat(), "range_to": to_d.isoformat(),
                    "cont_flag": "1"})
    if r.get("s") != "ok":
        raise RuntimeError(f"history {symbol}: {r.get('message', r.get('s'))}")
    df = pd.DataFrame(r["candles"], columns=["ts", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["ts"], unit="s")
    time.sleep(0.4)
    return df.set_index("date").drop(columns="ts").sort_index()


def ltp(fy, symbols):
    out = {}
    for i in range(0, len(symbols), 40):
        r = fy.quotes({"symbols": ",".join(symbols[i:i + 40])})
        if r.get("s") == "ok":
            for q in r.get("d", []):
                out[q["n"]] = q["v"].get("lp")
        time.sleep(0.3)
    return out


# ---------------- sizing (fixed risk, 1%) ----------------
def size_qty(entry, stop):
    if entry <= stop:
        return 0
    if (entry - stop) / entry * 100 > settings.MAX_STOP_PCT:
        return 0
    qty = int(settings.CAPITAL * settings.RISK_PER_TRADE_PCT / 100 / (entry - stop))
    return min(qty, int(settings.CAPITAL * settings.MAX_ALLOCATION_PCT / 100 / entry))


# ---------------- EOD scan ----------------
def scan():
    log("EOD scan starting")
    fy = fyers()
    symbols = [l.strip() for l in open(settings.WATCHLIST)
               if l.strip() and not l.startswith("#")]
    bench = history(fy, settings.BENCHMARK)
    now = dt.datetime.now(IST)
    found = []
    for sym in symbols:
        try:
            if store.has_pending_or_open(sym):
                continue
            df = history(fy, sym)
            if avg_turnover_cr(df) < settings.MIN_TURNOVER_CR or not is_stage2(df):
                continue
            if relative_strength(df, bench) <= 0:
                continue
            for fn in ALL_SETUPS:
                sig = fn(sym, df)
                if sig:
                    qty = size_qty(sig.entry, sig.stop)
                    if qty <= 0:
                        continue
                    valid = (now + dt.timedelta(days=settings.SIGNAL_VALID_DAYS)).isoformat()
                    store.add_signal(now.isoformat(), sig, qty, valid)
                    found.append(f"{sym} [{sig.setup}] entry {sig.entry} SL {sig.stop} "
                                 f"T1 {sig.target1} T2 {sig.target2} qty {qty}")
                    break
        except Exception as e:
            log(f"scan {sym}: {e}")
    msg = (f"Nitin Agent EOD scan ({settings.MODE}): {len(found)} signal(s)\n"
           + "\n".join(found)) if found else "Nitin Agent EOD scan: no new setups."
    telegram(msg)
    log(msg)


# ---------------- intraday monitor ----------------
def monitor():
    now = dt.datetime.now(IST)
    pend, opens = store.pending_signals(), store.open_trades()
    if not pend and not opens:
        return
    fy = fyers()
    prices = ltp(fy, sorted({x["symbol"] for x in pend + opens}))

    for s in pend:
        if now > dt.datetime.fromisoformat(s["valid_until"]):
            store.set_signal_status(s["id"], "EXPIRED")
            log(f"signal {s['symbol']} expired")
            continue
        p = prices.get(s["symbol"])
        if p and p >= s["entry"] and store.n_open() < settings.MAX_OPEN_POSITIONS:
            tid = store.open_trade(s, p, now.isoformat())
            store.set_signal_status(s["id"], "TRIGGERED")
            m = (f"Nitin Agent PAPER ENTRY #{tid}: {s['symbol']} qty {s['qty']} @ {p} "
                 f"[{s['setup']}] SL {s['stop']} T1 {s['target1']}")
            telegram(m); log(m)

    for t in store.open_trades():
        p = prices.get(t["symbol"])
        if not p:
            continue
        sig = {x["symbol"]: x for x in pend}
        stop = t["entry_price"] - t["stop_loss_rs"] / t["quantity"]
        setup = t["strategy_used"].split(":")[-1]
        tgt = None
        with store.conn() as c:
            row = c.execute("SELECT target1 FROM signals WHERE symbol=? ORDER BY id DESC LIMIT 1",
                            (t["symbol"],)).fetchone()
            tgt = row["target1"] if row else None
        if p <= stop:
            pnl = store.close_trade(t["id"], p, now.isoformat(), "stop_loss")
            m = f"Nitin Agent PAPER EXIT (SL): {t['symbol']} @ {p} pnl Rs.{pnl}"
            telegram(m); log(m)
        elif tgt and p >= tgt:
            pnl = store.close_trade(t["id"], p, now.isoformat(), "target1_2R")
            m = f"Nitin Agent PAPER EXIT (T1 2R): {t['symbol']} @ {p} pnl Rs.{pnl}"
            telegram(m); log(m)


# ---------------- main loop ----------------
def hm(t):
    h, m = t.split(":"); return int(h) * 60 + int(m)


def main():
    store.init()
    log(f"Nitin Agent started (mode={settings.MODE})")
    telegram(f"Nitin Agent online ({settings.MODE}). Swing setups: flag, base-ONP-pullback, DTL, VCP.")
    last_scan_day, last_mon = None, 0
    while True:
        try:
            now = dt.datetime.now(IST)
            mins = now.hour * 60 + now.minute
            wd = now.weekday() < 5
            if wd and mins >= hm(settings.SCAN_TIME) and last_scan_day != now.date():
                last_scan_day = now.date()
                scan()
            if (wd and hm(settings.MARKET_OPEN) <= mins <= hm(settings.MARKET_CLOSE)
                    and time.time() - last_mon >= settings.MONITOR_EVERY_MIN * 60):
                last_mon = time.time()
                monitor()
        except Exception:
            log("loop error:\n" + traceback.format_exc())
        time.sleep(30)


if __name__ == "__main__":
    main()
