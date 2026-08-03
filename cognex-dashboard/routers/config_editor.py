"""
COGNEX Dashboard — Full Config Editor
All 64 strategy parameters from Phase 1c, now wired to live agent files.

Storage:
  - params with file_map → write to Python file + restart agent
  - all other params    → write to strategy_settings.json
"""

import re, os, json, shutil, subprocess
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any

router   = APIRouter()
BASE     = "/home/anijay2021"
JSON_PATH = f"{BASE}/cognex-dashboard/strategy_settings.json"

# ── JSON settings helpers ─────────────────────────────────────────────────────
def load_json():
    if os.path.exists(JSON_PATH):
        try:
            return json.loads(open(JSON_PATH).read())
        except: pass
    return {}

def save_json(data: dict):
    os.makedirs(os.path.dirname(JSON_PATH), exist_ok=True)
    open(JSON_PATH, "w").write(json.dumps(data, indent=2))

# ── Python file read/write ────────────────────────────────────────────────────
def read_file_param(filepath, var, pattern):
    content = open(filepath).read()
    if pattern == "simple":
        m = re.search(rf'^{re.escape(var)}\s*=\s*([^\s#\n]+)', content, re.MULTILINE)
        return m.group(1).strip() if m else None
    if pattern == "quoted":
        m = re.search(rf'^{re.escape(var)}\s*=\s*"([^"]+)"', content, re.MULTILINE)
        return m.group(1) if m else None
    if pattern == "inline_lt":
        m = re.search(r'rsi2\s*<\s*(\d+(?:\.\d+)?)', content)
        return m.group(1) if m else None
    if pattern == "inline_gt":
        m = re.search(r'rsi2\s*>\s*(\d+(?:\.\d+)?)', content)
        return m.group(1) if m else None
    return None

def write_file_param(filepath, var, pattern, new_value):
    shutil.copy2(filepath, filepath + ".bak")
    content = open(filepath).read()
    original = content
    sv = str(new_value)
    if pattern == "simple":
        content = re.sub(rf'^({re.escape(var)}\s*=\s*)([^\s#\n]+)', rf'\g<1>{sv}', content, flags=re.MULTILINE)
    elif pattern == "quoted":
        content = re.sub(rf'^({re.escape(var)}\s*=\s*")[^"]*(")', rf'\g<1>{sv}\g<2>', content, flags=re.MULTILINE)
    elif pattern == "inline_lt":
        content = re.sub(r'(rsi2\s*<\s*)\d+(?:\.\d+)?', rf'\g<1>{sv}', content)
    elif pattern == "inline_gt":
        content = re.sub(r'(rsi2\s*>\s*)\d+(?:\.\d+)?', rf'\g<1>{sv}', content)
    if content != original:
        open(filepath, "w").write(content)
        return True
    return False

def restart_svc(svc):
    try:
        r = subprocess.run(["sudo","systemctl","try-restart",svc], capture_output=True, text=True, timeout=15)
        return r.returncode == 0
    except: return False

# ── Full parameter schema ─────────────────────────────────────────────────────
# file_map = (filepath, var_name, pattern) — if present, writes to Python file
# If no file_map → JSON only
P = f"{BASE}/prajnan-agent/strategies"
T = f"{BASE}/trishul-agent/strategies"
PENV = f"{BASE}/prajnan-agent/config/.env"
PO = f"{BASE}/prajnan-agent/core/order_executor.py"
PM = f"{BASE}/prajnan-agent/main.py"
NS = f"{BASE}/nitin-agent/config/settings.py"
A2 = f"{BASE}/prajnan-agent2/strategies/rsi2_scanner.py"
PPE = f"{BASE}/pocket-pivot-agent/config.env"

