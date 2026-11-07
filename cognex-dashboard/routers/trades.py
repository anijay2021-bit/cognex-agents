"""COGNEX Dashboard — Trades Router"""

from fastapi import APIRouter, Query
from typing import Optional
import config
from config import AGENTS
from db_reader import (
    get_today_trades, get_open_trades, get_recent_trades,
    get_pnl_history, get_today_pnl,
    get_recent_decisions, get_agent_summary,
    get_filtered_trades, get_trade_summary,
)

router = APIRouter()


def _stocks18_trades(date_from, date_to, status, strategy, index):
    """18SMA-Stocks signals (agent's own signals.db) shaped like trade rows."""
    import os, sqlite3
    empty = {"trades": [], "summary": {"total": 0, "closed": 0, "open": 0, "wins": 0, "losses": 0, "total_pnl": 0}}
    if index and index.upper() != "ALL":
        return empty
    if strategy and strategy.upper() not in ("ALL", "18SMA-STOCKS"):
        return empty
    path = os.path.join(config.BASE, "18sma-stocks-agent", "signals.db")
    if not os.path.exists(path):
        return empty
    q, a = "SELECT * FROM signals WHERE 1=1", []
    if date_from:
        q += " AND substr(signal_time,1,10)>=?"; a.append(date_from)
    if date_to:
        q += " AND substr(signal_time,1,10)<=?"; a.append(date_to)
    if status and status.upper() != "ALL":
        q += " AND upper(status)=?"; a.append(status.upper())
    q += " ORDER BY id DESC LIMIT 1000"
    c = sqlite3.connect(path, timeout=5)
    c.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in c.execute(q, a)]
    finally:
        c.close()
    out, closed, opn, wins, losses, tot = [], 0, 0, 0, 0, 0.0
    for r in rows:
        st = (r.get("status") or "").upper()
        pnl = r.get("pnl_rs")
        if st == "CLOSED":
            closed += 1
            tot += pnl or 0
            wins += 1 if (pnl or 0) > 0 else 0
            losses += 1 if (pnl or 0) < 0 else 0
        elif st == "OPEN":
            opn += 1
        out.append({
            "symbol": "%s %s %s" % (r.get("symbol"), r.get("strike"), r.get("opt_type")),
            "direction": "BUY", "strategy_used": "18SMA-Stocks",
            "entry_price": r.get("entry_price") or 0, "exit_price": r.get("exit_price"),
            "quantity": (r.get("lots") or 0) * (r.get("lot_size") or 0), "pnl_rs": pnl,
            "target_price": r.get("target_price"),
            "status": st, "mode": "PAPER", "entry_time": r.get("signal_time"),
            "exit_time": r.get("exit_time") or r.get("closed_at") or r.get("exit_ts"),
        })
    return {"trades": out, "summary": {"total": len(rows), "closed": closed, "open": opn,
                                       "wins": wins, "losses": losses, "total_pnl": tot}}


@router.get("/today")
async def today_trades(agent: Optional[str] = None):
    result = {}
    agents = {agent: AGENTS[agent]} if agent and agent in AGENTS else AGENTS
    for aid, cfg in agents.items():
        db = cfg.get("db")
        if db:
            result[aid] = await get_today_trades(db)
    return result


@router.get("/open")
async def open_positions():
    result = {}
    for aid, cfg in AGENTS.items():
        db = cfg.get("db")
        if db:
            result[aid] = await get_open_trades(db)
    return result


@router.get("/filtered")
async def filtered_trades(
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to:   Optional[str] = Query(None, description="YYYY-MM-DD"),
    strategy:  Optional[str] = Query(None),
    status:    Optional[str] = Query(None),
    agent:     Optional[str] = Query(None),
    index:     Optional[str] = Query(None),
):
    """Main trades endpoint — supports date range, strategy, and status filters."""
    result = {}
    agents = {agent: AGENTS[agent]} if agent and agent in AGENTS else AGENTS
    for aid, cfg in agents.items():
        db = cfg.get("db")
        if db:
            result[aid] = {
                "trades":  await get_filtered_trades(db, date_from, date_to, strategy, status, index=index),
                "summary": await get_trade_summary(db, date_from, date_to, strategy, status, index=index),
            }
    if not agent or agent == "stocks18":
        try:
            result["stocks18"] = _stocks18_trades(date_from, date_to, status, strategy, index)
        except Exception as e:
            result["stocks18"] = {"trades": [], "summary": {}, "error": str(e)}
    return result


@router.get("/pnl/today")
async def pnl_today():
    result = {}
    for aid, cfg in AGENTS.items():
        db = cfg.get("db")
        if db:
            result[aid] = await get_today_pnl(db)
    return result


@router.get("/pnl/history")
async def pnl_history(days: int = Query(30, le=365)):
    result = {}
    for aid, cfg in AGENTS.items():
        db = cfg.get("db")
        if db:
            result[aid] = await get_pnl_history(db, days)
    return result


@router.get("/signals/recent")
async def recent_signals(limit: int = Query(50, le=500)):
    result = {}
    for aid, cfg in AGENTS.items():
        db = cfg.get("db")
        if db:
            result[aid] = await get_recent_decisions(db, limit)
    return result


@router.get("/summary")
async def all_summaries():
    result = {}
    for aid, cfg in AGENTS.items():
        db = cfg.get("db")
        if db:
            result[aid] = await get_agent_summary(db, aid)
        else:
            result[aid] = {"agent_id": aid, "today_pnl": 0, "total_trades": 0,
                           "open_positions": 0, "mode": "PAPER", "note": "no DB"}
    return result
