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
S18 = f"{BASE}/18sma-agent/config/settings.py"
S18S = f"{BASE}/18sma-stocks-agent/config/settings.py"
VWAP = f"{BASE}/vwap-agent/config/settings.py"

PARAMS = {
    # --- STRADDLE AGENT (added by patch_straddle2) - Paper/Live mode deliberately NOT editable here ---
    "sd_lots":      {"label":"Lots per leg","desc":"20 lots = 1300 qty per leg. Applies from the NEXT cycle (a running cycle keeps its size)","section":"Size","dot":"dot-gray","type":"int","default":20,"unit":"lots","min":1,"max":50,"file_map":(f"{BASE}/straddle-agent/params.py","LOTS","simple"),"group":"Straddle Agent","svc":"straddle-agent"},
    "sd_entry":     {"label":"Entry time","desc":"Cycle entry on the first trading day after a monthly expiry","section":"Timing","dot":"dot-blue","type":"time","default":"09:30","unit":"","hhmm":True,"file_map":(f"{BASE}/straddle-agent/params.py","ENTRY_TIME","quoted"),"group":"Straddle Agent","svc":"straddle-agent"},
    "sd_roll":      {"label":"Roll / exit time","desc":"Weekly roll and monthly exit time on expiry days","section":"Timing","dot":"dot-blue","type":"time","default":"15:15","unit":"","hhmm":True,"file_map":(f"{BASE}/straddle-agent/params.py","ROLL_TIME","quoted"),"group":"Straddle Agent","svc":"straddle-agent"},
    "sd_min_days":  {"label":"Min days to monthly at entry","desc":"Only start a cycle when the monthly bought is at least this many days away","section":"Timing","dot":"dot-blue","type":"int","default":24,"unit":"days","min":0,"max":35,"file_map":(f"{BASE}/straddle-agent/params.py","MIN_DAYS_TO_MONTHLY_AT_ENTRY","simple"),"group":"Straddle Agent","svc":"straddle-agent"},
    "sd_buy_sl":    {"label":"Buy SL %","desc":"A flipped (long) weekly leg is sold when it falls this % below its buy price","section":"Risk","dot":"dot-amber","type":"float","default":20.0,"unit":"%","min":1,"max":90,"file_map":(f"{BASE}/straddle-agent/params.py","BUY_SL_PCT","simple"),"group":"Straddle Agent","svc":"straddle-agent"},
    "sd_max_loss":  {"label":"Max Loss per cycle","desc":"Close EVERYTHING if the cycle is down this much (Fix 2)","section":"Risk","dot":"dot-amber","type":"int","default":300000,"unit":"Rs","min":10000,"max":5000000,"file_map":(f"{BASE}/straddle-agent/params.py","MAX_LOSS_RS","simple"),"group":"Straddle Agent","svc":"straddle-agent"},

    # --- 18SMA (18 SMA + 2-Candle Breakout) ---
    "s18s_scan_enabled": {"label":"Scanning","desc":"Turn scanning on/off","group":"18SMA-Stocks","section":"General","dot":"dot-teal","type":"select","default":"on","unit":"","svc":"18sma-stocks-agent","opts":["on", "off"],"file_map": (S18S,"SCAN_ENABLED","quoted")},
    "s18s_product": {"label":"Product","desc":"INTRADAY squares off at the time below; CARRYFORWARD holds until option expiry day","group":"18SMA-Stocks","section":"General","dot":"dot-teal","type":"select","default":"INTRADAY","unit":"","svc":"18sma-stocks-agent","opts":["INTRADAY", "CARRYFORWARD"],"file_map": (S18S,"PRODUCT","quoted")},
    "s18s_lots": {"label":"Number of lots","desc":"Lots per signal","group":"18SMA-Stocks","section":"General","dot":"dot-teal","type":"int","default":1,"unit":"lots","svc":"18sma-stocks-agent","file_map": (S18S,"LOTS","simple")},
    "s18s_min_price": {"label":"Skip stocks below","desc":"No scan for stocks priced below this","group":"18SMA-Stocks","section":"General","dot":"dot-teal","type":"float","default":100.0,"unit":"Rs","svc":"18sma-stocks-agent","file_map": (S18S,"MIN_PRICE","simple")},
    "s18s_signal_mode": {"label":"Signal mode","desc":"cross = only the first close beyond SMA; always = every close above/below","group":"18SMA-Stocks","section":"Signal","dot":"dot-teal","type":"select","default":"cross","unit":"","svc":"18sma-stocks-agent","opts":["cross", "always"],"file_map": (S18S,"SIGNAL_MODE","quoted")},
    "s18s_tgt_mode": {"label":"Target mode","desc":"From option BUY price: percent or absolute (Rs)","group":"18SMA-Stocks","section":"Target & stop loss","dot":"dot-teal","type":"select","default":"percent","unit":"","svc":"18sma-stocks-agent","opts":["percent", "absolute"],"file_map": (S18S,"TGT_MODE","quoted")},
    "s18s_tgt_value": {"label":"Target value","desc":"Percent or Rs depending on target mode","group":"18SMA-Stocks","section":"Target & stop loss","dot":"dot-teal","type":"float","default":30.0,"unit":"","svc":"18sma-stocks-agent","file_map": (S18S,"TGT_VALUE","simple")},
    "s18s_sl_mode": {"label":"Stop loss mode","desc":"From option BUY price: percent or absolute (Rs)","group":"18SMA-Stocks","section":"Target & stop loss","dot":"dot-teal","type":"select","default":"percent","unit":"","svc":"18sma-stocks-agent","opts":["percent", "absolute"],"file_map": (S18S,"SL_MODE","quoted")},
    "s18s_sl_value": {"label":"Stop loss value","desc":"Percent or Rs depending on SL mode","group":"18SMA-Stocks","section":"Target & stop loss","dot":"dot-teal","type":"float","default":20.0,"unit":"","svc":"18sma-stocks-agent","file_map": (S18S,"SL_VALUE","simple")},
    "s18s_scan_until": {"label":"Last scan time","desc":"Last candle-close scanned (IST, HH:MM)","group":"18SMA-Stocks","section":"Timing","dot":"dot-teal","type":"str","default":"15:15","unit":"","svc":"18sma-stocks-agent","file_map": (S18S,"SCAN_UNTIL","quoted")},
    "s18s_squareoff": {"label":"Intraday square-off","desc":"INTRADAY signals closed at this time (IST, HH:MM)","group":"18SMA-Stocks","section":"Timing","dot":"dot-teal","type":"str","default":"15:15","unit":"","svc":"18sma-stocks-agent","file_map": (S18S,"SQUAREOFF_TIME","quoted")},
    "s18_timeframe":        {"label":"Timeframe","desc":"Candle/SMA timeframe (minutes) - drives both SMA and candles","group":"18SMA","section":"Signal","dot":"dot-teal","type":"select","opts":["1","3","5","10","15","30","60"],"default":"5","unit":"min","svc":"18sma-agent","file_map": (S18,"TIMEFRAME","simple")},
    "s18_sl_mode":          {"label":"Stop loss mode","desc":"POINTS = fixed points of option price, PERCENT = pct of option price","group":"18SMA","section":"Target & stop loss","dot":"dot-amber","type":"select","opts":["POINTS","PERCENT"],"default":"POINTS","unit":"","svc":"18sma-agent","file_map": (S18,"SL_MODE","quoted")},
    "s18_sl_value":         {"label":"Stop loss value","desc":"Meaning depends on SL mode (points or percent of option price)","group":"18SMA","section":"Target & stop loss","dot":"dot-amber","type":"float","default":15.0,"unit":"","svc":"18sma-agent","file_map": (S18,"SL_VALUE","simple")},
    "s18_target_mode":      {"label":"Target mode","desc":"RR = risk:reward multiple, POINTS = fixed points, PERCENT = pct of option price","group":"18SMA","section":"Target & stop loss","dot":"dot-amber","type":"select","opts":["RR","POINTS","PERCENT"],"default":"RR","unit":"","svc":"18sma-agent","file_map": (S18,"TARGET_MODE","quoted")},
    "s18_target_value":     {"label":"Target value","desc":"Meaning depends on target mode (multiple / points / percent)","group":"18SMA","section":"Target & stop loss","dot":"dot-amber","type":"float","default":2.0,"unit":"","svc":"18sma-agent","file_map": (S18,"TARGET_VALUE","simple")},
    "s18_daily_loss":       {"label":"Daily loss limit","desc":"Stop trading if daily loss exceeds this","group":"18SMA","section":"Risk management","dot":"dot-purple","type":"int","default":20000,"unit":"INR","svc":"18sma-agent","file_map": (S18,"DAILY_LOSS_LIMIT","simple")},
    "s18_nifty_lots":       {"label":"Nifty lots","desc":"Lots per Nifty trade","group":"18SMA","section":"Risk management","dot":"dot-purple","type":"int","default":1,"unit":"lots","svc":"18sma-agent","file_map": (S18,"NIFTY_LOTS","simple")},
    "s18_nifty_lot_size":   {"label":"Nifty lot size","desc":"Units per Nifty lot","group":"18SMA","section":"Risk management","dot":"dot-purple","type":"int","default":65,"unit":"","svc":"18sma-agent","file_map": (S18,"NIFTY_LOT_SIZE","simple")},
    "s18_banknifty_lots":   {"label":"BankNifty lots","desc":"Lots per BankNifty trade","group":"18SMA","section":"Risk management","dot":"dot-purple","type":"int","default":1,"unit":"lots","svc":"18sma-agent","file_map": (S18,"BANKNIFTY_LOTS","simple")},
    "s18_banknifty_lot_size": {"label":"BankNifty lot size","desc":"Units per BankNifty lot","group":"18SMA","section":"Risk management","dot":"dot-purple","type":"int","default":30,"unit":"","svc":"18sma-agent","file_map": (S18,"BANKNIFTY_LOT_SIZE","simple")},
    "s18_sensex_lots":      {"label":"Sensex lots","desc":"Lots per Sensex trade","group":"18SMA","section":"Risk management","dot":"dot-purple","type":"int","default":1,"unit":"lots","svc":"18sma-agent","file_map": (S18,"SENSEX_LOTS","simple")},
    "s18_sensex_lot_size":  {"label":"Sensex lot size","desc":"Units per Sensex lot","group":"18SMA","section":"Risk management","dot":"dot-purple","type":"int","default":20,"unit":"","svc":"18sma-agent","file_map": (S18,"SENSEX_LOT_SIZE","simple")},
    # ---- VWAP ----
    "vwap_timeframe": {"label":"Timeframe","desc":"Candle timeframe (minutes) for VWAP+SD bands","group":"VWAP","section":"Signal","dot":"dot-blue","type":"select","opts":["1","2","3","5","10","15","30","60"],"default":"5","unit":"min","svc":"vwap-agent","file_map": (VWAP,"TIMEFRAME","simple")},
    "vwap_sl_buffer": {"label":"SL buffer","desc":"Stop loss = signal candle low - this buffer","group":"VWAP","section":"Target & stop loss","dot":"dot-amber","type":"float","default":5.0,"unit":"pts","svc":"vwap-agent","file_map": (VWAP,"SL_BUFFER_POINTS","simple")},
    "vwap_daily_loss": {"label":"Daily loss limit","desc":"Stop trading if daily loss exceeds this","group":"VWAP","section":"Risk management","dot":"dot-purple","type":"int","default":20000,"unit":"INR","svc":"vwap-agent","file_map": (VWAP,"DAILY_LOSS_LIMIT","simple")},
    "vwap_nifty_lots": {"label":"Nifty lots","desc":"Total lots per Nifty signal, split across 3 sub-positions","group":"VWAP","section":"Risk management","dot":"dot-purple","type":"int","default":3,"unit":"lots","svc":"vwap-agent","file_map": (VWAP,"NIFTY_LOTS","simple")},
    "vwap_nifty_lot_size": {"label":"Nifty lot size","desc":"Units per Nifty lot","group":"VWAP","section":"Risk management","dot":"dot-purple","type":"int","default":65,"unit":"","svc":"vwap-agent","file_map": (VWAP,"NIFTY_LOT_SIZE","simple")},
    "vwap_banknifty_lots": {"label":"BankNifty lots","desc":"Total lots per BankNifty signal, split across 3 sub-positions","group":"VWAP","section":"Risk management","dot":"dot-purple","type":"int","default":3,"unit":"lots","svc":"vwap-agent","file_map": (VWAP,"BANKNIFTY_LOTS","simple")},
    "vwap_banknifty_lot_size": {"label":"BankNifty lot size","desc":"Units per BankNifty lot","group":"VWAP","section":"Risk management","dot":"dot-purple","type":"int","default":30,"unit":"","svc":"vwap-agent","file_map": (VWAP,"BANKNIFTY_LOT_SIZE","simple")},
    "vwap_sensex_lots": {"label":"Sensex lots","desc":"Total lots per Sensex signal, split across 3 sub-positions","group":"VWAP","section":"Risk management","dot":"dot-purple","type":"int","default":3,"unit":"lots","svc":"vwap-agent","file_map": (VWAP,"SENSEX_LOTS","simple")},
    "vwap_sensex_lot_size": {"label":"Sensex lot size","desc":"Units per Sensex lot","group":"VWAP","section":"Risk management","dot":"dot-purple","type":"int","default":20,"unit":"","svc":"vwap-agent","file_map": (VWAP,"SENSEX_LOT_SIZE","simple")},

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
    if isinstance(val, (int, float)) and not isinstance(val, bool) and (
            ("min" in cfg and val < cfg["min"]) or ("max" in cfg and val > cfg["max"])):
        raise HTTPException(400, f'{cfg["label"]} must be between {cfg.get("min")} and {cfg.get("max")}')
    if cfg.get("hhmm") and not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", str(val)):
        raise HTTPException(400, f'{cfg["label"]} must be HH:MM')

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
