"""
fno_backtest.py
---------------
Backtests RSI2 + SMA200 strategy on all NSE F&O stocks using Fyers daily data.

Entry : Price > Daily SMA(200) AND Daily RSI(2) < 5
Exit  : Daily RSI(2) > 95 OR Price < Daily SMA(200)

Execution: Entry and exit at NEXT DAY OPEN (realistic)
Data     : Fyers API, daily candles, 5 years history
Output   : results/fno_backtest_results.csv + summary printed to console

Run:
  cd ~/prajnan-agent && source venv/bin/activate
  python3 strategies/fno_backtest.py
"""

import os
import sys
import csv
import time
import datetime
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.expanduser("~/prajnan-agent"))

from brokers.fyers_connector import fyers_connector

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

STOCKS_CSV    = os.path.expanduser("~/prajnan-agent/data/fno_stocks.csv")
RESULTS_DIR   = os.path.expanduser("~/prajnan-agent/results")
RESULTS_FILE  = os.path.expanduser("~/prajnan-agent/results/fno_backtest_results.csv")
SUMMARY_FILE  = os.path.expanduser("~/prajnan-agent/results/fno_backtest_summary.csv")

YEARS         = 5            # years of history to fetch
RSI_PERIOD    = 2
SMA_PERIOD    = 200
RSI_ENTRY     = 5            # entry: RSI(2) < 5
RSI_EXIT      = 95           # exit:  RSI(2) > 95
QUANTITY      = 1            # shares per trade (set to 1 for % return analysis)
BATCH_DELAY   = 0.5          # seconds between API calls
MAX_HOLDING   = 30           # max days to hold if no exit signal (safety)

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("fno_backtest")

# ─────────────────────────────────────────────
# LOAD STOCK LIST
# ─────────────────────────────────────────────

