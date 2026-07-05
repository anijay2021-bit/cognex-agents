"""
COGNEX RSI2 Backtest — 30min SMA200 + RSI2
Both indicators on 30-min timeframe
Entry:  RSI(2) crossover + Spot vs SMA200(30min)
Exit:   RSI(2) crossover OR Spot crosses SMA200
"""

import sys
import numpy as np
import pandas as pd

sys.path.insert(0, '/home/anijay2021/prajnan-agent')
from brokers.fyers_connector import fyers_connector

TRADE_FROM     = "2026-01-28"
TO_DATE        = "2026-03-27"
SMA_PERIOD     = 200
RSI_PERIOD     = 2
RSI_OVERSOLD   = 10
RSI_OVERBOUGHT = 90
QUANTITY       = 650


def calc_rsi(close, period=2):
    n = len(close)
    rsi = np.full(n, np.nan)
    deltas = np.diff(close)
    gains  = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    ag = np.mean(gains[:period])
    al = np.mean(losses[:period])
    for i in range(period, n-1):
        ag = (ag*(period-1) + gains[i]) / period
        al = (al*(period-1) + losses[i]) / period
        rsi[i+1] = 100.0 if al == 0 else 100.0 - (100.0/(1.0+ag/al))
    return rsi


def fetch(symbol, resolution, from_date, to_date):
    data = {"symbol": symbol, "resolution": resolution,
            "date_format": "1", "range_from": from_date,
            "range_to": to_date, "cont_flag": "1"}
    resp = fyers_connector.fyers.history(data=data)
    if resp.get("s") != "ok":
        return None
    candles = resp.get("candles", [])
    if not candles:
        return None
    df = pd.DataFrame(candles, columns=["timestamp","open","high","low","close","volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
    return df.sort_values("timestamp").reset_index(drop=True)


def opt_price_at(opt_df, ts):
    if opt_df is None or len(opt_df) == 0:
        return 0
    diff = abs(opt_df["timestamp"] - ts)
    idx  = diff.idxmin()
    return 0 if diff[idx].seconds > 1800 else opt_df.iloc[idx]["close"]


def run():
    print("="*60)
    print("COGNEX RSI2 Backtest — 30min SMA200 + RSI2")
    print(f"SMA({SMA_PERIOD}) + RSI({RSI_PERIOD}) — both on 30min")
    print(f"Period: {TRADE_FROM} to {TO_DATE} | Qty: {QUANTITY}")
    print("="*60)

    if not fyers_connector.connect():
        print("Fyers failed"); return

    # Fetch 30min data in two chunks (Fyers ~6 month limit)
    print("Fetching 30min data (chunked)...")
    chunk1 = fetch("NSE:NIFTY50-INDEX", "30", "2025-10-01", "2026-01-01")
    chunk2 = fetch("NSE:NIFTY50-INDEX", "30", "2026-01-01", TO_DATE)
    if chunk1 is None or chunk2 is None:
        print("Failed to fetch 30min data"); return
    spot = pd.concat([chunk1, chunk2]).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)

    # UTC market hours filter: 3:45am to 10:00am
    spot = spot[(spot["timestamp"].dt.hour >= 3) & (spot["timestamp"].dt.hour <= 10)].reset_index(drop=True)

    # Calculate SMA200 and RSI2 on full dataset
    spot_close     = spot["close"].values.astype(float)
    spot["sma200"] = pd.Series(spot_close).rolling(SMA_PERIOD).mean().values
    spot["rsi2"]   = calc_rsi(spot_close, RSI_PERIOD)

    # SMA warmup check
    valid_sma = spot[~spot["sma200"].isna()]
    if len(valid_sma) > 0:
        print(f"Total 30min candles: {len(spot)}")
        print(f"SMA200 valid from:   {valid_sma.iloc[0]['timestamp']}")
    else:
        print("ERROR: SMA200 has no valid values — need more data"); return

    # Trade period
    trade_df = spot[spot["timestamp"].dt.date >= pd.Timestamp(TRADE_FROM).date()].copy().reset_index(drop=True)
    print(f"Trade period candles: {len(trade_df)}")

    # Verify SMA around key dates
    print("\nSMA200 verification (Jan 28 - Feb 5):")
    mask = (trade_df["timestamp"].dt.date >= pd.Timestamp("2026-01-28").date()) & \
           (trade_df["timestamp"].dt.date <= pd.Timestamp("2026-02-05").date())
    print(trade_df[mask][["timestamp","close","sma200","rsi2"]].head(10).to_string())
    print()

    # Option cache
    opt_cache = {}
    def get_opt(strike, otype):
        key = f"{strike}{otype}"
        if key not in opt_cache:
            sym = f"NSE:NIFTY26MAR{strike}{otype}"
            print(f"  Fetching {sym}")
            df  = fetch(sym, "5", "2026-01-01", TO_DATE)
            opt_cache[key] = (df, sym)
        return opt_cache[key]

    # Simulate
    trades   = []
    open_pos = []
    prev_rsi = np.nan
    prev_spot_vs_sma = None  # track spot vs sma crossover for exit

    print("\nScanning...\n")

    for i in range(len(trade_df)-1):
        row            = trade_df.iloc[i]
        ts             = row["timestamp"]
        spot_close_val = row["close"]
        rsi            = row["rsi2"]
        sma            = row["sma200"]

        if np.isnan(rsi) or np.isnan(sma):
            prev_rsi = rsi
            continue

        spot_above_sma = spot_close_val > sma

        # Force close all at market close (UTC 10:00)
        if ts.hour == 10:
            for ti in open_pos:
                ep  = opt_price_at(ti["opt_df"], ts)
                pnl = (ep - ti["entry_price"]) * QUANTITY if ep > 0 else 0
                r   = "WIN" if pnl > 0 else "LOSS"
                trades.append({k: v for k, v in ti.items() if k != "opt_df"} |
                               {"exit_time": ts, "exit_spot": spot_close_val,
                                "exit_price": ep, "pnl": round(pnl,2),
                                "exit_reason": "MARKET_CLOSE"})
                print(f"  CLOSE {ti['type']} {ts.strftime('%d-%b %H:%M')} | "
                      f"{ti['symbol']} Rs{ep:.2f} | PnL: Rs{pnl:+.0f} [{r}]")
            open_pos = []
            prev_rsi = rsi
            prev_spot_vs_sma = spot_above_sma
            continue

        # Check exits — crossover based
        remaining = []
        for ti in open_pos:
            t  = ti["type"]
            ex = None
            prev_rsi_ti = ti.get("prev_rsi", np.nan)
            prev_sma_ti = ti.get("prev_spot_above_sma", spot_above_sma)

            if t == "CE":
                # Exit CE: RSI crosses above 90 OR spot crosses below SMA
                if not np.isnan(prev_rsi_ti) and rsi > RSI_OVERBOUGHT and prev_rsi_ti <= RSI_OVERBOUGHT:
                    ex = f"RSI_CROSS RSI={rsi:.1f}>90"
                elif prev_sma_ti == True and spot_above_sma == False:
                    ex = f"SMA_CROSS {spot_close_val:.0f}<{sma:.0f}"
            elif t == "PE":
                # Exit PE: RSI crosses below 10 OR spot crosses above SMA
                if not np.isnan(prev_rsi_ti) and rsi < RSI_OVERSOLD and prev_rsi_ti >= RSI_OVERSOLD:
                    ex = f"RSI_CROSS RSI={rsi:.1f}<10"
                elif prev_sma_ti == False and spot_above_sma == True:
                    ex = f"SMA_CROSS {spot_close_val:.0f}>{sma:.0f}"

            if ex:
                ep  = opt_price_at(ti["opt_df"], ts)
                pnl = (ep - ti["entry_price"]) * QUANTITY if ep > 0 else 0
                r   = "WIN" if pnl > 0 else "LOSS"
                trades.append({k: v for k, v in ti.items() if k != "opt_df"} |
                               {"exit_time": ts, "exit_spot": spot_close_val,
                                "exit_price": ep, "pnl": round(pnl,2),
                                "exit_reason": ex})
                print(f"  {t} EXIT  {ts.strftime('%d-%b %H:%M')} | {ex} | "
                      f"{ti['symbol']} Rs{ep:.2f} | PnL: Rs{pnl:+.0f} [{r}]")
            else:
                # Update per-position tracking
                ti["prev_rsi"] = rsi
                ti["prev_spot_above_sma"] = spot_above_sma
                remaining.append(ti)
        open_pos = remaining

        # Check for new entry — RSI crossover + spot vs SMA
        sig = None
        if not np.isnan(prev_rsi):
            # CE: spot above SMA AND RSI crosses below 10
            if spot_above_sma and rsi < RSI_OVERSOLD and prev_rsi >= RSI_OVERSOLD:
                sig = "CE"
            # PE: spot below SMA AND RSI crosses above 90
            elif not spot_above_sma and rsi > RSI_OVERBOUGHT and prev_rsi <= RSI_OVERBOUGHT:
                sig = "PE"

        if sig:
            atm         = int(round(spot_close_val/50)*50)
            opt_df, sym = get_opt(atm, sig)
            next_row    = trade_df.iloc[i+1]
            next_ts     = next_row["timestamp"]
            ep          = opt_price_at(opt_df, next_ts)
            if ep > 0:
                entry_ts = next_ts
                ti = {"type": sig, "symbol": sym, "strike": atm,
                      "entry_time": entry_ts, "entry_price": ep,
                      "entry_spot": spot_close_val, "sma200": round(sma,2),
                      "entry_rsi": round(rsi,2),
                      "prev_rsi": rsi,
                      "prev_spot_above_sma": spot_above_sma,
                      "opt_df": opt_df}
                open_pos.append(ti)
                print(f"  {sig} ENTRY {entry_ts.strftime('%d-%b %H:%M')} | "
                      f"Spot:{spot_close_val:.0f} SMA:{sma:.0f} RSI:{rsi:.1f} | "
                      f"{sym} @ Rs{ep:.2f} [Open: {len(open_pos)}]")
            else:
                print(f"  {sig} SIGNAL {ts.strftime('%d-%b %H:%M')} — no price for {sym}")

        prev_rsi = rsi
        prev_spot_vs_sma = spot_above_sma

    # Close remaining positions
    if open_pos:
        last           = trade_df.iloc[-1]
        ts             = last["timestamp"]
        spot_close_val = last["close"]
        for ti in open_pos:
            ep  = opt_price_at(ti["opt_df"], ts)
            pnl = (ep - ti["entry_price"]) * QUANTITY if ep > 0 else 0
            r   = "WIN" if pnl > 0 else "LOSS"
            trades.append({k: v for k, v in ti.items() if k != "opt_df"} |
                           {"exit_time": ts, "exit_spot": spot_close_val,
                            "exit_price": ep, "pnl": round(pnl,2),
                            "exit_reason": "END_OF_BACKTEST"})
            print(f"  END {ti['type']} {ts.strftime('%d-%b %H:%M')} | "
                  f"Rs{ep:.2f} | PnL: Rs{pnl:+.0f} [{r}]")

    # Results
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)

    if not trades:
        print("No trades found"); return

    total = len(trades)
    wins  = [t for t in trades if t["pnl"] > 0]
    loss  = [t for t in trades if t["pnl"] <= 0]
    net   = sum(t["pnl"] for t in trades)
    wr    = len(wins)/total*100
    aw    = sum(t["pnl"] for t in wins)/len(wins) if wins else 0
    al    = sum(t["pnl"] for t in loss)/len(loss) if loss else 0

    print(f"Total trades:  {total}")
    print(f"Winning:       {len(wins)} ({wr:.1f}%)")
    print(f"Losing:        {len(loss)}")
    print(f"Net P&L:       Rs{net:+,.2f}")
    print(f"Avg win:       Rs{aw:+,.2f}")
    print(f"Avg loss:      Rs{al:+,.2f}")
    print(f"Best trade:    Rs{max(t['pnl'] for t in trades):+,.2f}")
    print(f"Worst trade:   Rs{min(t['pnl'] for t in trades):+,.2f}")

    ce = [t for t in trades if t["type"] == "CE"]
    pe = [t for t in trades if t["type"] == "PE"]
    print(f"\nCE trades: {len(ce)} | PnL: Rs{sum(t['pnl'] for t in ce):+,.2f}")
    print(f"PE trades: {len(pe)} | PnL: Rs{sum(t['pnl'] for t in pe):+,.2f}")

    pd.DataFrame(trades).to_csv(
        "/home/anijay2021/prajnan-agent/backtest/rsi2_results.csv", index=False)
    print("\nSaved: backtest/rsi2_results.csv")
    print("="*60)


if __name__ == "__main__":
    run()
