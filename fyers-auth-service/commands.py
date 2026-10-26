import sqlite3, subprocess, os, html, datetime
H = os.path.expanduser("~")
AG = {"vwap": ("vwap-agent", "vwap-agent.service"), "18sma": ("18sma-agent", "18sma-agent.service")}
HELP = ("<b>COGNEX commands</b>\n/status - agents, open trades, today P&amp;L\n/positions - open trades\n/pnl - today P&amp;L by agent\n/trades - today's trades\n/stop vwap|18sma|all\n/start vwap|18sma|all\n/help - this list\n\nFYERS_AUTH &lt;url&gt; - refresh Fyers token")
def _rows(d, q):
    try:
        c = sqlite3.connect(f"{H}/{d}/cognex_agent.db", timeout=5)
        c.row_factory = sqlite3.Row
        r = [dict(x) for x in c.execute(q)]
        c.close()
        return r
    except Exception:
        return []
def _active(s):
    return subprocess.run(["systemctl", "is-active", s], capture_output=True, text=True).stdout.strip()
def _today():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
def _open(d):
    return _rows(d, "SELECT * FROM trades WHERE status='OPEN'")
def _closed_today(d):
    return _rows(d, f"SELECT * FROM trades WHERE status='CLOSED' AND substr(exit_time,1,10)='{_today()}'")
def _pnl(d):
    return sum(float(t.get("pnl_rs") or 0) for t in _closed_today(d))
def _line(t):
    return html.escape(f"{t['symbol']} x{t['quantity']} @ {t['entry_price']}")
def status():
    out = ["<b>COGNEX status</b> " + _today()]
    for k, (d, s) in AG.items():
        out.append(f"{k}: {_active(s)} | open {len(_open(d))} | P&amp;L {_pnl(d):+.0f}")
    for s in ("cognex-dashboard.service", "fyers-auth-service.service"):
        out.append(f"{s.split('.')[0]}: {_active(s)}")
    return "\n".join(out)
def positions():
    out = ["<b>Open positions</b>"]
    for k, (d, s) in AG.items():
        for t in _open(d):
            out.append(f"{k}: " + _line(t))
    return "\n".join(out) if len(out) > 1 else "No open positions."
def pnl():
    out = ["<b>Today P&amp;L</b>"]
    tot = 0.0
    for k, (d, s) in AG.items():
        p = _pnl(d)
        tot += p
        out.append(f"{k}: {p:+.0f}")
    out.append(f"Total (closed): {tot:+.0f}")
    return "\n".join(out)
def trades():
    out = ["<b>Today's trades</b>"]
    for k, (d, s) in AG.items():
        for t in _rows(d, f"SELECT * FROM trades WHERE substr(entry_time,1,10)='{_today()}' ORDER BY id"):
            out.append(f"{k}: " + _line(t) + f" {t['status']} {float(t.get('pnl_rs') or 0):+.0f}")
    return "\n".join(out[:40]) if len(out) > 1 else "No trades today."
def ctl(action, arg):
    names = list(AG) if arg == "all" else ([arg] if arg in AG else [])
    if not names:
        return f"Usage: /{action} vwap|18sma|all"
    out = []
    for n in names:
        d, s = AG[n]
        r = subprocess.run(["sudo", "-n", "systemctl", action, s], capture_output=True, text=True)
        out.append(f"{n}: {action} " + ("OK, now " + _active(s) if r.returncode == 0 else "failed: " + html.escape(r.stderr.strip()[:100])))
        if action == "stop" and _open(d):
            out.append(f"WARNING {n} has open trades that are now unmanaged. /start {n} to resume.")
    return "\n".join(out)
def handle(text):
    p = text.strip().split()
    cmd = p[0].lower().split("@")[0]
    arg = p[1].lower() if len(p) > 1 else ""
    if cmd in ("/help", "/start") and not arg:
        return HELP
    if cmd == "/status":
        return status()
    if cmd == "/positions":
        return positions()
    if cmd == "/pnl":
        return pnl()
    if cmd == "/trades":
        return trades()
    if cmd in ("/stop", "/start"):
        return ctl(cmd[1:], arg)
    return None
