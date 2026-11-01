"""Show 18SMA-Stocks in the dashboard Trades tab (idempotent). Run on the VM."""
import os, shutil

D = os.path.expanduser("~/cognex-dashboard")


def edit(rel, old, new, marker):
    p = os.path.join(D, rel)
    s = open(p, encoding="utf-8").read()
    if marker in s:
        print("already patched:", rel)
        return
    assert s.count(old) == 1, (rel, old[:50], s.count(old))
    shutil.copy(p, p + ".bak-s18trades")
    open(p, "w", encoding="utf-8").write(s.replace(old, new))
    print("patched:", rel)


HELPER = '''

def _stocks18_trades(date_from, date_to, status, strategy, index):
    """18SMA-Stocks signals (agent's own signals.db) shaped like trade rows."""
    import os, sqlite3
    empty = {"trades": [], "summary": {"total": 0, "closed": 0, "open": 0, "wins": 0, "losses": 0, "total_pnl": 0}}
    if index and index.upper() != "ALL":
        return empty
    if strategy and strategy.upper() not in ("ALL", "18SMA-STOCKS"):
        return empty
    path = os.path.join(config.BASE, "18sma-stocks-agent", "signals.db")
    if not os.path.exists(path):
        return empty
    q, a = "SELECT * FROM signals WHERE 1=1", []
    if date_from:
        q += " AND substr(signal_time,1,10)>=?"; a.append(date_from)
    if date_to:
        q += " AND substr(signal_time,1,10)<=?"; a.append(date_to)
    if status and status.upper() != "ALL":
        q += " AND upper(status)=?"; a.append(status.upper())
    q += " ORDER BY id DESC LIMIT 1000"
    c = sqlite3.connect(path, timeout=5)
    c.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in c.execute(q, a)]
    finally:
        c.close()
    out, closed, opn, wins, losses, tot = [], 0, 0, 0, 0, 0.0
    for r in rows:
        st = (r.get("status") or "").upper()
        pnl = r.get("pnl_rs")
        if st == "CLOSED":
            closed += 1
            tot += pnl or 0
            wins += 1 if (pnl or 0) > 0 else 0
            losses += 1 if (pnl or 0) < 0 else 0
        elif st == "OPEN":
            opn += 1
        out.append({
            "symbol": "%s %s %s" % (r.get("symbol"), r.get("strike"), r.get("opt_type")),
            "direction": "BUY", "strategy_used": "18SMA-Stocks",
            "entry_price": r.get("entry_price") or 0, "exit_price": r.get("exit_price"),
            "quantity": (r.get("lots") or 0) * (r.get("lot_size") or 0), "pnl_rs": pnl,
            "status": st, "mode": "PAPER", "entry_time": r.get("signal_time"),
            "exit_time": r.get("exit_time") or r.get("closed_at") or r.get("exit_ts"),
        })
    return {"trades": out, "summary": {"total": len(rows), "closed": closed, "open": opn,
                                       "wins": wins, "losses": losses, "total_pnl": tot}}
'''

# backend
edit("routers/trades.py", "    return result\n\n\n@router.get(\"/pnl/today\")",
     "    if not agent or agent == \"stocks18\":\n"
     "        try:\n"
     "            result[\"stocks18\"] = _stocks18_trades(date_from, date_to, status, strategy, index)\n"
     "        except Exception as e:\n"
     "            result[\"stocks18\"] = {\"trades\": [], \"summary\": {}, \"error\": str(e)}\n"
     "    return result\n\n\n@router.get(\"/pnl/today\")", "_stocks18_trades(date_from")
s = open(os.path.join(D, "routers/trades.py"), encoding="utf-8").read()
if "def _stocks18_trades" not in s:
    s = s.replace('@router.get("/today")', HELPER.strip("\n") + '\n\n\n@router.get("/today")', 1)
    if "import config" not in s:
        s = s.replace("from config import AGENTS", "import config\nfrom config import AGENTS", 1)
    open(os.path.join(D, "routers/trades.py"), "w", encoding="utf-8").write(s)
    print("added helper")

# frontend button
edit("static/index.html", "onclick=\"setTT('vwap',this)\">VWAP</div>",
     "onclick=\"setTT('vwap',this)\">VWAP</div><div class=\"tt\" id=\"ttps\" onclick=\"setTT('stocks18',this)\">18SMA-Stocks</div>",
     "setTT('stocks18'")
