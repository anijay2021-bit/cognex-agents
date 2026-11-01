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


@router.get("/settings")
def get_settings():
    return _read_settings()


@router.post("/settings")
def save_settings(body: dict):
    s = _read_settings()
    try:
        if "lots" in body:
            s["lots"] = int(body["lots"])
            if s["lots"] < 1:
                raise ValueError("lots must be >= 1")
        if "product" in body:
            p = str(body["product"]).upper()
            if p not in ("INTRADAY", "CARRYFORWARD"):
                raise ValueError("product must be INTRADAY or CARRYFORWARD")
            s["product"] = p
        for k in ("tgt_mode", "sl_mode"):
            if k in body:
                m = str(body[k]).lower()
                if m not in ("percent", "absolute"):
                    raise ValueError(f"{k} must be percent or absolute")
                s[k] = m
        for k in ("tgt_value", "sl_value", "min_price"):
            if k in body:
                s[k] = float(body[k])
                if s[k] <= 0:
                    raise ValueError(f"{k} must be > 0")
        if s["sl_mode"] == "percent" and s["sl_value"] >= 100:
            raise ValueError("SL percent must be below 100")
        if "sma_period" in body:
            s["sma_period"] = int(body["sma_period"])
            if not 2 <= s["sma_period"] <= 200:
                raise ValueError("sma_period must be 2-200")
        if "signal_mode" in body:
            m = str(body["signal_mode"]).lower()
            if m not in ("cross", "always"):
                raise ValueError("signal_mode must be cross or always")
            s["signal_mode"] = m
        if "scan_enabled" in body:
            s["scan_enabled"] = bool(body["scan_enabled"])
        for k in ("scan_until", "squareoff_time"):
            if k in body:
                s[k] = _hhmm(body[k], k)
    except HTTPException:
        raise
    except (ValueError, TypeError) as e:
        raise HTTPException(400, str(e))
    tmp = SET_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, SET_FILE)
    return s


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
