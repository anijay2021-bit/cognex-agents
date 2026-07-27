"""
COGNEX Dashboard — Database Reader
Read-only async queries against the existing cognex_agent.db files.
Uses aiosqlite so it never blocks the FastAPI event loop.
Never writes to the agent databases.
"""

import aiosqlite
from datetime import datetime, date
from typing import Optional


async def _query(db_path: str, sql: str, params: tuple = ()) -> list[dict]:
    """Run a SELECT against any agent DB and return list of dicts."""
    try:
        async with aiosqlite.connect(f"file:{db_path}?mode=ro", uri=True) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(sql, params) as cur:
                rows = await cur.fetchall()
                return [dict(r) for r in rows]
    except Exception as e:
        return []


# ─── Trades ──────────────────────────────────────────────────────────────────

async def get_today_trades(db_path: str) -> list[dict]:
    today = str(date.today())
    return await _query(
        db_path,
        """SELECT id, order_id, symbol, instrument_type, underlying, strike, expiry,
                  direction, quantity, entry_price, exit_price,
                  entry_time, exit_time, pnl_rs, status,
                  strategy_used, reason, mode, stop_loss_rs
           FROM trades
           WHERE entry_time >= ?
           ORDER BY entry_time DESC""",
        (today,),
    )


async def get_open_trades(db_path: str) -> list[dict]:
    return await _query(
        db_path,
        """SELECT id, order_id, symbol, instrument_type, underlying, strike, expiry,
                  direction, quantity, entry_price, stop_loss_rs,
                  entry_time, status, strategy_used, mode
           FROM trades
           WHERE status = 'OPEN'
           ORDER BY entry_time DESC""",
    )


async def get_recent_trades(db_path: str, limit: int = 20) -> list[dict]:
    return await _query(
        db_path,
        """SELECT id, symbol, direction, quantity, entry_price, exit_price,
                  entry_time, exit_time, pnl_rs, status, strategy_used, mode
           FROM trades
           ORDER BY entry_time DESC LIMIT ?""",
        (limit,),
    )


# ─── Daily P&L ────────────────────────────────────────────────────────────────

async def get_today_pnl(db_path: str) -> dict:
    today = str(date.today())
    # Aggregate directly from trades table (daily_pnl table is unused)
    trades = await get_today_trades(db_path)
    wins   = [t for t in trades if (t.get("pnl_rs") or 0) > 0]
    losses = [t for t in trades if (t.get("pnl_rs") or 0) < 0]
    return {
        "date":           today,
        "total_trades":   len(trades),
        "winning_trades": len(wins),
        "losing_trades":  len(losses),
        "gross_pnl_rs":   sum(t.get("pnl_rs") or 0 for t in trades),
        "net_pnl_rs":     sum(t.get("pnl_rs") or 0 for t in trades),
        "mode":           trades[0].get("mode", "PAPER") if trades else "PAPER",
    }


async def get_pnl_history(db_path: str, days: int = 30) -> list[dict]:
    return await _query(
        db_path,
        """SELECT date(exit_time) AS date,
                  COUNT(*) AS total_trades,
                  SUM(CASE WHEN pnl_rs > 0 THEN 1 ELSE 0 END) AS winning_trades,
                  SUM(CASE WHEN pnl_rs < 0 THEN 1 ELSE 0 END) AS losing_trades,
                  ROUND(SUM(pnl_rs), 2) AS gross_pnl_rs,
                  ROUND(SUM(pnl_rs), 2) AS net_pnl_rs,
                  MAX(mode) AS mode
           FROM trades
           WHERE status = 'CLOSED' AND exit_time IS NOT NULL AND pnl_rs IS NOT NULL
           GROUP BY date(exit_time)
           ORDER BY date(exit_time) DESC LIMIT ?""",
        (days,),
    )


# ─── Agent Decisions / Signal History ────────────────────────────────────────

