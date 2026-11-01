#!/usr/bin/env python3
"""18SMA-Stocks agent.

Scans NSE F&O stocks on the 15-min timeframe (Angel One data). When a 15-min candle
closes above / below its 18 SMA it sends a Telegram alert for the ATM CALL / PUT with
option price, target and stop-loss, then tracks that signal (paper) until TGT / SL /
square-off. Settings live in settings.json and are edited from the COGNEX dashboard.
"""
import os, sys, csv, json, time, hmac, base64, struct, hashlib, sqlite3, logging, datetime as dt
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SET_FILE = os.path.join(BASE, "settings.json")
DB_FILE = os.path.join(BASE, "signals.db")
STATUS_FILE = os.path.join(BASE, "status.json")
CSV_FILE = os.path.join(BASE, "fno_lot_sizes.csv")
INST_FILE = os.path.join(BASE, "instruments.json")
MASTER_URL = "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json"
TF = dt.timedelta(minutes=15)

DEFAULTS = {
    "scan_enabled": True,
    "lots": 1,
    "product": "INTRADAY",       # INTRADAY | CARRYFORWARD
    "tgt_mode": "percent",       # percent | absolute  (from option BUY price)
    "tgt_value": 30.0,
    "sl_mode": "percent",
    "sl_value": 20.0,
    "min_price": 100.0,          # no scan for stocks priced below this (Rs)
    "sma_period": 18,
    "signal_mode": "cross",      # cross = alert on the crossing candle only | always = every close above/below
    "scan_until": "15:15",       # last candle-close time scanned (IST)
    "squareoff_time": "15:15",   # INTRADAY signals are closed at this time
}

os.makedirs(os.path.join(BASE, "logs"), exist_ok=True)
log = logging.getLogger("stocks18")
log.setLevel(logging.INFO)
_fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")
for _h in (logging.FileHandler(os.path.join(BASE, "logs", "stocks18.log")), logging.StreamHandler(sys.stdout)):
    _h.setFormatter(_fmt)
    log.addHandler(_h)


# ----------------------------------------------------------------------------- helpers
def load_env():
    env, p = {}, os.path.join(BASE, "config", ".env")
    if os.path.exists(p):
        for ln in open(p, encoding="utf-8"):
            ln = ln.strip()
            if ln and not ln.startswith("#") and "=" in ln:
                k, v = ln.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()


def now_ist():
    return dt.datetime.now(IST)


def hhmm(s, default):
    try:
        h, m = str(s).split(":")
        return dt.time(int(h), int(m))
    except Exception:
        return default


def get_settings():
    s = dict(DEFAULTS)
    try:
        s.update(json.load(open(SET_FILE)))
    except Exception:
        pass
    try:
        s["lots"] = max(1, int(s["lots"]))
        s["sma_period"] = max(2, int(s["sma_period"]))
        for k in ("tgt_value", "sl_value", "min_price"):
            s[k] = float(s[k])
        s["product"] = "CARRYFORWARD" if str(s["product"]).upper().startswith("C") else "INTRADAY"
        s["tgt_mode"] = "absolute" if str(s["tgt_mode"]).lower().startswith("a") else "percent"
        s["sl_mode"] = "absolute" if str(s["sl_mode"]).lower().startswith("a") else "percent"
        s["signal_mode"] = "always" if str(s["signal_mode"]).lower() == "always" else "cross"
    except Exception as e:
        log.warning("bad settings (%s) - using defaults", e)
        return dict(DEFAULTS)
    return s


def tick(x):
    return round(round(x * 20) / 20, 2)


def levels(entry, S):
    t = entry * (1 + S["tgt_value"] / 100) if S["tgt_mode"] == "percent" else entry + S["tgt_value"]
    l = entry * (1 - S["sl_value"] / 100) if S["sl_mode"] == "percent" else entry - S["sl_value"]
    return tick(t), tick(max(l, 0.05))


