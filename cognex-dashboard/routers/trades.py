"""COGNEX Dashboard — Trades Router"""

from fastapi import APIRouter, Query
from typing import Optional
from config import AGENTS
from db_reader import (
    get_today_trades, get_open_trades, get_recent_trades,
    get_pnl_history, get_today_pnl,
    get_recent_decisions, get_agent_summary,
    get_filtered_trades, get_trade_summary,
)

router = APIRouter()


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
):
    """Main trades endpoint — supports date range, strategy, and status filters."""
    result = {}
    agents = {agent: AGENTS[agent]} if agent and agent in AGENTS else AGENTS
    for aid, cfg in agents.items():
        db = cfg.get("db")
        if db:
            result[aid] = {
                "trades":  await get_filtered_trades(db, date_from, date_to, strategy, status),
                "summary": await get_trade_summary(db, date_from, date_to, strategy, status),
            }
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
