"""Remove all remaining prajnan-agent (RSI2 / EMA+OBV / RSI2-v2) traces from the dashboard. Run on VM."""
import os, re, shutil, subprocess

D = os.path.expanduser("~/cognex-dashboard")


def rw(rel, fn):
    p = os.path.join(D, rel)
    if not os.path.exists(p):
        return
    s = open(p, encoding="utf-8").read()
    n = fn(s)
    if n != s:
        if not os.path.exists(p + ".bak-rmpraj"):
            shutil.copy(p, p + ".bak-rmpraj")
        open(p, "w", encoding="utf-8").write(n)
        print("patched", rel)


def cfg(s):
    out = []
    for ln in s.split("\n"):
        st = ln.strip()
        if re.match(r'^"(?:r|e|a2)_[a-z0-9_]+"\s*:', st):
            continue
        if re.match(r"^#.*PRAJNAN", st, re.I):
            continue
        if re.match(r'^(?:P|PENV|PO|PM|A2)\s*=\s*f"\{BASE\}/prajnan', st):
            continue
        out.append(ln)
    return "\n".join(out)


rw("routers/config_editor.py", cfg)


def live(s):
    s = re.sub(r'    "prajnan_ema": \{.*?\n    \},\n', "", s, flags=re.S)
    s = re.sub(r"^[^\n]*(?:prajnan|strategy-level granularity|agent-instructions)[^\n]*\n", "", s, flags=re.M | re.I)
    return s


rw("routers/live_mode.py", live)

# index.html / config.py / ws_hub.py: report leftovers
for f in ["routers/config_editor.py", "routers/live_mode.py", "config.py", "ws_hub.py", "static/index.html"]:
    p = os.path.join(D, f)
    if os.path.exists(p):
        for i, ln in enumerate(open(p, encoding="utf-8"), 1):
            if re.search(r"prajn|rsi2|ema\+obv|\bPENV\b|\bA2\b", ln, re.I):
                print("LEFT", f, i, ln.strip()[:100])
r = subprocess.run(["python3", "-m", "py_compile", D + "/routers/config_editor.py", D + "/routers/live_mode.py"])
print("compile rc", r.returncode)
