"""List today's 18SMA-Stocks entries whose price equals the option's previous close (stale quote).
Usage (on the VM):  venv/bin/python audit_entries.py            -> report only
                    venv/bin/python audit_entries.py --void 12,15 -> mark those signal ids VOID (excluded from P&L)"""
import sys
import main as M

if "--void" in sys.argv:
    ids = [int(x) for x in sys.argv[sys.argv.index("--void") + 1].split(",") if x.strip()]
    with M.db() as c:
        for i in ids:
            c.execute("UPDATE signals SET status='VOID', pnl_rs=0, reason='VOID: entry was previous close (no trade)' WHERE id=?", (i,))
    print("voided", ids)
    raise SystemExit

today = M.now_ist().date().isoformat()
with M.db() as c:
    rows = [dict(r) for r in c.execute(
        "SELECT * FROM signals WHERE substr(signal_time,1,10)=? AND entry_price IS NOT NULL ORDER BY id", (today,))]
A = M.Angel(M.ENV)
if not A.login():
    raise SystemExit("login failed")
q = A.quotes([("NFO", r["option_token"]) for r in rows])
print("id | symbol strike type | entry | prev close | traded today | bid/ask | status pnl | FLAG")
bad = 0
for r in rows:
    k = q.get(("NFO", str(r["option_token"])))
    if not k:
        print(r["id"], r["symbol"], "no quote")
        continue
    stale = abs(r["entry_price"] - k["close"]) < 0.005
    bad += stale
    print("%s | %s %g %s | %.2f | %.2f | vol %d | %.2f/%.2f | %s %s | %s" % (
        r["id"], r["symbol"], r["strike"], r["opt_type"], r["entry_price"], k["close"], k["vol"], k["bid"], k["ask"],
        r["status"], r["pnl_rs"], "STALE?" if stale else ""))
print("total", len(rows), "| entry == previous close:", bad)
