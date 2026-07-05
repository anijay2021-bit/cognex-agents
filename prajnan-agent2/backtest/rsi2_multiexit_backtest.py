"""
COGNEX RSI2 Backtest — Multiple Exit Threshold Tests
Both indicators on 30-min timeframe
Front-month contract rolling:
  Jan contract: 2026-01-01 to 2026-01-27
  Feb contract: 2026-01-28 to 2026-02-24
  Mar contract: 2026-02-25 to 2026-03-27
"""

import sys
import numpy as np
import pandas as pd

sys.path.insert(0, '/home/anijay2021/cognex-agent')
from brokers.fyers_connector import fyers_connector

TRADE_FROM  = "2026-01-01"
TO_DATE     = "2026-03-27"
SMA_PERIOD  = 200
RSI_PERIOD  = 2
RSI_OVERSOLD   = 10
RSI_OVERBOUGHT = 90
QUANTITY    = 650

# Front-month contract map: (from_date, to_date, expiry_label)
CONTRACT_ROLLS = [
    {"from": "2026-01-01", "to": "2026-01-27", "expiry": "26JAN"},
    {"from": "2026-01-28", "to": "2026-02-24", "expiry": "26FEB"},
    {"from": "2026-02-25", "to": "2026-03-27", "expiry": "26MAR"},
]

EXIT_CONFIGS = [
    {"label": "Exit_98_5",  "ce_exit_rsi": 98,  "pe_exit_rsi": 5.0},
    {"label": "Exit_95_75", "ce_exit_rsi": 95,  "pe_exit_rsi": 7.5},
    {"label": "Exit_92_6",  "ce_exit_rsi": 92,  "pe_exit_rsi": 6.0},
]


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


def get_expiry_for_date(d):
    """Return expiry label for a given date"""
    for roll in CONTRACT_ROLLS:
        if pd.Timestamp(roll["from"]).date() <= d <= pd.Timestamp(roll["to"]).date():
            return roll["expiry"]
    return None


def opt_price_at(opt_df, ts):
    if opt_df is None or len(opt_df) == 0:
        return 0
    diff = abs(opt_df["timestamp"] - ts)
    idx  = diff.idxmin()
    return 0 if diff[idx].seconds > 1800 else opt_df.iloc[idx]["close"]


