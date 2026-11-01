"""18SMA-Stocks: settings + signals API for the COGNEX dashboard."""
import json
import os
import sqlite3
import datetime as dt

from fastapi import APIRouter, HTTPException

import config

router = APIRouter()
AGENT_DIR = f"{config.BASE}/18sma-stocks-agent"
SET_FILE = f"{AGENT_DIR}/settings.json"
DB_FILE = f"{AGENT_DIR}/signals.db"
STATUS_FILE = f"{AGENT_DIR}/status.json"

DEFAULTS = {
    "scan_enabled": True, "lots": 1, "product": "INTRADAY",
    "tgt_mode": "percent", "tgt_value": 30.0, "sl_mode": "percent", "sl_value": 20.0,
    "min_price": 100.0, "sma_period": 18, "signal_mode": "cross",
    "scan_until": "15:15", "squareoff_time": "15:15",
}


def _read_settings():
    s = dict(DEFAULTS)
    try:
        s.update(json.load(open(SET_FILE)))
    except Exception:
        pass
    return s


def _hhmm(v, name):
    try:
        h, m = str(v).split(":")
        assert 0 <= int(h) < 24 and 0 <= int(m) < 60
        return f"{int(h):02d}:{int(m):02d}"
    except Exception:
        raise HTTPException(400, f"{name} must be HH:MM")


def _rows(q, args=()):
    if not os.path.exists(DB_FILE):
        return []
    c = sqlite3.connect(DB_FILE, timeout=5)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(q, args)]
    finally:
        c.close()


@router.get("/signals")
def signals(limit: int = 200, day: str = ""):
    limit = max(1, min(limit, 1000))
    if day:
        return _rows("SELECT * FROM signals WHERE substr(signal_time,1,10)=? ORDER BY id DESC LIMIT ?", (day, limit))
    return _rows("SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,))


@router.get("/summary")
def summary():
    today = (dt.datetime.utcnow() + dt.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    r = _rows(
        "SELECT COUNT(*) n, SUM(status='OPEN') op, "
        "COALESCE(SUM(CASE WHEN status='CLOSED' THEN pnl_rs END),0) pnl "
        "FROM signals WHERE substr(signal_time,1,10)=?", (today,))
    m = _rows(
        "SELECT COALESCE(SUM(CASE WHEN status='CLOSED' THEN pnl_rs END),0) pnl FROM signals "
        "WHERE substr(signal_time,1,7)=?", (today[:7],))
    try:
        st = json.load(open(STATUS_FILE))
    except Exception:
        st = {}
    return {"today": today, "signals_today": (r[0]["n"] if r else 0) or 0, "open": (r[0]["op"] if r else 0) or 0,
            "pnl_today": r[0]["pnl"] if r else 0, "pnl_month": m[0]["pnl"] if m else 0, "status": st}