def load_symbols() -> list:
    if not os.path.exists(STOCKS_CSV):
        logger.error(f"CSV not found: {STOCKS_CSV}")
        sys.exit(1)
    symbols = []
    with open(STOCKS_CSV, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = list(row.values())[0].strip()
            if sym:
                symbols.append(sym)
    logger.info(f"Loaded {len(symbols)} stocks")
    return symbols

# ─────────────────────────────────────────────
# FETCH DAILY CANDLES FROM FYERS
# ─────────────────────────────────────────────

def fetch_daily_candles(symbol: str, years: int = YEARS) -> pd.DataFrame:
    """
    Fetch daily OHLC from Fyers for a stock.
    Fyers allows max 365 days per call — split into yearly chunks.
    """
    fyers    = fyers_connector.fyers
    today    = datetime.date.today()
    all_data = []

    # Fetch year by year
    for y in range(years, 0, -1):
        to_date   = today - datetime.timedelta(days=(y-1)*365)
        from_date = to_date - datetime.timedelta(days=365)
        data = {
            "symbol":      f"NSE:{symbol}-EQ",
            "resolution":  "D",
            "date_format": "1",
            "range_from":  from_date.strftime("%Y-%m-%d"),
            "range_to":    to_date.strftime("%Y-%m-%d"),
            "cont_flag":   "1"
        }
        try:
            response = fyers.history(data=data)
            if response.get("s") == "ok":
                all_data.extend(response.get("candles", []))
            time.sleep(0.1)
        except Exception as e:
            logger.debug(f"Fetch error {symbol}: {e}")

    if not all_data:
        return pd.DataFrame()

    df = pd.DataFrame(all_data, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
    df = df.drop_duplicates(subset="timestamp")
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df

# ─────────────────────────────────────────────
# INDICATORS
# ─────────────────────────────────────────────

def calc_rsi2(close: np.ndarray) -> np.ndarray:
    n      = len(close)
    rsi    = np.full(n, np.nan)
    if n < RSI_PERIOD + 2:
        return rsi
    deltas   = np.diff(close)
    gains    = np.where(deltas > 0, deltas, 0.0)
    losses   = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains[:RSI_PERIOD])
    avg_loss = np.mean(losses[:RSI_PERIOD])
    for i in range(RSI_PERIOD, n - 1):
        avg_gain = (avg_gain * (RSI_PERIOD - 1) + gains[i]) / RSI_PERIOD
        avg_loss = (avg_loss * (RSI_PERIOD - 1) + losses[i]) / RSI_PERIOD
        if avg_loss == 0:
            rsi[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi[i + 1] = 100.0 - (100.0 / (1.0 + rs))
    return rsi


def calc_sma200(close: np.ndarray) -> np.ndarray:
    sma = np.full(len(close), np.nan)
    for i in range(SMA_PERIOD - 1, len(close)):
        sma[i] = np.mean(close[i - SMA_PERIOD + 1:i + 1])
    return sma

# ─────────────────────────────────────────────
# BACKTEST ONE STOCK
# ─────────────────────────────────────────────

def backtest_stock(symbol: str, df: pd.DataFrame) -> list:
    """
    Run backtest on one stock.
    Returns list of trade dicts.
    """
    if len(df) < SMA_PERIOD + 10:
        return []

    close  = df["close"].values.astype(float)
    opens  = df["open"].values.astype(float)
    dates  = df["timestamp"].values
    sma200 = calc_sma200(close)
    rsi2   = calc_rsi2(close)

    trades       = []
    in_trade     = False
    entry_price  = 0
    entry_date   = None
    entry_idx    = 0

    for i in range(SMA_PERIOD, len(df) - 1):
        if np.isnan(rsi2[i]) or np.isnan(sma200[i]):
            continue

        if not in_trade:
            # Entry condition: close > SMA200 AND RSI2 < 5
            if close[i] > sma200[i] and rsi2[i] < RSI_ENTRY:
                # Enter at NEXT day's open
                entry_price = opens[i + 1]
                entry_date  = pd.Timestamp(dates[i + 1]).date()
                entry_idx   = i + 1
                in_trade    = True

        else:
            days_held = i - entry_idx
            # Exit condition: RSI2 > 95 OR close < SMA200 OR max holding
            exit_reason = None
            if rsi2[i] > RSI_EXIT:
                exit_reason = "RSI_EXIT"
            elif close[i] < sma200[i]:
                exit_reason = "SMA_EXIT"
            elif days_held >= MAX_HOLDING:
                exit_reason = "MAX_HOLD"

            if exit_reason and i + 1 < len(df):
                exit_price = opens[i + 1]
                exit_date  = pd.Timestamp(dates[i + 1]).date()
                pnl_pct    = round((exit_price - entry_price) / entry_price * 100, 2)
                pnl_rs     = round((exit_price - entry_price) * QUANTITY, 2)
                trades.append({
                    "symbol":       symbol,
                    "entry_date":   str(entry_date),
                    "exit_date":    str(exit_date),
                    "entry_price":  round(entry_price, 2),
                    "exit_price":   round(exit_price, 2),
                    "days_held":    days_held,
                    "pnl_pct":      pnl_pct,
                    "pnl_rs":       pnl_rs,
                    "exit_reason":  exit_reason,
                    "result":       "WIN" if pnl_pct > 0 else "LOSS",
                })
                in_trade = False

    return trades

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    os.makedirs(RESULTS_DIR, exist_ok=True)

    logger.info("=" * 60)
    logger.info("F&O RSI2 Backtest Engine")
    logger.info(f"Entry : Price > SMA200 AND RSI(2) < {RSI_ENTRY}")
    logger.info(f"Exit  : RSI(2) > {RSI_EXIT} OR Price < SMA200")
    logger.info(f"Data  : {YEARS} years daily candles from Fyers")
    logger.info(f"Stocks: {STOCKS_CSV}")
    logger.info("=" * 60)

    # Connect Fyers
    if not fyers_connector.connect():
        logger.error("Fyers connection failed")
        sys.exit(1)
    logger.info("Fyers connected ✓")

    symbols    = load_symbols()
    all_trades = []
    errors     = 0
    skipped    = 0

    for i, symbol in enumerate(symbols):
        try:
            logger.info(f"[{i+1}/{len(symbols)}] {symbol} — fetching...")
            df = fetch_daily_candles(symbol)

            if df is None or len(df) < SMA_PERIOD + 10:
                logger.debug(f"  {symbol}: insufficient data ({len(df) if df is not None else 0} candles)")
                skipped += 1
                time.sleep(BATCH_DELAY)
                continue

            trades = backtest_stock(symbol, df)
            all_trades.extend(trades)
            logger.info(f"  {symbol}: {len(df)} candles → {len(trades)} trades")

        except Exception as e:
            errors += 1
            logger.warning(f"  {symbol}: error — {e}")

        time.sleep(BATCH_DELAY)

    if not all_trades:
        logger.warning("No trades found across all stocks.")
        return

    # ── Save detailed results ──────────────────────────────────────
    results_df = pd.DataFrame(all_trades)
    results_df.to_csv(RESULTS_FILE, index=False)
    logger.info(f"\nDetailed results saved: {RESULTS_FILE}")

    # ── Per-stock summary ──────────────────────────────────────────
    summary = []
    for sym, grp in results_df.groupby("symbol"):
        wins      = grp[grp["result"] == "WIN"]
        losses    = grp[grp["result"] == "LOSS"]
        total     = len(grp)
        win_rate  = round(len(wins) / total * 100, 1) if total > 0 else 0
        avg_win   = round(wins["pnl_pct"].mean(), 2) if len(wins) > 0 else 0
        avg_loss  = round(losses["pnl_pct"].mean(), 2) if len(losses) > 0 else 0
        net_pct   = round(grp["pnl_pct"].sum(), 2)
        avg_days  = round(grp["days_held"].mean(), 1)
        summary.append({
            "symbol":    sym,
            "trades":    total,
            "wins":      len(wins),
            "losses":    len(losses),
            "win_rate%": win_rate,
            "avg_win%":  avg_win,
            "avg_loss%": avg_loss,
            "net_pnl%":  net_pct,
            "avg_days":  avg_days,
        })

    summary_df = pd.DataFrame(summary).sort_values("net_pnl%", ascending=False)
    summary_df.to_csv(SUMMARY_FILE, index=False)

    # ── Print overall summary ──────────────────────────────────────
    total_trades = len(all_trades)
    total_wins   = len([t for t in all_trades if t["result"] == "WIN"])
    overall_wr   = round(total_wins / total_trades * 100, 1)
    avg_pnl      = round(results_df["pnl_pct"].mean(), 2)
    avg_win_pct  = round(results_df[results_df["result"]=="WIN"]["pnl_pct"].mean(), 2)
    avg_loss_pct = round(results_df[results_df["result"]=="LOSS"]["pnl_pct"].mean(), 2)
    avg_hold     = round(results_df["days_held"].mean(), 1)

    print("\n" + "=" * 60)
    print("BACKTEST RESULTS SUMMARY")
    print("=" * 60)
    print(f"Stocks tested  : {len(symbols) - skipped - errors}")
    print(f"Total trades   : {total_trades}")
    print(f"Win rate       : {overall_wr}%")
    print(f"Avg trade P&L  : {avg_pnl}%")
    print(f"Avg win        : +{avg_win_pct}%")
    print(f"Avg loss       : {avg_loss_pct}%")
    print(f"Avg hold days  : {avg_hold}")
    print(f"\nTop 10 stocks by net P&L:")
    print(summary_df.head(10).to_string(index=False))
    print(f"\nBottom 5 stocks:")
    print(summary_df.tail(5).to_string(index=False))
    print("=" * 60)
    print(f"\nFiles saved:")
    print(f"  Detailed : {RESULTS_FILE}")
    print(f"  Summary  : {SUMMARY_FILE}")


if __name__ == "__main__":
    main()