async def get_recent_decisions(db_path: str, limit: int = 50) -> list[dict]:
    return await _query(
        db_path,
        """SELECT id, timestamp, market_regime, nifty_spot, vix, pcr_nifty,
                  decision, reasoning, trade_id
           FROM agent_decisions
           ORDER BY timestamp DESC LIMIT ?""",
        (limit,),
    )


async def get_last_decision(db_path: str) -> Optional[dict]:
    rows = await _query(
        db_path,
        """SELECT timestamp, market_regime, nifty_spot, vix, pcr_nifty,
                  decision, reasoning
           FROM agent_decisions
           ORDER BY timestamp DESC LIMIT 1""",
    )
    return rows[0] if rows else None


# ─── Agent Memory (key-value store) ──────────────────────────────────────────

async def get_agent_memory(db_path: str) -> list[dict]:
    return await _query(
        db_path,
        """SELECT key, value, confidence, last_updated, times_observed
           FROM agent_memory
           ORDER BY last_updated DESC""",
    )


# ─── Summary (used for dashboard home cards) ─────────────────────────────────

async def get_agent_summary(db_path: str, agent_id: str) -> dict:
    """Single call that returns everything needed for an agent's summary card."""
    pnl     = await get_today_pnl(db_path)
    open_t  = await get_open_trades(db_path)
    last_d  = await get_last_decision(db_path)

    return {
        "agent_id":       agent_id,
        "today_pnl":      round(pnl.get("net_pnl_rs") or 0, 2),
        "total_trades":   pnl.get("total_trades") or 0,
        "winning_trades": pnl.get("winning_trades") or 0,
        "losing_trades":  pnl.get("losing_trades") or 0,
        "open_positions": len(open_t),
        "mode":           pnl.get("mode", "PAPER"),
        "last_signal":    last_d.get("decision") if last_d else "—",
        "last_nifty":     last_d.get("nifty_spot") if last_d else None,
        "last_vix":       last_d.get("vix") if last_d else None,
        "last_activity":  last_d.get("timestamp") if last_d else None,
    }


async def get_filtered_trades(
    db_path: str,
    date_from: str = None,
    date_to: str = None,
    strategy: str = None,
    status: str = None,
    limit: int = 1000,
) -> list[dict]:
    """Filtered trade query — used by the Trades tab."""
    conditions = ["1=1"]
    params = []

    if date_from:
        conditions.append("entry_time >= ?")
        params.append(f"{date_from}T00:00:00")
    if date_to:
        conditions.append("entry_time <= ?")
        params.append(f"{date_to}T23:59:59.999999")
    if strategy and strategy.upper() != "ALL":
        conditions.append("strategy_used = ?")
        params.append(strategy)
    if status and status.upper() != "ALL":
        conditions.append("status = ?")
        params.append(status.upper())

    where = " AND ".join(conditions)
    return await _query(
        db_path,
        f"""SELECT id, symbol, direction, quantity, entry_price, exit_price,
                   entry_time, exit_time, pnl_rs, status, strategy_used, mode, reason
            FROM trades
            WHERE {where}
            ORDER BY entry_time DESC LIMIT ?""",
        tuple(params + [limit]),
    )


async def get_trade_summary(
    db_path: str,
    date_from: str = None,
    date_to: str = None,
    strategy: str = None,
    status: str = None,
) -> dict:
    """Aggregate summary for the current filter set."""
    trades = await get_filtered_trades(db_path, date_from, date_to, strategy, status, limit=10000)
    total  = len(trades)
    closed = [t for t in trades if t.get("status") == "CLOSED"]
    wins   = [t for t in closed if (t.get("pnl_rs") or 0) > 0]
    losses = [t for t in closed if (t.get("pnl_rs") or 0) < 0]
    pnl    = sum(t.get("pnl_rs") or 0 for t in closed)
    return {
        "total":    total,
        "closed":   len(closed),
        "open":     total - len(closed),
        "wins":     len(wins),
        "losses":   len(losses),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "total_pnl": round(pnl, 2),
    }
