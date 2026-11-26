"""Remove Trishul, Nitin, Prajnan Calendar and Pocket Pivot from the COGNEX dashboard (idempotent).
Run on the VM:  python3 remove_agents_dashboard.py   (edits ~/cognex-dashboard, keeps .bak-rmagents backups)"""
import os, re, shutil

D = os.path.expanduser("~/cognex-dashboard")


def edit(rel, fn, label):
    p = os.path.join(D, rel)
    if not os.path.exists(p):
        print("missing:", rel)
        return
    s = open(p, encoding="utf-8").read()
    n, info = fn(s)
    if n == s:
        print("no change:", rel, "-", label)
        return
    if not os.path.exists(p + ".bak-rmagents"):
        shutil.copy(p, p + ".bak-rmagents")
    open(p, "w", encoding="utf-8").write(n)
    print("patched:", rel, "-", info)


# 1. config.py - AGENTS entries
def f_config(s):
    n, c = re.subn(r'    "(?:prajnan_calendar|nitin|pocketpivot)": \{.*?\n    \},\n', "", s, flags=re.S)
    return n, "%d agent blocks removed" % c


edit("config.py", f_config, "agents")


# 2. config_editor.py - c_*, n_*, pp_* params, path constants, comments
def f_cfg(s):
    lines, out, c = s.split("\n"), [], 0
    for ln in lines:
        st = ln.strip()
        if re.match(r'^"(?:c|n|pp)_[a-z0-9_]+"\s*:', st):
            c += 1
            continue
        if re.match(r'^(?:T|NS|PPE)\s*=\s*f"\{BASE\}/(?:trishul-agent|nitin-agent|pocket-pivot-agent)', st):
            c += 1
            continue
        if re.match(r"^#.*(TRISHUL|PRAJNAN CALENDAR|NITIN swing|POCKET PIVOT)", st):
            c += 1
            continue
        out.append(ln)
    return "\n".join(out), "%d lines removed" % c


edit("routers/config_editor.py", f_cfg, "params")


# 3. live_mode.py - groups prajnan_calendar, trishul; drop the stale agent-instructions helper
def f_live(s):
    n, c1 = re.subn(r'    "(?:prajnan_calendar|trishul)": \{.*?\n    \},\n', "", s, flags=re.S)
    n, c2 = re.subn(r'\n\n@router\.get\("/agent-instructions"\).*\Z', "\n", n, flags=re.S)
    return n, "%d groups, %d helper endpoint removed" % (c1, c2)


edit("routers/live_mode.py", f_live, "groups")


# 4. ws_hub.py - trishul journal tail
def f_ws(s):
    n, c1 = re.subn(r"async def tail_trishul_journal\(\):.*?(?=\nasync def broadcast_agent_statuses)", "", s, flags=re.S)
    n, c2 = re.subn(r"    asyncio\.create_task\(tail_trishul_journal\(\)\)\n", "", n)
    return n, "%d function, %d task removed" % (c1, c2)


edit("ws_hub.py", f_ws, "trishul tail")


# 5. static/index.html
def f_html(s):
    c = 0
    n, k = re.subn(r'    <div class="ac" id="card-(?:nitin|pocketpivot|prajnan_calendar)">.*?\n(?=    <div class="ac" id="card-)', "", s, flags=re.S)
    c += k
    n, k = re.subn(r"^  \{id:'(?:prajnan_cal|nitin|pocketpivot)',label:'[^']*'\},\n", "", n, flags=re.M)
    c += k
    n, k = re.subn(r"^  (?:prajnan_cal|nitin|pocketpivot):\[[^\]]*\],\n", "", n, flags=re.M)
    c += k
    n, k = re.subn(r'<div class="tt active" id="ttpn" onclick="setTT\(\'nitin\',this\)">Nitin</div>', "", n)
    c += k
    n, k = re.subn(r'<div class="tt" id="ttp18" onclick="setTT\(\'sma18\',this\)">18SMA</div>',
                   '<div class="tt active" id="ttp18" onclick="setTT(\'sma18\',this)">18SMA</div>', n)
    c += k
    n, k = re.subn(r"tt:'nitin'", "tt:'sma18'", n)
    c += k
    n, k = re.subn(r'<div class="lfb" onclick="setF2\(\'nitin\',this\)">Nitin</div>', "", n)
    c += k
    n, k = re.subn(r'<div class="ls">Prajñān · Prajñān2 · Nitin · Calendar Agent \+ Pocket Pivot</div>',
                   '<div class="ls">18SMA · VWAP · 18SMA-Stocks</div>', n)
    c += k
    return n, "%d edits" % c


edit("static/index.html", f_html, "cards/tabs/settings")
print("done")
