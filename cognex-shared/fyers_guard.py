"""Shared Fyers REST budget for all COGNEX agents (Standard plan: 5/s, 50/min, 5000/day).
Every REST call must call acquire() first. State is one JSON file guarded by flock."""
import json, os, time, fcntl, datetime as dt

PATH = os.path.expanduser("~/cognex-shared/fyers_usage.json")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MIN_GAP = 0.3
PER_MIN = 40
DAILY = 5000
CAPS = {"entry": 4000, "exit": 4900}
ALERT_AT = (0.7, 0.9)


def _load(f):
    f.seek(0)
    s = f.read()
    try:
        d = json.loads(s) if s else {}
    except Exception:
        d = {}
    today = dt.datetime.now(IST).date().isoformat()
    if d.get("date") != today:
        d = {"date": today, "day": 0, "recent": [], "alerts": []}
    return d


def used():
    try:
        with open(PATH, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            return _load(f)["day"]
    except Exception:
        return -1


def _decide(d, now, cap, kind, msgs):
    if d["day"] >= cap:
        if "cap-" + kind not in d["alerts"]:
            d["alerts"].append("cap-" + kind)
            msgs.append(f"Fyers daily budget reached for {kind} calls ({d['day']}/{DAILY}). Agents throttled.")
        return -1, False
    last = d["recent"][-1] if d["recent"] else 0
    if now - last < MIN_GAP:
        return MIN_GAP - (now - last), False
    if len(d["recent"]) >= PER_MIN:
        return 60 - (now - d["recent"][0]) + 0.05, False
    d["recent"].append(now)
    d["day"] += 1
    for th in ALERT_AT:
        if d["day"] >= th * DAILY and str(th) not in d["alerts"]:
            d["alerts"].append(str(th))
            msgs.append(f"Fyers API usage {d['day']}/{DAILY} ({int(th * 100)}% of daily quota).")
    return 0, True


def acquire(kind="entry", alert=None):
    """Block until a REST call is allowed. False if today's budget for this kind is spent."""
    cap = CAPS.get(kind, CAPS["entry"])
    while True:
        msgs = []
        with open(PATH, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            d = _load(f)
            now = time.time()
            d["recent"] = [t for t in d["recent"] if now - t < 60]
            wait, ok = _decide(d, now, cap, kind, msgs)
            f.truncate(0)
            f.write(json.dumps(d))
        for m in msgs:
            try:
                if alert:
                    alert(m)
            except Exception:
                pass
        if wait < 0:
            return False
        if ok:
            return True
        time.sleep(max(wait, 0.05))