def run_simulation(trade_df, opt_cache, ce_exit_rsi, pe_exit_rsi, label):
    print(f"\n{'='*60}")
    print(f"Running: {label} | CE exit RSI>{ce_exit_rsi} | PE exit RSI<{pe_exit_rsi}")
    print(f"{'='*60}")

    def get_opt(strike, otype, expiry):
        key = f"{expiry}{strike}{otype}"
        if key not in opt_cache:
            sym = f"NSE:NIFTY{expiry}{strike}{otype}"
            print(f"  Fetching {sym}")
            df  = fetch(sym, "5", "2026-01-01", TO_DATE)
            opt_cache[key] = (df, sym)
        return opt_cache[key]

    trades   = []
    open_pos = []
    prev_rsi = np.nan

    for i in range(len(trade_df)-1):
        row            = trade_df.iloc[i]
        ts             = row["timestamp"]
        spot_close_val = row["close"]
        rsi            = row["rsi2"]
        sma            = row["sma200"]
        d              = ts.date()

        if np.isnan(rsi) or np.isnan(sma):
            prev_rsi = rsi
            continue

        spot_above_sma = spot_close_val > sma
        expiry = get_expiry_for_date(d)
        if expiry is None:
            prev_rsi = rsi
            continue

        # Force close at market close (UTC 10:00)
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
            continue

        # Force close positions when contract rolls
        remaining_after_roll = []
        for ti in open_pos:
            if ti["expiry"] != expiry:
                ep  = opt_price_at(ti["opt_df"], ts)
                pnl = (ep - ti["entry_price"]) * QUANTITY if ep > 0 else 0
                r   = "WIN" if pnl > 0 else "LOSS"
                trades.append({k: v for k, v in ti.items() if k != "opt_df"} |
                               {"exit_time": ts, "exit_spot": spot_close_val,
                                "exit_price": ep, "pnl": round(pnl,2),
                                "exit_reason": "CONTRACT_ROLL"})
                print(f"  ROLL  {ti['type']} {ts.strftime('%d-%b %H:%M')} | "
                      f"{ti['symbol']} Rs{ep:.2f} | PnL: Rs{pnl:+.0f} [{r}]")
            else:
                remaining_after_roll.append(ti)
        open_pos = remaining_after_roll

        # Check exits
        remaining = []
        for ti in open_pos:
            t           = ti["type"]
            ex          = None
            prev_rsi_ti = ti.get("prev_rsi", np.nan)
            prev_sma_ti = ti.get("prev_spot_above_sma", spot_above_sma)

            if t == "CE":
                if not np.isnan(prev_rsi_ti) and rsi > ce_exit_rsi and prev_rsi_ti <= ce_exit_rsi:
                    ex = f"RSI_CROSS RSI={rsi:.1f}>{ce_exit_rsi}"
                elif prev_sma_ti == True and spot_above_sma == False:
                    ex = f"SMA_CROSS {spot_close_val:.0f}<{sma:.0f}"
            elif t == "PE":
                if not np.isnan(prev_rsi_ti) and rsi < pe_exit_rsi and prev_rsi_ti >= pe_exit_rsi:
                    ex = f"RSI_CROSS RSI={rsi:.1f}<{pe_exit_rsi}"
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
                ti["prev_rsi"] = rsi
                ti["prev_spot_above_sma"] = spot_above_sma
                remaining.append(ti)
        open_pos = remaining

        # New entry
        sig = None
        if not np.isnan(prev_rsi):
            if spot_above_sma and rsi < RSI_OVERSOLD and prev_rsi >= RSI_OVERSOLD:
                sig = "CE"
            elif not spot_above_sma and rsi > RSI_OVERBOUGHT and prev_rsi <= RSI_OVERBOUGHT:
                sig = "PE"

        if sig:
            atm         = int(round(spot_close_val/50)*50)
            opt_df, sym = get_opt(atm, sig, expiry)
            next_row    = trade_df.iloc[i+1]
            next_ts     = next_row["timestamp"]
            ep          = opt_price_at(opt_df, next_ts)
            if ep > 0:
                ti = {"type": sig, "symbol": sym, "strike": atm,
                      "expiry": expiry,
                      "entry_time": next_ts, "entry_price": ep,
                      "entry_spot": spot_close_val, "sma200": round(sma,2),
                      "entry_rsi": round(rsi,2),
                      "prev_rsi": rsi,
                      "prev_spot_above_sma": spot_above_sma,
                      "opt_df": opt_df}
                open_pos.append(ti)
                print(f"  {sig} ENTRY {next_ts.strftime('%d-%b %H:%M')} | "
                      f"Spot:{spot_close_val:.0f} SMA:{sma:.0f} RSI:{rsi:.1f} | "
                      f"{sym} @ Rs{ep:.2f} [Open: {len(open_pos)}]")
            else:
                print(f"  {sig} SIGNAL {ts.strftime('%d-%b %H:%M')} — no price for {sym}")

        prev_rsi = rsi

    # Close remaining
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

    # Summary
    print(f"\n--- {label} SUMMARY ---")
    if not trades:
        print("No trades"); return []

    total = len(trades)
    wins  = [t for t in trades if t["pnl"] > 0]
    loss  = [t for t in trades if t["pnl"] <= 0]
    net   = sum(t["pnl"] for t in trades)
    wr    = len(wins)/total*100
    aw    = sum(t["pnl"] for t in wins)/len(wins) if wins else 0
    al    = sum(t["pnl"] for t in loss)/len(loss) if loss else 0
    ce    = [t for t in trades if t["type"] == "CE"]
    pe    = [t for t in trades if t["type"] == "PE"]

    print(f"Total: {total} | Win: {len(wins)} ({wr:.1f}%) | Loss: {len(loss)}")
    print(f"Net PnL:  Rs{net:+,.2f}")
    print(f"Avg Win:  Rs{aw:+,.2f} | Avg Loss: Rs{al:+,.2f}")
    print(f"Best:     Rs{max(t['pnl'] for t in trades):+,.2f} | Worst: Rs{min(t['pnl'] for t in trades):+,.2f}")
    print(f"CE: {len(ce)} trades Rs{sum(t['pnl'] for t in ce):+,.2f} | PE: {len(pe)} trades Rs{sum(t['pnl'] for t in pe):+,.2f}")

    return trades