def tg(msg):
    tok, chat = ENV.get("TELEGRAM_BOT_TOKEN"), ENV.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        log.warning("Telegram not configured: %s", msg[:80])
        return
    try:
        r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          json={"chat_id": chat, "text": msg}, timeout=10)
        if r.status_code != 200:
            log.warning("Telegram HTTP %s: %s", r.status_code, r.text[:100])
    except Exception as e:
        log.warning("Telegram error: %s", e)


def send_alerts(msgs):
    if len(msgs) <= 8:
        for m in msgs:
            tg(m)
            time.sleep(1.1)
        return
    buf = ""
    for m in msgs:
        if len(buf) + len(m) > 3500:
            tg(buf)
            time.sleep(1.1)
            buf = ""
        buf += m + "\n\n"
    if buf:
        tg(buf)


def totp(secret):
    key = base64.b32decode(secret.replace(" ", "").upper() + "=" * (-len(secret.replace(" ", "")) % 8))
    h = hmac.new(key, struct.pack(">Q", int(time.time() // 30)), hashlib.sha1).digest()
    o = h[-1] & 15
    return str((struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6).zfill(6)


# ----------------------------------------------------------------------------- Angel One REST
class Angel:
    HOST = "https://apiconnect.angelone.in"

    def __init__(self, env):
        self.env, self.jwt = env, None
        self.last_call, self.fail_until, self.warned = 0.0, 0.0, False

    def _hdr(self, auth=True):
        h = {"Content-Type": "application/json", "Accept": "application/json", "X-UserType": "USER",
             "X-SourceID": "WEB", "X-ClientLocalIP": "127.0.0.1", "X-ClientPublicIP": "127.0.0.1",
             "X-MACAddress": "00:00:00:00:00:00", "X-PrivateKey": self.env.get("ANGELONE_API_KEY", "")}
        if auth and self.jwt:
            h["Authorization"] = "Bearer " + self.jwt
        return h

    def login(self):
        if time.time() < self.fail_until:
            return False
        try:
            r = requests.post(self.HOST + "/rest/auth/angelbroking/user/v1/loginByPassword",
                              json={"clientcode": self.env.get("ANGELONE_CLIENT_ID"),
                                    "password": self.env.get("ANGELONE_PASSWORD"),
                                    "totp": totp(self.env.get("ANGELONE_TOTP_SECRET", ""))},
                              headers=self._hdr(False), timeout=20).json()
        except Exception as e:
            r = {"status": False, "message": str(e)}
        if r.get("status") and r.get("data"):
            self.jwt, self.warned = r["data"]["jwtToken"], False
            log.info("Angel One login OK")
            return True
        self.jwt = None
        self.fail_until = time.time() + 300
        log.error("Angel One login failed: %s", r.get("message"))
        if not self.warned:
            self.warned = True
            tg("18SMA-Stocks: Angel One login FAILED (%s). Retrying every 5 min." % r.get("message"))
        return False

    def post(self, path, body, gap=0.4):
        for attempt in range(3):
            w = self.last_call + gap - time.time()
            if w > 0:
                time.sleep(w)
            if not self.jwt and not self.login():
                return None
            try:
                self.last_call = time.time()
                resp = requests.post(self.HOST + path, json=body, headers=self._hdr(), timeout=20)
                try:
                    r = resp.json()
                except Exception:
                    time.sleep(2 + attempt * 2)          # rate-limit pages are not JSON
                    continue
                if r.get("status"):
                    return r.get("data")
                msg, code = str(r.get("message", "")), str(r.get("errorcode", ""))
                if "token" in msg.lower() or code in ("AG8001", "AG8002", "AB8050", "AB8051"):
                    self.jwt = None
                    continue
                if "rate" in msg.lower() or code == "AB1004":
                    time.sleep(2 + attempt * 2)
                    continue
                log.warning("Angel %s -> %s %s", path.split("/")[-2], code, msg[:80])
                return None
            except Exception as e:
                log.warning("Angel request error: %s", e)
                time.sleep(1)
        return None

    def candles(self, token, frm, to):
        d = self.post("/rest/secure/angelbroking/historical/v1/getCandleData",
                      {"exchange": "NSE", "symboltoken": str(token), "interval": "FIFTEEN_MINUTE",
                       "fromdate": frm.strftime("%Y-%m-%d %H:%M"), "todate": to.strftime("%Y-%m-%d %H:%M")})
        return d or []

    def ltp(self, items):
        """items: list of (exchange, token) -> {(exchange, token): ltp}"""
        out = {}
        for i in range(0, len(items), 50):
            grp = {}
            for e, t in items[i:i + 50]:
                grp.setdefault(e, []).append(str(t))
            d = self.post("/rest/secure/angelbroking/market/v1/quote/",
                          {"mode": "LTP", "exchangeTokens": grp}, gap=1.1)
            for q in (d or {}).get("fetched", []) or []:
                try:
                    out[(q["exchange"], str(q["symbolToken"]))] = float(q["ltp"])
                except Exception:
                    pass
        return out


# ----------------------------------------------------------------------------- instruments
def build_instruments(raw):
    eq, opt = {}, {}
    for x in raw:
        seg = x.get("exch_seg")
        if seg == "NSE" and str(x.get("symbol", "")).endswith("-EQ"):
            eq[x["name"]] = x["token"]
        elif seg == "NFO" and x.get("instrumenttype") == "OPTSTK":
            try:
                exp = dt.datetime.strptime(x["expiry"], "%d%b%Y").date().isoformat()
                opt.setdefault(x["name"], {}).setdefault(exp, []).append(
                    [float(x["strike"]) / 100.0, x["symbol"][-2:], x["token"], x["symbol"], int(x["lotsize"])])
            except Exception:
                continue
    return {"eq": eq, "opt": opt}


def load_instruments(force=False):
    today = now_ist().date()
    if not force and os.path.exists(INST_FILE):
        if dt.date.fromtimestamp(os.path.getmtime(INST_FILE)) == today:
            return json.load(open(INST_FILE))
    log.info("Downloading Angel One instrument master ...")
    raw = None
    for attempt in range(4):
        try:
            r = requests.get(MASTER_URL, timeout=240)
            r.raise_for_status()
            raw = r.json()
            break
        except Exception as e:
            log.warning("instrument master download failed (%s), retry %d", e, attempt + 1)
            time.sleep(10 * (attempt + 1))
    if raw is None:
        if os.path.exists(INST_FILE):
            log.warning("using stale instrument cache")
            return json.load(open(INST_FILE))
        raise RuntimeError("cannot download instrument master")
    inst = build_instruments(raw)
    json.dump(inst, open(INST_FILE, "w"))
    log.info("Instruments: %d equities, %d option underlyings", len(inst["eq"]), len(inst["opt"]))
    return inst


def load_watchlist():
    out = []
    with open(CSV_FILE, encoding="utf-8-sig") as f:
        for r in csv.reader(f):
            if len(r) < 3 or not r[1].strip() or r[1].strip().lower() == "symbol":
                continue
            try:
                out.append((r[1].strip(), int(float(r[2]))))
            except Exception:
                continue
    return out


def pick_option(inst, sym, spot, direction, today):
    exps = sorted(e for e in inst["opt"].get(sym, {}) if e >= today.isoformat())
    if not exps:
        return None
    exp = exps[1] if exps[0] == today.isoformat() and len(exps) > 1 else exps[0]   # roll off expiry day
    rows = inst["opt"][sym][exp]
    typ = "CE" if direction == "CALL" else "PE"
    cand = [r for r in rows if r[1] == typ]
    if not cand:
        return None
    best = min(cand, key=lambda r: (abs(r[0] - spot), r[0]))
    return {"expiry": exp, "strike": best[0], "type": typ, "token": best[2], "symbol": best[3], "lot": best[4]}


# ----------------------------------------------------------------------------- storage
def db():
    c = sqlite3.connect(DB_FILE, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS signals(
            id INTEGER PRIMARY KEY AUTOINCREMENT, symbol TEXT, direction TEXT, candle_ts TEXT, signal_time TEXT,
            spot REAL, sma REAL, option_symbol TEXT, option_token TEXT, strike REAL, expiry TEXT, opt_type TEXT,
            lot_size INTEGER, lots INTEGER, qty INTEGER, product TEXT, entry_price REAL, target_price REAL,
            sl_price REAL, status TEXT, exit_price REAL, exit_time TEXT, pnl_rs REAL, reason TEXT,
            UNIQUE(symbol, candle_ts, direction))""")


def write_status(**kw):
    try:
        st = {}
        try:
            st = json.load(open(STATUS_FILE))
        except Exception:
            pass
        st.update(kw)
        st["updated"] = now_ist().isoformat(timespec="seconds")
        json.dump(st, open(STATUS_FILE, "w"))
    except Exception as e:
        log.warning("status write failed: %s", e)


# ----------------------------------------------------------------------------- scanning
STATE = {"inst": None, "watch": [], "eligible": [], "day": None, "scanned": None, "warned_nodata": None}


def prepare_day(A, S):
    today = now_ist().date()
    STATE["inst"] = load_instruments()
    STATE["watch"] = load_watchlist()
    inst = STATE["inst"]
    toks = [(s, inst["eq"][s]) for s, _ in STATE["watch"] if s in inst["eq"]]
    unmatched = [s for s, _ in STATE["watch"] if s not in inst["eq"]]
    q = A.ltp([("NSE", t) for _, t in toks])
    elig, low = [], []
    for s, t in toks:
        p = q.get(("NSE", str(t)))
        if p is not None and p < S["min_price"]:
            low.append("%s(%.0f)" % (s, p))
        else:
            elig.append((s, t))
    STATE["eligible"], STATE["day"] = elig, today
    log.info("Watchlist %d | eligible %d | below Rs %.0f: %d | not on NSE-EQ: %s",
             len(STATE["watch"]), len(elig), S["min_price"], len(low), ",".join(unmatched) or "-")
    write_status(eligible=len(elig), excluded_low_price=low, unmatched=unmatched, day=today.isoformat())


def fmt_signal(sig, opt, entry, tgt, sl, S):
    above = sig["dir"] == "CALL"
    exp = dt.date.fromisoformat(opt["expiry"]).strftime("%d%b%y").upper()
    lines = [
        "%s closed %s 18 SMA" % (sig["sym"], "above" if above else "below"),
        "Close: Rs %.2f | 18 SMA: Rs %.2f | Time: %s IST" % (sig["close"], sig["sma"], sig["ts"].strftime("%H:%M")),
        "BUY ATM %s: %s %s %g %s" % ("CALL" if above else "PUT", sig["sym"], exp, opt["strike"], opt["type"]),
    ]
    if entry:
        lines.append("Option price: Rs %.2f" % entry)
        lines.append("TGT: Rs %.2f (%s) | SL: Rs %.2f (%s)" % (
            tgt, ("+%g%%" % S["tgt_value"]) if S["tgt_mode"] == "percent" else ("+Rs %g" % S["tgt_value"]),
            sl, ("-%g%%" % S["sl_value"]) if S["sl_mode"] == "percent" else ("-Rs %g" % S["sl_value"])))
    else:
        lines.append("Option price: n/a (quote unavailable) - not tracked")
    lines.append("Lots: %d x %d = %d qty | %s" % (S["lots"], opt["lot"], S["lots"] * opt["lot"], S["product"]))
    return "\n".join(lines)


def scan(A, b, S):
    t0 = time.time()
    P = S["sma_period"]
    frm = (b - dt.timedelta(days=4)).replace(hour=9, minute=15, second=0, microsecond=0)
    found, ok, skip = [], 0, 0
    for sym, tok in STATE["eligible"]:
        rows = A.candles(tok, frm, b)
        cl = []
        for r in rows:
            try:
                cl.append((dt.datetime.fromisoformat(r[0]).astimezone(IST), float(r[4])))
            except Exception:
                continue
        cl = [(t, c) for t, c in cl if t + TF <= b + dt.timedelta(seconds=1)]
        if len(cl) < P + 1 or cl[-1][0] != b - TF:
            skip += 1
            continue
        ok += 1
        closes = [c for _, c in cl]
        c1, c0 = closes[-1], closes[-2]
        s1, s0 = sum(closes[-P:]) / P, sum(closes[-P - 1:-1]) / P
        if c1 < S["min_price"]:
            continue
        if S["signal_mode"] == "cross":
            up, dn = (c0 <= s0 and c1 > s1), (c0 >= s0 and c1 < s1)
        else:
            up, dn = c1 > s1, c1 < s1
        if up or dn:
            found.append({"sym": sym, "dir": "CALL" if up else "PUT", "close": c1, "sma": s1, "ts": cl[-1][0] + TF})
    msgs = process_signals(A, found, S)
    if ok == 0 and STATE["warned_nodata"] != b.date():
        STATE["warned_nodata"] = b.date()
        tg("18SMA-Stocks: no fresh 15-min candles for any stock at %s (market holiday or Angel One data issue)." % b.strftime("%H:%M"))
    if msgs:
        send_alerts(msgs)
    dur = round(time.time() - t0)
    log.info("Scan %s: scanned %d, skipped %d, signals %d (%ds)", b.strftime("%H:%M"), ok, skip, len(found), dur)
    write_status(last_scan=b.isoformat(timespec="minutes"), scanned=ok, skipped=skip, signals_last=len(found), scan_seconds=dur)


def process_signals(A, found, S):
    if not found:
        return []
    today = now_ist().date()
    inst = STATE["inst"]
    picks = []
    for sg in found:
        opt = pick_option(inst, sg["sym"], sg["close"], sg["dir"], today)
        if not opt:
            log.warning("No option contract for %s", sg["sym"])
            continue
        picks.append((sg, opt))
    q = A.ltp([("NFO", o["token"]) for _, o in picks])
    msgs = []
    for sg, opt in picks:
        entry = q.get(("NFO", str(opt["token"])))
        tgt, sl = levels(entry, S) if entry else (None, None)
        lot = opt["lot"]
        with db() as c:
            cur = c.execute(
                "INSERT OR IGNORE INTO signals(symbol,direction,candle_ts,signal_time,spot,sma,option_symbol,option_token,"
                "strike,expiry,opt_type,lot_size,lots,qty,product,entry_price,target_price,sl_price,status) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (sg["sym"], sg["dir"], sg["ts"].isoformat(timespec="minutes"), now_ist().isoformat(timespec="seconds"),
                 sg["close"], sg["sma"], opt["symbol"], opt["token"], opt["strike"], opt["expiry"], opt["type"],
                 lot, S["lots"], S["lots"] * lot, S["product"], entry, tgt, sl, "OPEN" if entry else "ALERT"))
            fresh = cur.rowcount == 1
        if fresh:
            msgs.append(fmt_signal(sg, opt, entry, tgt, sl, S))
    return msgs


# ----------------------------------------------------------------------------- tracking (paper)
def monitor(A, S, now):
    with db() as c:
        opens = [dict(r) for r in c.execute("SELECT * FROM signals WHERE status='OPEN'")]
    if not opens:
        return
    q = A.ltp([("NFO", o["option_token"]) for o in opens])
    sq = hhmm(S["squareoff_time"], dt.time(15, 15))
    for o in opens:
        p = q.get(("NFO", str(o["option_token"])))
        reason = None
        sig_day = o["signal_time"][:10]
        expiry_day = o["expiry"] <= now.date().isoformat()
        if o["product"] == "INTRADAY" and sig_day < now.date().isoformat():
            fin(o, None, now, "EOD_MISSED")
            continue
        if p is None:
            continue
        if p >= o["target_price"]:
            reason = "TARGET"
        elif p <= o["sl_price"]:
            reason = "SL"
        elif (o["product"] == "INTRADAY" or expiry_day) and now.time() >= sq:
            reason = "EOD"
        if reason:
            fin(o, p, now, reason)


def fin(o, price, now, reason):
    pnl = round((price - o["entry_price"]) * o["qty"], 2) if price is not None else None
    with db() as c:
        c.execute("UPDATE signals SET status='CLOSED', exit_price=?, exit_time=?, pnl_rs=?, reason=? WHERE id=?",
                  (price, now.isoformat(timespec="seconds"), pnl, reason, o["id"]))
    exp = dt.date.fromisoformat(o["expiry"]).strftime("%d%b%y").upper()
    name = "%s %s %g %s" % (o["symbol"], exp, o["strike"], o["opt_type"])
    if price is None:
        tg("18SMA-Stocks EXIT (%s): %s - not squared off, no price" % (reason, name))
    else:
        tg("18SMA-Stocks EXIT (%s): %s @ Rs %.2f (entry Rs %.2f) | P&L Rs %+.0f (%d qty)" % (
            reason, name, price, o["entry_price"], pnl, o["qty"]))
    log.info("Closed #%s %s %s @ %s pnl=%s", o["id"], name, reason, price, pnl)


# ----------------------------------------------------------------------------- main loop
def last_boundary(now):
    b = now.replace(minute=now.minute // 15 * 15, second=0, microsecond=0)
    lo, hi = now.replace(hour=9, minute=30, second=0, microsecond=0), now.replace(hour=15, minute=30, second=0, microsecond=0)
    return b if lo <= b <= hi else None


def main():
    init_db()
    if not os.path.exists(SET_FILE):
        json.dump(DEFAULTS, open(SET_FILE, "w"), indent=2)
    need = ("ANGELONE_API_KEY", "ANGELONE_CLIENT_ID", "ANGELONE_PASSWORD", "ANGELONE_TOTP_SECRET")
    miss = [k for k in need if not ENV.get(k)]
    if miss:
        log.error("Missing in config/.env: %s", ",".join(miss))
        time.sleep(30)
        sys.exit(1)
    A = Angel(ENV)
    log.info("18SMA-Stocks agent started")
    tg("18SMA-Stocks agent started (15-min 18 SMA scan on NSE F&O stocks).")
    last_mon = 0.0
    while True:
        try:
            now, S = now_ist(), get_settings()
            live = now.weekday() < 5 and dt.time(9, 15) <= now.time() <= dt.time(15, 40)
            if live:
                if STATE["day"] != now.date():
                    A.jwt = None
                    prepare_day(A, S)
                b = last_boundary(now)
                if (b and b != STATE["scanned"] and S["scan_enabled"] and now >= b + dt.timedelta(seconds=10)
                        and b.time() <= hhmm(S["scan_until"], dt.time(15, 15))):
                    STATE["scanned"] = b
                    if now - b <= dt.timedelta(minutes=6):      # skip stale boundaries after a late start
                        scan(A, b, S)
                    else:
                        log.info("Skipping stale boundary %s", b.strftime("%H:%M"))
                if time.time() - last_mon >= 60:
                    last_mon = time.time()
                    monitor(A, S, now)
            elif now.weekday() < 5 and now.time() > dt.time(15, 40) and time.time() - last_mon >= 600:
                last_mon = time.time()
                monitor(A, S, now)                              # settle stale intraday leftovers
        except Exception as e:
            log.exception("loop error: %s", e)
            time.sleep(10)
        time.sleep(5)


if __name__ == "__main__":
    main()
