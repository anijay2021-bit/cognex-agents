"""SQLite store for vwap-agent. Trades table mirrors the cognex-dashboard
schema, plus sl_price/target_price (absolute prices) since each VWAP
sub-position carries its own individually-computed target (VWAP/+1SD/+2SD)
rather than one global SL/target formula."""
import sqlite3
import datetime as dt
from config import settings


def conn():
    c = sqlite3.connect(settings.DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS trades(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id TEXT, symbol TEXT, instrument_type TEXT, underlying TEXT,
            strike REAL, expiry TEXT, direction TEXT, quantity INTEGER,
            entry_price REAL, exit_price REAL, entry_time TEXT, exit_time TEXT,
            pnl_rs REAL, status TEXT, strategy_used TEXT, reason TEXT,
            mode TEXT, stop_loss_rs REAL, signal_id TEXT,
            sl_price REAL, target_price REAL)""")


def n_open(underlying=None):
    with conn() as c:
        if underlying:
            return c.execute(
                "SELECT COUNT(*) FROM trades WHERE status='OPEN' AND underlying=?",
                (underlying,)).fetchone()[0]
        return c.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0]


def signal_traded(underlying, signal_id):
    """True if this excursion has already produced a trade (open or closed) --
    checked as a prefix match since each excursion opens up to 3 sub-position
    rows suffixed -T1/-T2/-T3."""
    if not signal_id:
        return False
    with conn() as c:
        row = c.execute(
            "SELECT 1 FROM trades WHERE underlying=? AND signal_id LIKE ? LIMIT 1",
            (underlying, f"{signal_id}%")).fetchone()
        return row is not None


def open_trade(order_id, symbol, underlying, strike, expiry, direction, qty,
               entry_price, entry_time, sl_price, target_price, reason, signal_id=None):
    risk = round(abs(entry_price - sl_price) * qty, 2)
    with conn() as c:
        cur = c.execute(
            """INSERT INTO trades(order_id,symbol,instrument_type,underlying,
                strike,expiry,direction,quantity,entry_price,entry_time,status,
                strategy_used,reason,mode,stop_loss_rs,signal_id,sl_price,target_price)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (order_id, symbol, "OPT", underlying, strike, expiry, direction, qty,
             entry_price, entry_time, "OPEN", "VWAP", reason, settings.MODE, risk,
             signal_id, sl_price, target_price))
        return cur.lastrowid


def open_trades():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM trades WHERE status='OPEN'")]


def close_trade(tid, exit_price, exit_time, reason):
    with conn() as c:
        t = c.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
        pnl = round((exit_price - t["entry_price"]) * t["quantity"], 2)
        c.execute(
            """UPDATE trades SET exit_price=?, exit_time=?, pnl_rs=?,
                status='CLOSED', reason=? WHERE id=?""",
            (exit_price, exit_time, pnl, reason, tid))
        return pnl


def today_pnl():
    today = dt.date.today().isoformat()
    with conn() as c:
        rows = c.execute(
            "SELECT pnl_rs FROM trades WHERE status='CLOSED' AND entry_time LIKE ?",
            (f"{today}%",)).fetchall()
        return sum(r["pnl_rs"] or 0 for r in rows)
