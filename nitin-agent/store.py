"""SQLite store — trades table matches the cognex-dashboard schema exactly."""
import sqlite3
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
            mode TEXT, stop_loss_rs REAL)""")
        c.execute("""CREATE TABLE IF NOT EXISTS signals(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created TEXT, symbol TEXT, setup TEXT, entry REAL, stop REAL,
            target1 REAL, target2 REAL, qty INTEGER, status TEXT,
            valid_until TEXT, notes TEXT)""")


def add_signal(created, sig, qty, valid_until):
    with conn() as c:
        c.execute("""INSERT INTO signals(created,symbol,setup,entry,stop,target1,
            target2,qty,status,valid_until,notes) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (created, sig.symbol, sig.setup, sig.entry, sig.stop, sig.target1,
             sig.target2, qty, "PENDING", valid_until, sig.notes))


def pending_signals():
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM signals WHERE status='PENDING'")]


def set_signal_status(sid, status):
    with conn() as c:
        c.execute("UPDATE signals SET status=? WHERE id=?", (status, sid))


def has_pending_or_open(symbol):
    with conn() as c:
        n1 = c.execute("SELECT COUNT(*) FROM signals WHERE symbol=? AND status='PENDING'",
                       (symbol,)).fetchone()[0]
        n2 = c.execute("SELECT COUNT(*) FROM trades WHERE symbol=? AND status='OPEN'",
                       (symbol,)).fetchone()[0]
    return n1 + n2 > 0


def open_trades():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM trades WHERE status='OPEN'")]


def n_open():
    with conn() as c:
        return c.execute("SELECT COUNT(*) FROM trades WHERE status='OPEN'").fetchone()[0]


def open_trade(sig_row, entry_price, entry_time):
    risk = (entry_price - sig_row["stop"]) * sig_row["qty"]
    with conn() as c:
        cur = c.execute("""INSERT INTO trades(order_id,symbol,instrument_type,underlying,
            strike,expiry,direction,quantity,entry_price,entry_time,status,
            strategy_used,reason,mode,stop_loss_rs)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (f"NITIN-PAPER-{sig_row['id']}", sig_row["symbol"], "EQ", sig_row["symbol"],
             None, None, "BUY", sig_row["qty"], entry_price, entry_time, "OPEN",
             f"NitinSwing:{sig_row['setup']}", sig_row["notes"], settings.MODE,
             round(risk, 2)))
        return cur.lastrowid


def close_trade(tid, exit_price, exit_time, reason):
    with conn() as c:
        t = c.execute("SELECT * FROM trades WHERE id=?", (tid,)).fetchone()
        pnl = round((exit_price - t["entry_price"]) * t["quantity"], 2)
        c.execute("""UPDATE trades SET exit_price=?, exit_time=?, pnl_rs=?,
            status='CLOSED', reason=? WHERE id=?""",
            (exit_price, exit_time, pnl, reason, tid))
        return pnl
