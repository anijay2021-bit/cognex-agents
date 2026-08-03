"""
COGNEX Dashboard — Log Parser
Parses loguru-format log lines from all 3 agents into structured dicts.

Loguru format:
  2026-06-25 09:50:24.600 | INFO     | strategies.rsi2_scanner:scan:179 - MESSAGE

Extracts structured data from known message patterns so the React UI can
display live signal panels (RSI2 value, EMA values, Nifty spot, etc.)
"""

import re
from datetime import datetime, timedelta
from typing import Optional

# ─── Base parser ─────────────────────────────────────────────────────────────

LOG_RE = re.compile(
    r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+)'   # timestamp
    r'\s*\|\s*(\w+)\s*\|'                               # level
    r'\s*([^\s:]+:[^\s:]+:\d+)\s*-\s*'                 # module:func:line
    r'(.+)$'                                            # message
)


def parse_line(raw: str, agent_id: str) -> Optional[dict]:
    """
    Parse a single loguru log line.
    Returns a dict with base fields + strategy-specific extracted values.
    Returns None if line doesn't match loguru format.
    """
    m = LOG_RE.match(raw.strip())
    if not m:
        return None

    ts_str, level, location, message = m.groups()
    try:
        _u = datetime.strptime(ts_str[:19], "%Y-%m-%d %H:%M:%S")
        ts_str = (_u + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d %H:%M:%S") + ts_str[19:]
    except Exception:
        pass
    module = location.split(":")[0]

    base = {
        "agent":     agent_id,
        "timestamp": ts_str,
        "level":     level.strip(),
        "module":    module,
        "message":   message.strip(),
        "raw":       raw.rstrip(),
        "parsed":    {},           # Strategy-specific extracted values
        "event":     None,         # Named event type if detected
    }

    # ── RSI2 scanner lines ───────────────────────────────────────────────────
    if "rsi2_scanner" in module:

        # "RSI2 Check | Spot:24049.65 EMA200:24040.47 RSI2:11.96 Time:09:50"
        m2 = re.search(
            r'Spot:([\d.]+).*?EMA200:([\d.]+).*?RSI2:([\d.]+).*?Time:(\d+:\d+)',
            message
        )
        if m2:
            base["parsed"] = {
                "strategy": "RSI2",
                "spot":     float(m2.group(1)),
                "ema200":   float(m2.group(2)),
                "bar_time": m2.group(3) or "",
            }
            base["event"] = "rsi2_check"

        # "RSI2 BUY CE signal" or "RSI2 SELL PE signal"
        elif re.search(r'RSI2.*(BUY|SELL).*(CE|PE)', message, re.I):
            base["event"] = "rsi2_signal"
            side_m = re.search(r'(BUY|SELL)\s+(CE|PE)', message, re.I)
            if side_m:
                base["parsed"] = {
                    "strategy": "RSI2",
                    "action": side_m.group(1).upper(),
                    "option": side_m.group(2).upper(),
                }

        # "RSI2: No signal"
        elif "No signal" in message:
            base["event"] = "no_signal"
            base["parsed"] = {"strategy": "RSI2"}

    # ── EMA+OBV scanner lines ────────────────────────────────────────────────
    elif "ema_obv_scanner" in module:

        # "EMA+OBV | EMA9:23240.46 EMA21:23256.37 Time:09:45"
        m2 = re.search(
            r'EMA9:([\d.]+).*?EMA21:([\d.]+)(?:.*?Time:(\d+:\d+))?',
            message
        )
        if m2:
            ema9, ema21 = float(m2.group(1)), float(m2.group(2))
            base["parsed"] = {
                "strategy": "EMA_OBV",
                "ema9":     ema9,
                "ema21":    ema21,
                "bar_time": m2.group(3) or "",
                "crossover": ema9 > ema21,
            }
            base["event"] = "ema_check"

        # Bullish crossover signal
        elif re.search(r'EMA.*(cross|signal|BUY)', message, re.I):
            base["event"] = "ema_signal"
            base["parsed"] = {"strategy": "EMA_OBV"}

        elif "No cross" in message:
            base["event"] = "no_signal"
            base["parsed"] = {"strategy": "EMA_OBV"}

    # ── Calendar spread lines ────────────────────────────────────────────────
    elif "calendar" in module:
        base["parsed"] = {"strategy": "Calendar"}

        if re.search(r'roll|weekly', message, re.I):
            base["event"] = "calendar_roll"
        elif re.search(r'SL|stop.loss|flip', message, re.I):
            base["event"] = "calendar_sl"
        elif re.search(r'entry|buy|sell', message, re.I):
            base["event"] = "calendar_entry"

    # ── Decision cycle summary ───────────────────────────────────────────────
    elif "__main__" in module and "decision_cycle" in message:
        # "decision_cycle: no signal. Nifty spot=24050"
        spot_m = re.search(r'Nifty spot=?([\d.]+)', message)
        base["event"] = "decision_cycle"
        base["parsed"] = {
            "spot":      float(spot_m.group(1)) if spot_m else None,
            "signal":    "no signal" not in message.lower(),
        }

    # ── Trade events ─────────────────────────────────────────────────────────
    elif re.search(r'ORDER|TRADE|FILL|BUY|SELL', message):
        base["event"] = "trade_event"

    # ── Auth / startup events ────────────────────────────────────────────────
    elif re.search(r'connected|started|Fyers|AngelOne|token', message, re.I):
        base["event"] = "system_event"

    return base


def parse_last_n_lines(log_path: str, n: int = 100) -> list[dict]:
    """Read the last N lines from a log file synchronously (for initial load)."""
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            buf, chunk = b"", 8192
            lines_found = 0
            pos = size

            while pos > 0 and lines_found <= n:
                read = min(chunk, pos)
                pos -= read
                f.seek(pos)
                buf = f.read(read) + buf
                lines_found = buf.count(b"\n")

        raw_lines = buf.decode("utf-8", errors="replace").splitlines()[-n:]
        return raw_lines
    except Exception:
        return []
