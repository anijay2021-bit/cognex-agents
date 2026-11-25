"""Manually close every OPEN 18SMA-Stocks paper trade at the current market (bid) price.
Run on the VM AFTER stopping the agent:  venv/bin/python close_all.py
Sell price = best bid; else last price. Contracts with no quote (e.g. expired) are closed with no price."""
import main as M

A = M.Angel(M.ENV)
if not A.login():
    raise SystemExit("login failed")
now = M.now_ist()
with M.db() as c:
    opens = [dict(r) for r in c.execute("SELECT * FROM signals WHERE status='OPEN'")]
print("open trades:", len(opens))
q = A.quotes([("NFO", o["option_token"]) for o in opens]) if opens else {}
n_ok = n_stale = n_none = 0
tot = 0.0
for o in opens:
    k = q.get(("NFO", str(o["option_token"])))
    price, reason = None, "MANUAL_NOQUOTE"
    if k:
        if k["bid"] > 0:
            price, reason = k["bid"], "MANUAL"
        elif k["ltp"] > 0:
            price, reason = k["ltp"], "MANUAL" if k["vol"] > 0 else "MANUAL_STALE"
    pnl = round((price - o["entry_price"]) * o["qty"], 2) if price is not None else None
    with M.db() as c:
        c.execute("UPDATE signals SET status='CLOSED', exit_price=?, exit_time=?, pnl_rs=?, reason=? WHERE id=?",
                  (price, now.isoformat(timespec="seconds"), pnl, reason, o["id"]))
    if price is None:
        n_none += 1
    elif reason == "MANUAL_STALE":
        n_stale += 1
    else:
        n_ok += 1
    tot += pnl or 0
msg = ("18SMA-Stocks stopped. %d open trades closed manually at market: %d at bid/last, %d at stale last price, "
       "%d with no quote. P&L of these exits: Rs %+.0f" % (len(opens), n_ok, n_stale, n_none, tot))
print(msg)
M.tg(msg)
