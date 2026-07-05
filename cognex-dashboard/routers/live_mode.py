"""
COGNEX Dashboard — Live Mode Controller
Switches individual strategies between PAPER and LIVE (real AngelOne orders).

How it works:
  1. Dashboard calls POST /api/live/{group}/enable
  2. Backend writes to live_modes.json
  3. Backend updates agent's .env file (TRADING_MODE=LIVE)
  4. Backend restarts the agent service
  5. Agent reads TRADING_MODE on startup and routes orders accordingly

Groups:
  prajnan_ema      → prajnan-agent  (EMA+OBV strategy)
  prajnan_calendar → prajnan-agent  (Calendar Spread strategy)
  trishul          → trishul-agent  (Trishul Mean Reversion)

NOTE: prajnan-agent runs multiple strategies. Setting prajnan_ema OR
prajnan_calendar to LIVE will set the whole prajnan-agent to LIVE.
The strategy-level granularity requires a small agent code change — see
/api/live/agent-instructions for the exact 3 lines to add.
"""

import json, os, subprocess, re
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime

router = APIRouter()

BASE       = "/home/anijay2021"
MODES_FILE = f"{BASE}/cognex-dashboard/live_modes.json"

GROUPS = {
    "prajnan_ema": {
        "label":    "Prajñān — EMA+OBV",
        "agent":    "prajnan-agent",
        "service":  "prajnan-agent",
        "env_file": f"{BASE}/prajnan-agent/.env",
        "env_key":  "TRADING_MODE",
    },
    "prajnan_calendar": {
        "label":    "Prajñān — Calendar Spread",
        "agent":    "prajnan-agent",
        "service":  "prajnan-agent",
        "env_file": f"{BASE}/prajnan-agent/.env",
        "env_key":  "TRADING_MODE",
    },
    "trishul": {
        "label":    "Trishul — Mean Reversion",
        "agent":    "trishul-agent",
        "service":  "trishul-agent",
        "env_file": f"{BASE}/trishul-agent/.env",
        "env_key":  "TRADING_MODE",
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_modes() -> dict:
    defaults = {g: "PAPER" for g in GROUPS}
    if os.path.exists(MODES_FILE):
        try:
            return {**defaults, **json.loads(open(MODES_FILE).read())}
        except Exception:
            pass
    return defaults


def save_modes(modes: dict):
    os.makedirs(os.path.dirname(MODES_FILE), exist_ok=True)
    open(MODES_FILE, "w").write(json.dumps(modes, indent=2))


def _update_env_file(env_path: str, key: str, value: str) -> bool:
    """Update or append KEY=VALUE in an .env file."""
    try:
        if os.path.exists(env_path):
            content = open(env_path).read()
            pattern = rf'^{re.escape(key)}\s*=.*$'
            if re.search(pattern, content, re.MULTILINE):
                content = re.sub(pattern, f'{key}={value}', content, flags=re.MULTILINE)
            else:
                content += f'\n{key}={value}\n'
        else:
            content = f'{key}={value}\n'
        open(env_path, "w").write(content)
        return True
    except Exception:
        return False


def _restart(service: str) -> bool:
    try:
        r = subprocess.run(
            ["sudo", "systemctl", "restart", service],
            capture_output=True, text=True, timeout=15
        )
        return r.returncode == 0
    except Exception:
        return False


def _any_live(modes: dict, agent: str) -> bool:
    """Check if any group pointing to this agent is in LIVE mode."""
    return any(
        modes.get(g) == "LIVE"
        for g, cfg in GROUPS.items()
        if cfg["agent"] == agent
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
def get_modes():
    """Current LIVE/PAPER mode for every strategy group."""
    modes = load_modes()
    return {
        g: {
            "group":   g,
            "label":   GROUPS[g]["label"],
            "mode":    modes.get(g, "PAPER"),
            "agent":   GROUPS[g]["agent"],
            "service": GROUPS[g]["service"],
        }
        for g in GROUPS
    }


@router.post("/{group}/enable")
async def go_live(group: str):
    """
    Switch a strategy to LIVE mode.
    Writes TRADING_MODE=LIVE to agent .env and restarts agent.
    ⚠️  This will place REAL orders on AngelOne.
    """
    if group not in GROUPS:
        raise HTTPException(404, f"Group '{group}' not found")

    cfg   = GROUPS[group]
    modes = load_modes()
    modes[group] = "LIVE"
    save_modes(modes)

    # Update agent .env
    env_updated = _update_env_file(cfg["env_file"], cfg["env_key"], "LIVE")

    # Restart agent
    restarted = _restart(cfg["service"])

    return {
        "group":       group,
        "mode":        "LIVE",
        "env_updated": env_updated,
        "restarted":   restarted,
        "warning":     "⚠️ LIVE MODE — Real orders will be placed on AngelOne",
        "timestamp":   datetime.now().isoformat(),
    }


@router.post("/{group}/disable")
async def go_paper(group: str):
    """Switch a strategy back to PAPER mode."""
    if group not in GROUPS:
        raise HTTPException(404, f"Group '{group}' not found")

    cfg   = GROUPS[group]
    modes = load_modes()
    modes[group] = "PAPER"
    save_modes(modes)

    # Only update .env to PAPER if NO other group on same agent is still LIVE
    if not _any_live(modes, cfg["agent"]):
        _update_env_file(cfg["env_file"], cfg["env_key"], "PAPER")

    restarted = _restart(cfg["service"])

    return {
        "group":     group,
        "mode":      "PAPER",
        "restarted": restarted,
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/agent-instructions")
def agent_instructions():
    """
    Returns the exact code change needed in each agent to support
    per-strategy live mode from this dashboard.
    """
    return {
        "summary": "Add 6 lines to each strategy's scan function to read live_modes.json",
        "modes_file": MODES_FILE,
        "changes_needed": [
            {
                "agent":    "prajnan-agent",
                "file":     "~/prajnan-agent/strategies/ema_obv_scanner.py",
                "group_key": "prajnan_ema",
                "add_at_top": """
import json as _json, os as _os
def _get_mode():
    try: return _json.loads(open('/home/anijay2021/cognex-dashboard/live_modes.json').read()).get('prajnan_ema','PAPER')
    except: return 'PAPER'
""",
                "change": "Replace `mode = settings.trading_mode` with `mode = _get_mode()`",
            },
            {
                "agent":    "prajnan-agent",
                "file":     "~/prajnan-agent/strategies/calendar_spread_strategy.py",
                "group_key": "prajnan_calendar",
                "add_at_top": """
import json as _json
def _get_mode():
    try: return _json.loads(open('/home/anijay2021/cognex-dashboard/live_modes.json').read()).get('prajnan_calendar','PAPER')
    except: return 'PAPER'
""",
                "change": "Replace `mode = settings.trading_mode` with `mode = _get_mode()`",
            },
            {
                "agent":    "trishul-agent",
                "file":     "~/trishul-agent/main.py",
                "group_key": "trishul",
                "add_at_top": """
import json as _json
def _get_mode():
    try: return _json.loads(open('/home/anijay2021/cognex-dashboard/live_modes.json').read()).get('trishul','PAPER')
    except: return 'PAPER'
""",
                "change": "Replace any hardcoded 'PAPER' mode check with `_get_mode()`",
            },
        ],
    }
