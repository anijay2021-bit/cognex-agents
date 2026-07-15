#!/usr/bin/env python3
"""
pocket_pivot_agent.py
=====================
"Pocket Pivot" agent: scrapes Nitin's Chartink screener and sends the surviving
tickers (Symbol, Price, % Change) to Telegram. No broker / execution code.

Run:
    python3 pocket_pivot_agent.py

Credentials come from environment variables - never hardcode secrets here:
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

Dependencies:
    pip3 install requests
"""

import os
import re
import sys
import json
import logging
from datetime import date, datetime, time, timedelta, timezone

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)


class PocketPivotAgent:
    """Chartink pocket-pivot scan -> Telegram alert."""

    name = "Pocket Pivot"

    SEEN_FILE = "/home/anijay2021/pocket_pivot_seen.json"
    SCREENER_URL = "https://chartink.com/screener/pocket-pivot-scan-atfinallynitin"
    PROCESS_URL = "https://chartink.com/screener/process"

    # ---- Exact clauses from Nitin's screener (process payload), verbatim ---- #
    SCAN_CLAUSE = """( {33489} ( ( {33489} (  daily volume >  daily max( 10 ,  daily volume *  daily count( 1, 1 where  daily close <  daily open ) ) or( {33489} ( ( {33489} ( ( {33489} (  1 day ago close >  2 days ago close ) ) or( {33489} (  1 day ago close <  2 days ago close and  1 day ago volume <  daily volume ) ) ) ) and( {33489} ( ( {33489} (  2 days ago close >  3 days ago close ) ) or( {cash} (  2 days ago close <  3 days ago close and  2 days ago volume <  daily volume ) ) ) ) and( {33489} ( ( {33489} (  3 days ago close >  4 days ago close ) ) or( {33489} (  3 days ago close <  4 days ago close and  3 days ago volume <  daily volume ) ) ) ) and( {33489} ( ( {33489} (  4 days ago close >  5 days ago close ) ) or( {33489} (  4 days ago close <  5 days ago close and  4 days ago volume <  daily volume ) ) ) ) and( {33489} ( ( {33489} (  5 days ago close >  6 days ago close ) ) or( {33489} (  5 days ago close <  6 days ago close and  5 days ago volume <  daily volume ) ) ) ) and( {33489} ( ( {33489} (  6 days ago close >  7 days ago close ) ) or( {33489} (  6 days ago close <  7 days ago close and  6 days ago volume <  daily volume ) ) ) ) and( {33489} ( ( {33489} (  7 days ago close >  8 days ago close ) ) or( {33489} (  7 days ago close <  8 days ago close and  7 days ago volume <  daily volume ) ) ) ) and( {33489} ( ( {33489} (  8 days ago close >  9 days ago close ) ) or( {33489} (  8 days ago close <  9 days ago close and  8 days ago volume <  daily volume ) ) ) ) and( {33489} ( ( {33489} (  9 days ago close >  10 days ago close ) ) or( {33489} (  9 days ago close <  10 days ago close and  9 days ago volume <  daily volume ) ) ) ) and( {33489} ( ( {33489} (  10 days ago close >  11 days ago close ) ) or( {33489} (  10 days ago close <  11 days ago close and  10 days ago volume <  daily volume ) ) ) ) ) ) ) ) and  daily close >=  1 day ago close and( {33489} (  daily close >=  20 and  market cap >=  100 and  weekly sma(  weekly volume , 10 ) >  100000 and  daily sma(  daily volume , 50 ) *  daily close >  5000000 ) ) and( {33489} (  daily close >  daily sma(  daily close , 50 ) and  daily close >  daily sma(  daily close , 200 ) and  daily close >  1.3 *  weekly min( 52 ,  weekly low ) and  daily close >  0.75 *  weekly max( 52 ,  weekly high ) and  daily low <=  daily wma(  daily close , 10 ) ) ) ) )"""

    DEBUG_CLAUSE = """groupcount( 1 where      daily volume >  daily max( 10 ,  daily volume *  daily count( 1, 1 where  daily close <  daily open ) )),groupcount( 1 where                  1 day ago close >  2 days ago close),groupcount( 1 where                  1 day ago close <  2 days ago close),groupcount( 1 where                  1 day ago volume <  daily volume),groupcount( 1 where                  2 days ago close >  3 days ago close),groupcount( 1 where                  2 days ago close <  3 days ago close),groupcount( 1 where                  2 days ago volume <  daily volume),groupcount( 1 where                  3 days ago close >  4 days ago close),groupcount( 1 where                  3 days ago close <  4 days ago close),groupcount( 1 where                  3 days ago volume <  daily volume),groupcount( 1 where                  4 days ago close >  5 days ago close),groupcount( 1 where                  4 days ago close <  5 days ago close),groupcount( 1 where                  4 days ago volume <  daily volume),groupcount( 1 where                  5 days ago close >  6 days ago close),groupcount( 1 where                  5 days ago close <  6 days ago close),groupcount( 1 where                  5 days ago volume <  daily volume),groupcount( 1 where                  6 days ago close >  7 days ago close),groupcount( 1 where                  6 days ago close <  7 days ago close),groupcount( 1 where                  6 days ago volume <  daily volume),groupcount( 1 where                  7 days ago close >  8 days ago close),groupcount( 1 where                  7 days ago close <  8 days ago close),groupcount( 1 where                  7 days ago volume <  daily volume),groupcount( 1 where                  8 days ago close >  9 days ago close),groupcount( 1 where                  8 days ago close <  9 days ago close),groupcount( 1 where                  8 days ago volume <  daily volume),groupcount( 1 where                  9 days ago close >  10 days ago close),groupcount( 1 where                  9 days ago close <  10 days ago close),groupcount( 1 where                  9 days ago volume <  daily volume),groupcount( 1 where                  10 days ago close >  11 days ago close),groupcount( 1 where                  10 days ago close <  11 days ago close),groupcount( 1 where                  10 days ago volume <  daily volume),groupcount( 1 where  daily close >=  1 day ago close),groupcount( 1 where      daily close >=  20),groupcount( 1 where      market cap >=  100),groupcount( 1 where      weekly sma(  weekly volume , 10 ) >  100000),groupcount( 1 where      daily sma(  daily volume , 50 ) *  daily close >  5000000),groupcount( 1 where      daily close >  daily sma(  daily close , 50 )),groupcount( 1 where      daily close >  daily sma(  daily close , 200 )),groupcount( 1 where      daily close >  1.3 *  weekly min( 52 ,  weekly low )),groupcount( 1 where      daily close >  0.75 *  weekly max( 52 ,  weekly high )),groupcount( 1 where      daily low <=  daily wma(  daily close , 10 ))"""

    COLUMN_CLAUSE = """ Daily Close as 'scan-column-default-close',  Daily "close - 1 candle ago close / 1 candle ago close * 100" as 'scan-column-default-percent-change', filternumber( daily close >  1 day ago close,1) as 'default-percent-change-conditional-filters-color',  Daily Volume as 'scan-column-default-volume'"""

    BASE_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self):
        self.log = logging.getLogger("pocket_pivot")
        self.telegram_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    # ------------------------------------------------------------------ #
    # Chartink scrape
    # ------------------------------------------------------------------ #
    def fetch_screener_results(self):
        session = requests.Session()
        session.headers.update(self.BASE_HEADERS)

        resp = session.get(self.SCREENER_URL, timeout=30)
        resp.raise_for_status()

        m = re.search(r'<meta[^>]*name="csrf-token"[^>]*content="([^"]+)"', resp.text) \
            or re.search(r'<meta[^>]*content="([^"]+)"[^>]*name="csrf-token"', resp.text)
        if not m:
            raise RuntimeError("Could not locate csrf-token on the screener page.")
        csrf_token = m.group(1)
        self.log.info("csrf-token acquired.")

        headers = {
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRF-TOKEN": csrf_token,
            "Referer": self.SCREENER_URL,
            "Origin": "https://chartink.com",
        }
        payload = {
            "scan_clause": self.SCAN_CLAUSE,
            "debug_clause": self.DEBUG_CLAUSE,
            "column_clause": self.COLUMN_CLAUSE,
        }
        r = session.post(self.PROCESS_URL, headers=headers, data=payload, timeout=30)
        r.raise_for_status()
        data = r.json().get("data", [])
        self.log.info("Screener returned %d row(s).", len(data))
        return data

    def format_alert(self, rows):
        if not rows:
            return f"{self.name} scan: no stocks passed today."
        lines = [f"\U0001F4C8 *{self.name}* - {len(rows)} hit(s)", ""]
        for row in rows:
            symbol = row.get("nsecode") or row.get("bsecode") or row.get("name", "?")
            price = row.get("scan-column-default-close", row.get("close", "-"))
            chg = row.get("scan-column-default-percent-change", row.get("per_chg", "-"))
            lines.append(f"`{symbol:<12}`  Rs {price}  ({chg}%)")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Telegram dispatch
    # ------------------------------------------------------------------ #
    def send_telegram(self, text):
        if not self.telegram_token or not self.telegram_chat_id:
            self.log.warning("Telegram credentials missing; skipping. Message:\n%s", text)
            return
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        resp = requests.post(url, data=payload, timeout=15)
        if resp.ok:
            self.log.info("Telegram alert sent.")
        else:
            self.log.error("Telegram send failed (%s): %s", resp.status_code, resp.text)

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # Per-day dedup
    # ------------------------------------------------------------------ #
    def _load_seen(self):
        try:
            with open(self.SEEN_FILE) as fh:
                d = json.load(fh)
            if d.get("date") == date.today().isoformat():
                return set(d.get("symbols", []))
        except (OSError, ValueError):
            pass
        return set()

    def _save_seen(self, symbols):
        try:
            with open(self.SEEN_FILE, "w") as fh:
                json.dump({"date": date.today().isoformat(),
                           "symbols": sorted(symbols)}, fh)
        except OSError as exc:
            self.log.error("Could not write seen-file: %s", exc)

    def _filter_new(self, rows):
        seen = self._load_seen()
        fresh = [r for r in rows
                 if (r.get("nsecode") or r.get("bsecode") or r.get("name")) not in seen]
        if fresh:
            for r in fresh:
                seen.add(r.get("nsecode") or r.get("bsecode") or r.get("name"))
            self._save_seen(seen)
        return fresh

    def _within_market_hours(self):
        ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        if ist.weekday() >= 5:
            return False
        return time(9, 15) <= ist.time() <= time(15, 30)

    def run(self):
        self.log.info("%s agent starting.", self.name)
        if not self._within_market_hours():
            self.log.info("Outside market hours (09:15-15:30 IST, Mon-Fri). Exiting.")
            return
        try:
            rows = self.fetch_screener_results()
        except requests.exceptions.RequestException as exc:
            # transient network/timeout/rate-limit: log only, no Telegram spam
            self.log.warning("Screener fetch failed (transient): %s", exc)
            return
        except Exception as exc:  # noqa: BLE001
            self.log.error("Screener fetch failed: %s", exc)
            self.send_telegram(f"\u26A0\uFE0F {self.name} agent error: {exc}")
            sys.exit(1)
        fresh = self._filter_new(rows)
        self.log.info("%d new (of %d total) after dedup.", len(fresh), len(rows))
        if fresh:
            self.send_telegram(self.format_alert(fresh))
        else:
            self.log.info("Nothing new to alert today.")
        self.log.info("Run complete.")


if __name__ == "__main__":
    PocketPivotAgent().run()
