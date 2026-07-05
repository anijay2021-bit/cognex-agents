"""
COGNEX Dashboard — Agents Router
GET status, systemctl start/stop/restart per agent.
"""

import subprocess
from fastapi import APIRouter, HTTPException
from config import AGENTS
from ws_hub import hub
from datetime import datetime

router = APIRouter()


def _systemctl(action: str, service: str) -> dict:
    try:
        result = subprocess.run(
            ["sudo", "systemctl", action, service],
            capture_output=True, text=True, timeout=10
        )
        return {
            "success": result.returncode == 0,
            "output":  result.stdout.strip() or result.stderr.strip(),
        }
    except Exception as e:
        return {"success": False, "output": str(e)}


def _get_status(service: str) -> dict:
    try:
        active = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()

        props_out = subprocess.run(
            ["systemctl", "show", service,
             "--property=ActiveEnterTimestamp,MainPID,MemoryCurrent,ExecMainStartTimestamp"],
            capture_output=True, text=True, timeout=5
        ).stdout.strip()

        props = {}
        for line in props_out.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k] = v

        mem_bytes = int(props.get("MemoryCurrent", 0) or 0)

        return {
            "status":    active,
            "running":   active == "active",
            "pid":       props.get("MainPID", ""),
            "started_at": props.get("ActiveEnterTimestamp", ""),
            "memory_mb": round(mem_bytes / 1024 / 1024, 1),
            "service":   service,
        }
    except Exception:
        return {"status": "unknown", "running": False, "service": service}


@router.get("/")
def list_agents():
    """All agents with current systemd status."""
    result = []
    for agent_id, cfg in AGENTS.items():
        status = _get_status(cfg["service"])
        result.append({
            "id":           agent_id,
            "display_name": cfg["display_name"],
            "account":      cfg["account"],
            "strategies":   cfg["strategies"],
            "broker_data":  cfg["broker_data"],
            "broker_exec":  cfg["broker_exec"],
            "has_db":       cfg["db"] is not None,
            **status,
        })
    return result


@router.get("/{agent_id}")
def get_agent(agent_id: str):
    if agent_id not in AGENTS:
        raise HTTPException(404, f"Agent '{agent_id}' not found")
    cfg = AGENTS[agent_id]
    return {"id": agent_id, **cfg, **_get_status(cfg["service"])}


@router.post("/{agent_id}/start")
async def start_agent(agent_id: str):
    if agent_id not in AGENTS:
        raise HTTPException(404)
    service = AGENTS[agent_id]["service"]
    result  = _systemctl("start", service)
    await hub.broadcast({
        "type": "agent_status",
        "data": {agent_id: _get_status(service)},
        "timestamp": datetime.now().isoformat(),
    })
    await hub.broadcast({
        "type": "log_line",
        "agent": agent_id,
        "timestamp": datetime.now().isoformat(),
        "level": "INFO",
        "module": "dashboard",
        "message": f"▶ {service} START requested from dashboard",
        "event": "system_event",
        "parsed": {},
    })
    return result


@router.post("/{agent_id}/stop")
async def stop_agent(agent_id: str):
    if agent_id not in AGENTS:
        raise HTTPException(404)
    service = AGENTS[agent_id]["service"]
    result  = _systemctl("stop", service)
    await hub.broadcast({
        "type": "agent_status",
        "data": {agent_id: _get_status(service)},
        "timestamp": datetime.now().isoformat(),
    })
    await hub.broadcast({
        "type": "log_line",
        "agent": agent_id,
        "timestamp": datetime.now().isoformat(),
        "level": "WARNING",
        "module": "dashboard",
        "message": f"⏹ {service} STOP requested from dashboard",
        "event": "system_event",
        "parsed": {},
    })
    return result


@router.post("/{agent_id}/restart")
async def restart_agent(agent_id: str):
    if agent_id not in AGENTS:
        raise HTTPException(404)
    service = AGENTS[agent_id]["service"]
    result  = _systemctl("restart", service)
    await hub.broadcast({
        "type": "log_line",
        "agent": agent_id,
        "timestamp": datetime.now().isoformat(),
        "level": "WARNING",
        "module": "dashboard",
        "message": f"🔄 {service} RESTART requested from dashboard",
        "event": "system_event",
        "parsed": {},
    })
    return result
