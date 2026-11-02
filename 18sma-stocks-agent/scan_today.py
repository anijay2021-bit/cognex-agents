"""One-off report: which F&O stocks crossed ABOVE / BELOW 18 SMA on 15-min closes today.
Run on the VM:  venv/bin/python scan_today.py
Read-only: sends no Telegram alerts and writes nothing to signals.db."""
import datetime as dt
import collections
import main as M

S = M.get_settings()
P = S["sma_period"]
A = M.Angel(M.ENV)
if not A.login():
    raise SystemExit("login failed")
inst = M.load_instruments()
watch = M.load_watchlist()
toks = [(s, inst["eq"][s]) for s, _ in watch if s in inst["eq"]]
now = M.now_ist()
today = now.date()
end = now.replace(hour=15, minute=30, second=0, microsecond=0) if now.hour >= 15 else now
frm = (end - dt.timedelta(days=5)).replace(hour=9, minute=15, second=0, microsecond=0)

up, dn, last_above, last_below, nodata = collections.defaultdict(list), collections.defaultdict(list), [], [], []
low = 0
for sym, tok in toks:
    rows = A.candles(tok, frm, end)
    cl = []
    for r in rows:
        try:
            cl.append((dt.datetime.fromisoformat(r[0]).astimezone(M.IST), float(r[4])))
        except Exception:
            pass
    if len(cl) < P + 2:
        nodata.append(sym)
        continue
    closes = [c for _, c in cl]
    if closes[-1] < S["min_price"]:
        low += 1
        continue
    for i in range(1, len(cl)):
        t = cl[i][0]
        if t.date() != today or i < P:
            continue
        s1 = sum(closes[i - P + 1:i + 1]) / P
        s0 = sum(closes[i - P:i]) / P
        c1, c0 = closes[i], closes[i - 1]
        close_time = (t + M.TF).strftime("%H:%M")
        if c0 <= s0 and c1 > s1:
            up[close_time].append(sym)
        elif c0 >= s0 and c1 < s1:
            dn[close_time].append(sym)
    s_last = sum(closes[-P:]) / P
    (last_above if closes[-1] > s_last else last_below).append(sym)

print("DATE", today, "| stocks", len(toks), "| no data", len(nodata), "| below Rs100", low)
print("CROSSED ABOVE 18SMA (candle close time):")
for k in sorted(up):
    print(" ", k, len(up[k]), ",".join(up[k]))
print("CROSSED BELOW 18SMA:")
for k in sorted(dn):
    print(" ", k, len(dn[k]), ",".join(dn[k]))
print("LAST CLOSE ABOVE SMA:", len(last_above), "| BELOW:", len(last_below))
with open("scan_today.txt", "w") as f:
    f.write("UP\n")
    for k in sorted(up):
        f.write("%s %s\n" % (k, ",".join(up[k])))
    f.write("DOWN\n")
    for k in sorted(dn):
        f.write("%s %s\n" % (k, ",".join(dn[k])))
    f.write("ABOVE_NOW %s\n" % ",".join(last_above))
    f.write("NODATA %s\n" % ",".join(nodata))
