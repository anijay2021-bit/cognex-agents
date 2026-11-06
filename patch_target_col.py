"""Add a Target column (before Exit) to the dashboard Trades table (idempotent). Run on the VM."""
import os, shutil

D = os.path.expanduser("~/cognex-dashboard")


def edit(rel, pairs, marker):
    p = os.path.join(D, rel)
    s = open(p, encoding="utf-8").read()
    if marker in s:
        print("already patched:", rel)
        return
    for old, new in pairs:
        assert old in s, (rel, old[:50])
        s = s.replace(old, new)
    shutil.copy(p, p + ".bak-target")
    open(p, "w", encoding="utf-8").write(s)
    print("patched:", rel)


TG = "(v=>v?'₹'+Number(v).toFixed(2):'—')(t.target_price??t.target??t.tp_price??t.tp)"

edit("static/index.html", [
    ("<th>Entry ₹</th><th>Exit ₹</th>", "<th>Entry ₹</th><th>Target ₹</th><th>Exit ₹</th>"),
    ("<td>${t.exit_price?'₹'+t.exit_price.toFixed(2):'—'}</td>",
     "<td style=\"color:#2563eb\">${" + TG + "}</td>\n        <td>${t.exit_price?'₹'+t.exit_price.toFixed(2):'—'}</td>"),
    ('colspan="11"', 'colspan="12"'),
    (".bpa{background:#eff6ff;color:#1d4ed8}", ".bpa{background:#eff6ff;color:#1d4ed8}.bv{background:#f1f5f9;color:#94a3b8}"),
], "Target ₹")

edit("routers/trades.py", [
    ('"quantity": (r.get("lots") or 0) * (r.get("lot_size") or 0), "pnl_rs": pnl,',
     '"quantity": (r.get("lots") or 0) * (r.get("lot_size") or 0), "pnl_rs": pnl,\n            "target_price": r.get("target_price"),'),
], '"target_price": r.get("target_price")')
