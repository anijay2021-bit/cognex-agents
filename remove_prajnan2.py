"""Remove leftover prajnan RSI2/EMA code paths from the dashboard (config_editor regex branches, index.html options + feed functions). Run on VM."""
import os, re, shutil, subprocess

D = os.path.expanduser("~/cognex-dashboard")


def rw(rel, fn):
    p = os.path.join(D, rel)
    s = open(p, encoding="utf-8").read()
    n = fn(s)
    if n != s:
        if not os.path.exists(p + ".bak-rmpraj2"):
            shutil.copy(p, p + ".bak-rmpraj2")
        open(p, "w", encoding="utf-8").write(n)
        print("patched", rel)


def cfg(s):
    # drop inline_lt / inline_gt branches (read + write); they only served the removed RSI2 params
    s = re.sub(r'    if pattern == "inline_(?:lt|gt)":\n        m = re\.search\(r\'rsi2[^\n]*\n        return m\.group\(1\) if m else None\n', "", s)
    s = re.sub(r"    elif pattern == \"inline_(?:lt|gt)\":\n        content = re\.sub\(r'\(rsi2[^\n]*\n", "", s)
    return s


rw("routers/config_editor.py", cfg)


def html(s):
    s = re.sub(r'^[^\n]*<option value="(?:RSI2|EMA_OBV)">[^\n]*\n', "", s, flags=re.M)
    s = re.sub(r"^function upd[RE]\(p,ts\)\{[^\n]*\n", "", s, flags=re.M)
    return s


rw("static/index.html", html)
for f in ["routers/config_editor.py", "static/index.html"]:
    for i, ln in enumerate(open(os.path.join(D, f), encoding="utf-8"), 1):
        if re.search(r"rsi2|ema\+obv|EMA_OBV|updR|updE|r-spot|'e-9'|id=\"[re]-", ln, re.I):
            print("LEFT", f, i, ln.strip()[:160])
print("compile rc", subprocess.run(["python3", "-m", "py_compile", D + "/routers/config_editor.py"]).returncode)
