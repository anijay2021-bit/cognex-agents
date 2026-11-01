"""Move 18SMA-Stocks settings into the dashboard Settings tab (idempotent). Run from anywhere."""
import os, shutil

D = os.path.expanduser("~/cognex-dashboard")


def edit(rel, old, new, marker, count=1):
    p = os.path.join(D, rel)
    s = open(p, encoding="utf-8").read()
    if marker in s:
        print("already patched:", rel)
        return
    assert s.count(old) == count, (rel, old[:40], s.count(old))
    shutil.copy(p, p + ".bak-s18tab")
    open(p, "w", encoding="utf-8").write(s.replace(old, new))
    print("patched:", rel)


def P(id_, label, desc, section, typ, default, var, pat, unit="", opts=None):
    d = {"label": label, "desc": desc, "group": "18SMA-Stocks", "section": section, "dot": "dot-teal",
         "type": typ, "default": default, "unit": unit, "svc": "18sma-stocks-agent",
         "file_map": None}
    if opts:
        d["opts"] = opts
    body = ",".join(f'"{k}":{v!r}'.replace("'", '"') for k, v in d.items() if k != "file_map")
    return f'    "{id_}": {{{body},"file_map": (S18S,"{var}","{pat}")}},\n'


ROWS = [
    P("s18s_scan_enabled", "Scanning", "Turn scanning on/off", "General", "select", "on", "SCAN_ENABLED", "quoted", opts=["on", "off"]),
    P("s18s_product", "Product", "INTRADAY squares off at the time below; CARRYFORWARD holds until option expiry day", "General", "select", "INTRADAY", "PRODUCT", "quoted", opts=["INTRADAY", "CARRYFORWARD"]),
    P("s18s_lots", "Number of lots", "Lots per signal", "General", "int", 1, "LOTS", "simple", "lots"),
    P("s18s_min_price", "Skip stocks below", "No scan for stocks priced below this", "General", "float", 100.0, "MIN_PRICE", "simple", "Rs"),
    P("s18s_signal_mode", "Signal mode", "cross = only the first close beyond SMA; always = every close above/below", "Signal", "select", "cross", "SIGNAL_MODE", "quoted", opts=["cross", "always"]),
    P("s18s_tgt_mode", "Target mode", "From option BUY price: percent or absolute (Rs)", "Target & stop loss", "select", "percent", "TGT_MODE", "quoted", opts=["percent", "absolute"]),
    P("s18s_tgt_value", "Target value", "Percent or Rs depending on target mode", "Target & stop loss", "float", 30.0, "TGT_VALUE", "simple"),
    P("s18s_sl_mode", "Stop loss mode", "From option BUY price: percent or absolute (Rs)", "Target & stop loss", "select", "percent", "SL_MODE", "quoted", opts=["percent", "absolute"]),
    P("s18s_sl_value", "Stop loss value", "Percent or Rs depending on SL mode", "Target & stop loss", "float", 20.0, "SL_VALUE", "simple"),
    P("s18s_scan_until", "Last scan time", "Last candle-close scanned (IST, HH:MM)", "Timing", "str", "15:15", "SCAN_UNTIL", "quoted"),
    P("s18s_squareoff", "Intraday square-off", "INTRADAY signals closed at this time (IST, HH:MM)", "Timing", "str", "15:15", "SQUAREOFF_TIME", "quoted"),
]
IDS = [r.split('"')[1] for r in ROWS]

# 1. config_editor.py: path constant + PARAMS rows (before the first s18_ row)
edit("routers/config_editor.py", 'S18 = f"{BASE}/18sma-agent/config/settings.py"',
     'S18 = f"{BASE}/18sma-agent/config/settings.py"\nS18S = f"{BASE}/18sma-stocks-agent/config/settings.py"',
     "S18S =")
edit("routers/config_editor.py", '    "s18_timeframe":', "".join(ROWS) + '    "s18_timeframe":', '"s18_scan_enabled"' if False else '"s18s_lots"')

# 2. index.html: GROUPS + GMAP
edit("static/index.html", "  sma18:[", "  stocks18:[" + ",".join(f"'{i}'" for i in IDS) + "],\n  sma18:[", "stocks18:[")
s = open(os.path.join(D, "static/index.html"), encoding="utf-8").read()
if "id:'stocks18'" not in s:
    import re
    m = re.search(r"\{id:'sma18',label:'[^']*'\}", s)
    assert m, "GROUPS sma18 entry not found"
    shutil.copy(os.path.join(D, "static/index.html"), os.path.join(D, "static/index.html.bak-s18tab2"))
    s = s.replace(m.group(0), m.group(0) + ",{id:'stocks18',label:'18SMA-Stocks'}", 1)
    open(os.path.join(D, "static/index.html"), "w", encoding="utf-8").write(s)
    print("patched GROUPS")

# 3. card: replace settings link with signals link
edit("static/index.html",
     '<div class="al">Settings</div><div class="av" style="font-size:11px"><a href="/stocks18.html" target="_blank">Open settings &amp; signals</a></div>',
     '<div class="al">Signals</div><div class="av" style="font-size:11px"><a href="/stocks18.html" target="_blank">View signals</a> &middot; settings in Settings tab</div>',
     "View signals")