PARAMS = {
  # ── TRISHUL ──────────────────────────────────────────────────────────────
  # ── PRAJNAN RSI2 ─────────────────────────────────────────────────────────
  "r_oversold":           {"label":"RSI2 oversold threshold","desc":"Buy CE when RSI2 drops below this value","group":"Prajnan RSI2","section":"Entry — CE (buy call)","dot":"dot-teal","type":"int","default":5,"unit":"","svc":"prajnan-agent","file_map":(f"{P}/rsi2_scanner.py","RSI_OVERSOLD","simple")},
  "r_overbought":         {"label":"RSI2 overbought threshold","desc":"Buy PE when RSI2 rises above this value","group":"Prajnan RSI2","section":"Entry — PE (buy put)","dot":"dot-teal","type":"int","default":95,"unit":"","svc":"prajnan-agent","file_map":(f"{P}/rsi2_scanner.py","RSI_OVERBOUGHT","simple")},
  "r_exit_ce":            {"label":"RSI2 exit — CE","desc":"Exit CE when RSI2 crosses above this value","group":"Prajnan RSI2","section":"Exit","dot":"dot-coral","type":"int","default":95,"unit":"","svc":"prajnan-agent"},
  "r_exit_pe":            {"label":"RSI2 exit — PE","desc":"Exit PE when RSI2 crosses below this value","group":"Prajnan RSI2","section":"Exit","dot":"dot-coral","type":"int","default":5,"unit":"","svc":"prajnan-agent"},
  "r_lots":               {"label":"Lots per trade","desc":"1 lot = 65 units of Nifty","group":"Prajnan RSI2","section":"Risk management","dot":"dot-purple","type":"int","default":10,"unit":"lots","svc":"prajnan-agent","file_map":(f"{P}/rsi2_scanner.py","RSI2_LOTS","simple"),"file_map": (PENV,"RSI2_LOTS","simple")},
  "r_daily_loss":         {"label":"Daily loss limit","desc":"Stop all trading if cumulative daily loss exceeds this","group":"Prajnan RSI2","section":"Risk management","dot":"dot-purple","type":"int","default":20000,"unit":"₹","svc":"prajnan-agent"},

  # ── PRAJNAN EMA+OBV ──────────────────────────────────────────────────────
  "e_product_type":       {"label":"Product type","desc":"INTRADAY (MIS) · CARRYFORWARD (NRML)","group":"Prajnan EMA+OBV","section":"Product type","dot":"dot-gray","type":"select","opts":["INTRADAY","CARRYFORWARD"],"default":"INTRADAY","unit":"","svc":"prajnan-agent","file_map": (PO,"PRODUCT_TYPE","quoted")},
  "e_ema_fast":           {"label":"EMA fast period","desc":"Fast EMA on 15-min Nifty Futures candles","group":"Prajnan EMA+OBV","section":"Entry conditions","dot":"dot-teal","type":"int","default":9,"unit":"candles","svc":"prajnan-agent","file_map":(f"{P}/ema_obv_scanner.py","EMA_FAST","simple")},
  "e_ema_slow":           {"label":"EMA slow period","desc":"Slow EMA on 15-min Nifty Futures candles","group":"Prajnan EMA+OBV","section":"Entry conditions","dot":"dot-teal","type":"int","default":21,"unit":"candles","svc":"prajnan-agent","file_map":(f"{P}/ema_obv_scanner.py","EMA_SLOW","simple")},
  "e_obv_lookback":       {"label":"OBV lookback candles","desc":"Number of candles to confirm OBV higher highs","group":"Prajnan EMA+OBV","section":"Entry conditions","dot":"dot-teal","type":"int","default":5,"unit":"candles","svc":"prajnan-agent"},
  "e_target_mult":        {"label":"Target multiplier","desc":"Target = entry premium × this (1.4 = 40% profit)","group":"Prajnan EMA+OBV","section":"Target & stop loss","dot":"dot-amber","type":"float","default":1.4,"unit":"×","svc":"prajnan-agent","file_map": (f"{P}/ema_obv_scanner.py","TARGET_MULT","simple")},
  "e_sl_pct":             {"label":"Premium SL %","desc":"Exit when premium drops X% from entry price","group":"Prajnan EMA+OBV","section":"Target & stop loss","dot":"dot-amber","type":"int","default":30,"unit":"%","svc":"prajnan-agent"},
  "e_ema_cross_exit":     {"label":"EMA cross exit","desc":"Exit when EMA9 crosses back below EMA21","group":"Prajnan EMA+OBV","section":"Target & stop loss","dot":"dot-amber","type":"bool","default":True,"unit":"","svc":"prajnan-agent"},
  "e_lots":               {"label":"Lots per trade","desc":"1 lot = 65 units of Nifty","group":"Prajnan EMA+OBV","section":"Risk management","dot":"dot-purple","type":"int","default":10,"unit":"lots","svc":"prajnan-agent","file_map": (PENV,"EMA_LOTS","simple")},
  "e_daily_loss":         {"label":"Daily loss limit","desc":"Stop trading if daily loss exceeds this","group":"Prajnan EMA+OBV","section":"Risk management","dot":"dot-purple","type":"int","default":20000,"unit":"₹","svc":"prajnan-agent"},
  "e_entry_from":         {"label":"Entries valid from","desc":"No entries before this time (opening noise)","group":"Prajnan EMA+OBV","section":"Timing","dot":"dot-blue","type":"time","default":"09:30","unit":"","svc":"prajnan-agent","file_map": (f"{P}/ema_obv_scanner.py","ENTRY_FROM","quoted")},
  "e_no_entry_after":     {"label":"No new entries after","desc":"Stop new entries after this time IST","group":"Prajnan EMA+OBV","section":"Timing","dot":"dot-blue","type":"time","default":"14:45","unit":"","svc":"prajnan-agent","file_map": (f"{P}/ema_obv_scanner.py","NO_ENTRY_AFTER","quoted")},
  "e_squareoff":          {"label":"EOD square-off","desc":"Exit all positions at this time IST","group":"Prajnan EMA+OBV","section":"Timing","dot":"dot-blue","type":"time","default":"15:25","unit":"","svc":"prajnan-agent","file_map": (PM,"EOD_SQUAREOFF_IST","quoted")},
  # ── PRAJNAN CALENDAR ─────────────────────────────────────────────────────
  "c_lots":               {"label":"Lots per leg","desc":"Applied to each of the 4 legs (buy monthly + sell weekly)","group":"Prajnan Calendar","section":"Structure","dot":"dot-gray","type":"int","default":10,"unit":"lots","svc":"prajnan-agent","file_map":(f"{P}/calendar_spread_strategy.py","LOTS","simple")},
  "c_sl_candle":          {"label":"SL check interval","desc":"Check SL on every X-min candle close, not tick-by-tick","group":"Prajnan Calendar","section":"Stop loss logic","dot":"dot-amber","type":"int","default":5,"unit":"min","svc":"prajnan-agent","file_map": (f"{P}/calendar_spread_strategy.py","SL_CANDLE_TF","simple")},
  "c_flip_sl":            {"label":"Flipped buy SL %","desc":"After SL flip: exit if premium drops X% from flip entry","group":"Prajnan Calendar","section":"Stop loss logic","dot":"dot-amber","type":"float","default":30.0,"unit":"%","svc":"prajnan-agent","file_map":(f"{P}/calendar_spread_strategy.py","BUY_SL_PERCENT","simple")},
  "c_max_flips":          {"label":"Max flip cycles","desc":"Max sell→buy→sell cycles per leg before giving up","group":"Prajnan Calendar","section":"Stop loss logic","dot":"dot-amber","type":"int","default":5,"unit":"","svc":"prajnan-agent"},
  "c_roll_exit":          {"label":"Weekly roll — exit time","desc":"Exit weekly sold legs at this time on expiry day IST","group":"Prajnan Calendar","section":"Weekly roll","dot":"dot-blue","type":"time","default":"15:24","unit":"","svc":"prajnan-agent","file_map":(f"{P}/calendar_spread_strategy.py","WEEKLY_EXIT_TIME","quoted")},
  "c_roll_entry":         {"label":"Weekly roll — entry time","desc":"Sell new weekly straddle at this time IST","group":"Prajnan Calendar","section":"Weekly roll","dot":"dot-blue","type":"time","default":"15:26","unit":"","svc":"prajnan-agent","file_map": (f"{P}/calendar_spread_strategy.py","ENTRY_TIME","quoted")},
  "c_monthly_exit":       {"label":"Monthly exit time","desc":"Exit ALL positions at this time on monthly expiry day IST","group":"Prajnan Calendar","section":"Monthly expiry","dot":"dot-blue","type":"time","default":"15:24","unit":"","svc":"prajnan-agent","file_map":(f"{P}/calendar_spread_strategy.py","MONTHLY_EXIT_TIME","quoted")},
  "c_skip_resell":        {"label":"Skip resell if ATM matches","desc":"Hold buy legs if strike = new ATM at monthly expiry","group":"Prajnan Calendar","section":"Monthly expiry","dot":"dot-blue","type":"bool","default":True,"unit":"","svc":"prajnan-agent"},
  "c_hedge":              {"label":"Hedging enabled","desc":"Buy OTM protection before expiry days","group":"Prajnan Calendar","section":"Hedge settings","dot":"dot-teal","type":"bool","default":False,"unit":"","svc":"prajnan-agent"},
  "c_hedge_ce":           {"label":"CE hedge offset","desc":"Buy CE hedge X strikes above sell strike","group":"Prajnan Calendar","section":"Hedge settings","dot":"dot-teal","type":"int","default":5,"unit":"strikes","svc":"prajnan-agent"},
  "c_hedge_pe":           {"label":"PE hedge offset","desc":"Buy PE hedge X strikes below sell strike","group":"Prajnan Calendar","section":"Hedge settings","dot":"dot-teal","type":"int","default":5,"unit":"strikes","svc":"prajnan-agent"},
  "c_daily_loss":         {"label":"Daily loss limit","desc":"Stop new weekly rolls if daily loss exceeds this","group":"Prajnan Calendar","section":"Risk management","dot":"dot-purple","type":"int","default":30000,"unit":"₹","svc":"prajnan-agent"},
    # --- NITIN swing agent (added by sync 2026-07-15) ---
    "n_mode":           {"label":"Trading mode","desc":"PAPER or LIVE (live path not implemented in agent)","group":"Nitin Swing","section":"General","dot":"dot-gray","type":"select","opts":["PAPER","LIVE"],"default":"PAPER","unit":"","svc":"nitin-agent","file_map": (NS,"MODE","quoted")},
    "n_capital":        {"label":"Capital","desc":"Capital base for position sizing","group":"Nitin Swing","section":"Risk management","dot":"dot-purple","type":"float","default":100000.0,"unit":"Rs","svc":"nitin-agent","file_map": (NS,"CAPITAL","simple")},
    "n_risk_pct":       {"label":"Risk per trade %","desc":"Percent of capital risked per trade","group":"Nitin Swing","section":"Risk management","dot":"dot-purple","type":"float","default":1.0,"unit":"%","svc":"nitin-agent","file_map": (NS,"RISK_PER_TRADE_PCT","simple")},
    "n_max_alloc":      {"label":"Max allocation %","desc":"Max percent of capital in one stock","group":"Nitin Swing","section":"Risk management","dot":"dot-purple","type":"float","default":25.0,"unit":"%","svc":"nitin-agent","file_map": (NS,"MAX_ALLOCATION_PCT","simple")},
    "n_max_stop":       {"label":"Max stop distance %","desc":"Reject setups with stop further than this","group":"Nitin Swing","section":"Risk management","dot":"dot-amber","type":"float","default":8.0,"unit":"%","svc":"nitin-agent","file_map": (NS,"MAX_STOP_PCT","simple")},
    "n_max_positions":  {"label":"Max open positions","desc":"Concurrent open positions cap","group":"Nitin Swing","section":"Risk management","dot":"dot-purple","type":"int","default":3,"unit":"","svc":"nitin-agent","file_map": (NS,"MAX_OPEN_POSITIONS","simple")},
    "n_min_turnover":   {"label":"Min turnover","desc":"Skip illiquid stocks below this daily turnover","group":"Nitin Swing","section":"Universe","dot":"dot-teal","type":"float","default":5.0,"unit":"Cr","svc":"nitin-agent","file_map": (NS,"MIN_TURNOVER_CR","simple")},
    "n_scan_time":      {"label":"EOD scan time","desc":"Daily setup scan time IST (Mon-Fri)","group":"Nitin Swing","section":"Timing","dot":"dot-blue","type":"time","default":"18:30","unit":"","svc":"nitin-agent","file_map": (NS,"SCAN_TIME","quoted")},
    "n_monitor_min":    {"label":"Monitor interval","desc":"Signal/position check cadence during market hours","group":"Nitin Swing","section":"Timing","dot":"dot-blue","type":"int","default":15,"unit":"min","svc":"nitin-agent","file_map": (NS,"MONITOR_EVERY_MIN","simple")},
    "n_signal_valid":   {"label":"Signal validity","desc":"Signals expire if not triggered in N days","group":"Nitin Swing","section":"Timing","dot":"dot-blue","type":"int","default":4,"unit":"days","svc":"nitin-agent","file_map": (NS,"SIGNAL_VALID_DAYS","simple")},
    # --- PRAJNAN2 RSI2 agent (added by sync 2026-07-15) ---
    "a2_rsi_period":    {"label":"RSI period","desc":"RSI length for RSI2 scanner","group":"Prajnan2 RSI2","section":"Signal","dot":"dot-teal","type":"int","default":2,"unit":"","svc":"prajnan-agent2","file_map": (A2,"RSI_PERIOD","simple")},
    "a2_rsi_oversold":  {"label":"RSI oversold","desc":"Buy CE when RSI drops below this","group":"Prajnan2 RSI2","section":"Signal","dot":"dot-teal","type":"int","default":5,"unit":"","svc":"prajnan-agent2","file_map": (A2,"RSI_OVERSOLD","simple")},
    "a2_rsi_overbought":{"label":"RSI overbought","desc":"Buy PE when RSI rises above this","group":"Prajnan2 RSI2","section":"Signal","dot":"dot-teal","type":"int","default":95,"unit":"","svc":"prajnan-agent2","file_map": (A2,"RSI_OVERBOUGHT","simple")},
    "a2_ema_period":    {"label":"Trend EMA period","desc":"Daily EMA length for trend filter","group":"Prajnan2 RSI2","section":"Signal","dot":"dot-teal","type":"int","default":200,"unit":"","svc":"prajnan-agent2","file_map": (A2,"EMA_PERIOD","simple")},
    # --- POCKET PIVOT (added 2026-07-16) ---
    "pp_scan_from":     {"label":"Scan from","desc":"Start scanning at this time IST (Mon-Fri)","group":"Pocket Pivot","section":"Timing","dot":"dot-blue","type":"time","default":"09:15","unit":"","svc":"pocket-pivot-agent","file_map": (PPE,"SCAN_FROM","quoted")},
    "pp_no_scan_after": {"label":"Stop scanning after","desc":"No scans after this time IST","group":"Pocket Pivot","section":"Timing","dot":"dot-blue","type":"time","default":"15:29","unit":"","svc":"pocket-pivot-agent","file_map": (PPE,"NO_SCAN_AFTER","quoted")},
    "pp_interval":      {"label":"Scan interval","desc":"Seconds between Chartink scans","group":"Pocket Pivot","section":"Timing","dot":"dot-blue","type":"int","default":60,"unit":"sec","svc":"pocket-pivot-agent","file_map": (PPE,"INTERVAL_SEC","simple")},
}

