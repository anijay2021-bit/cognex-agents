"""Wire 18SMA-Stocks into the COGNEX dashboard (idempotent). Run from ~/cognex-dashboard."""
import os, shutil

D = os.path.expanduser("~/cognex-dashboard")


def patch(rel, old, new, marker):
    p = os.path.join(D, rel)
    s = open(p, encoding="utf-8").read()
    if marker in s:
        print("already patched:", rel)
        return
    assert s.count(old) == 1, (rel, s.count(old))
    shutil.copy(p, p + ".bak-stocks18")
    open(p, "w", encoding="utf-8").write(s.replace(old, new + old, 1))
    print("patched:", rel)


patch("config.py", '    "pocketpivot": {', '''    "stocks18": {
        "display_name": "18SMA-Stocks",
        "account":      "Kiran - alerts only",
        "service":      "18sma-stocks-agent",
        "db":           None,
        "log":          f"{BASE}/18sma-stocks-agent/logs/stocks18.log",
        "strategies":   ["18 SMA close (15m) on F&O stocks -> ATM option alert"],
        "broker_data":  "Angel One",
        "broker_exec":  "Alerts",
    },
''', '"stocks18"')

patch("main.py", 'app.include_router(live_router,', '''from routers.stocks18 import router as stocks18_router
app.include_router(stocks18_router, prefix="/api/stocks18", tags=["18SMA-Stocks"])
''', "stocks18_router")

CARD = '''    <div class="ac" id="card-stocks18">
      <div class="atp"><div><div class="an">18SMA-Stocks</div><div class="as2">F&amp;O stocks - 15m 18 SMA alerts (Angel One)</div></div><div class="sp unknown" id="pill-stocks18"><div class="spd"></div><span>-</span></div></div>
      <div class="asts"><div class="ast"><div class="al">Scans</div><div class="av" style="font-size:11px;color:#64748b">every 15 min</div></div><div class="ast"><div class="al">Settings</div><div class="av" style="font-size:11px"><a href="/stocks18.html" target="_blank">Open settings &amp; signals</a></div></div></div>
      <div class="abt"><div class="ab start" onclick="act('stocks18','start')">Start</div><div class="ab stop" onclick="act('stocks18','stop')">Stop</div><div class="ab restart" onclick="act('stocks18','restart')">Restart</div></div>
    </div>
'''
patch("static/index.html", '    <div class="ac" id="card-pocketpivot">', CARD, 'id="card-stocks18"')