def run():
    print("="*60)
    print("COGNEX RSI2 Multi-Exit Backtest — Rolling Contracts")
    print(f"Jan contract: 01-Jan to 27-Jan")
    print(f"Feb contract: 28-Jan to 24-Feb")
    print(f"Mar contract: 25-Feb to 27-Mar")
    print(f"Period: {TRADE_FROM} to {TO_DATE} | Qty: {QUANTITY}")
    print("="*60)

    if not fyers_connector.connect():
        print("Fyers failed"); return

    # Fetch 30min data chunked
    print("\nFetching 30min data...")
    chunk1 = fetch("NSE:NIFTY50-INDEX", "30", "2025-10-01", "2026-01-01")
    chunk2 = fetch("NSE:NIFTY50-INDEX", "30", "2026-01-01", TO_DATE)
    if chunk1 is None or chunk2 is None:
        print("Failed to fetch 30min data"); return

    spot = pd.concat([chunk1, chunk2]).drop_duplicates("timestamp").sort_values("timestamp").reset_index(drop=True)
    spot = spot[(spot["timestamp"].dt.hour >= 3) & (spot["timestamp"].dt.hour <= 10)].reset_index(drop=True)

    spot_close     = spot["close"].values.astype(float)
    spot["sma200"] = pd.Series(spot_close).rolling(SMA_PERIOD).mean().values
    spot["rsi2"]   = calc_rsi(spot_close, RSI_PERIOD)

    valid_sma = spot[~spot["sma200"].isna()]
    print(f"Total 30min candles: {len(spot)}")
    print(f"SMA200 valid from:   {valid_sma.iloc[0]['timestamp'] if len(valid_sma) > 0 else 'NONE'}")

    trade_df = spot[spot["timestamp"].dt.date >= pd.Timestamp(TRADE_FROM).date()].copy().reset_index(drop=True)
    print(f"Trade period candles: {len(trade_df)}")

    # Shared option cache
    opt_cache = {}

    # Run all 3 exit configs
    all_summaries = []
    for cfg in EXIT_CONFIGS:
        trades = run_simulation(
            trade_df, opt_cache,
            ce_exit_rsi=cfg["ce_exit_rsi"],
            pe_exit_rsi=cfg["pe_exit_rsi"],
            label=cfg["label"]
        )
        if trades:
            df = pd.DataFrame(trades)
            df["exit_config"] = cfg["label"]
            path = f"/home/anijay2021/cognex-agent/backtest/rsi2_{cfg['label']}.csv"
            df.to_csv(path, index=False)
            print(f"Saved: {path}")

            total = len(trades)
            wins  = len([t for t in trades if t["pnl"] > 0])
            net   = sum(t["pnl"] for t in trades)
            all_summaries.append({
                "config":        cfg["label"],
                "ce_exit_rsi":   cfg["ce_exit_rsi"],
                "pe_exit_rsi":   cfg["pe_exit_rsi"],
                "total_trades":  total,
                "winners":       wins,
                "win_pct":       round(wins/total*100, 1),
                "net_pnl":       round(net, 2)
            })

    # Final comparison
    print("\n" + "="*60)
    print("COMPARISON TABLE")
    print("="*60)
    summary_df = pd.DataFrame(all_summaries)
    print(summary_df.to_string(index=False))
    summary_df.to_csv("/home/anijay2021/cognex-agent/backtest/rsi2_comparison.csv", index=False)
    print("\nSaved: backtest/rsi2_comparison.csv")
    print("="*60)


if __name__ == "__main__":
    run()