# ── Endpoints ─────────────────────────────────────────────────────────────────
@router.get("/")
def get_all():
    js = load_json()
    result = {}
    for pid, cfg in PARAMS.items():
        val = None
        live = False
        # Try Python file first
        fm = cfg.get("file_map")
        if fm:
            fp, var, pat = fm
            try:
                raw = read_file_param(fp, var, pat)
                if raw is not None:
                    val = _cast(raw, cfg["type"])
                    live = True
            except: pass
        # Fall back to JSON
        if val is None:
            val = js.get(pid, cfg["default"])
        result[pid] = {
            "id": pid, "label": cfg["label"], "desc": cfg["desc"],
            "group": cfg["group"], "section": cfg["section"], "dot": cfg["dot"],
            "type": cfg["type"], "opts": cfg.get("opts"), "unit": cfg["unit"],
            "value": val, "default": cfg["default"], "svc": cfg["svc"],
            "file_linked": live,
        }
    return result

class Body(BaseModel):
    value: Any

@router.patch("/{param_id}")
def save_param(param_id: str, body: Body):
    if param_id not in PARAMS: raise HTTPException(404, "Param not found")
    cfg = PARAMS[param_id]
    val = _cast(body.value, cfg["type"])

    # Save to JSON always
    js = load_json()
    js[param_id] = val
    save_json(js)

    # Also write Python file if mapped
    restarted = False
    if cfg.get("file_map"):
        fp, var, pat = cfg["file_map"]
        try:
            write_file_param(fp, var, pat, val)
            restarted = restart_svc(cfg["svc"])
        except Exception as e:
            return {"success": True, "param_id": param_id, "value": val, "json_saved": True, "file_error": str(e)}

    return {"success": True, "param_id": param_id, "value": val,
            "file_linked": bool(cfg.get("file_map")), "restarted": restarted,
            "svc": cfg["svc"]}

def _cast(val, typ):
    if typ == "int":   return int(float(str(val)))
    if typ == "float": return float(str(val))
    if typ == "bool":  return bool(val) if isinstance(val, bool) else str(val).lower() in ("true","1","yes","on")
    return str(val)
