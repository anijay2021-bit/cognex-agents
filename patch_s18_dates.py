"""18SMA-Stocks Trades tab: a date range shows only trades entered AND closed inside that range (idempotent).
Still-open trades are shown only when the range reaches today. Run on the VM."""
import os, shutil

D = os.path.expanduser("~/cognex-dashboard")
p = os.path.join(D, "routers/trades.py")
s = open(p, encoding="utf-8").read()

if "_s18_today" in s:
    print("already patched")
else:
    old = '    if date_to:\n        q += " AND substr(signal_time,1,10)<=?"; a.append(date_to)\n'
    new = old + (
        '        import datetime as _dt\n'
        '        _s18_today = (_dt.datetime.utcnow() + _dt.timedelta(hours=5, minutes=30)).date().isoformat()\n'
        '        q += " AND (exit_time IS NULL OR substr(exit_time,1,10)<=?)"; a.append(date_to)\n'
        '        if date_to < _s18_today:\n'
        '            q += " AND status<>\'OPEN\'"\n')
    assert s.count(old) == 1, s.count(old)
    shutil.copy(p, p + ".bak-s18dates")
    open(p, "w", encoding="utf-8").write(s.replace(old, new))
    print("patched")
