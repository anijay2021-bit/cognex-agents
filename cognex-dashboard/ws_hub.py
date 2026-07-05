"""
COGNEX Dashboard — WebSocket Hub + Background Tasks
"""

import asyncio
import json
import os
import subprocess
from datetime import datetime
from typing import List
from fastapi import WebSocket, APIRouter

from log_parser import parse_line, parse_last_n_lines
from config import AGENTS, LOG_TAIL_LINES, LOG_BROADCAST_INTERVAL

ws_router = APIRouter()


class Hub:
    def __init__(self):
        self.connections: List[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.connections.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.connections:
            self.connections.remove(ws)

    async def broadcast(self, msg: dict):
        if not self.connections:
            return
        payload = json.dumps(msg, default=str)
        dead = []
        for ws in list(self.connections):
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    async def send_one(self, ws: WebSocket, msg: dict):
        try:
            await ws.send_text(json.dumps(msg, default=str))
        except Exception:
            self.disconnect(ws)


hub = Hub()


def _now():
    return datetime.now().isoformat()


@ws_router.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    await hub.connect(websocket)
    for agent_id, cfg in AGENTS.items():
        log_path = cfg.get("log")
        if log_path and os.path.exists(log_path):
            lines = parse_last_n_lines(log_path, LOG_TAIL_LINES)
            for raw in lines:
                parsed = parse_line(raw, agent_id)
                if parsed:
                    await hub.send_one(websocket, {"type": "log_line", **parsed})

    await hub.send_one(websocket, {
        "type": "connected",
        "timestamp": _now(),
        "data": {"message": "COGNEX Dashboard connected"},
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await hub.send_one(websocket, {"type": "pong", "timestamp": _now()})
            except Exception:
                pass
    except Exception:
        hub.disconnect(websocket)


async def tail_agent_log(agent_id: str, log_path: str):
    try:
        with open(log_path, "r") as f:
            f.seek(0, 2)
            file_pos = f.tell()
    except Exception:
        file_pos = 0

    while True:
        await asyncio.sleep(LOG_BROADCAST_INTERVAL)
        try:
            if not os.path.exists(log_path):
                continue
            with open(log_path, "r", errors="replace") as f:
                f.seek(file_pos)
                new_lines = f.readlines()
                file_pos = f.tell()
            for raw in new_lines:
                parsed = parse_line(raw, agent_id)
                if parsed:
                    await hub.broadcast({"type": "log_line", **parsed})
        except Exception:
            pass


async def tail_trishul_journal():
    try:
        proc = await asyncio.create_subprocess_exec(
            "journalctl", "-u", "trishul-agent", "-f", "--no-pager", "-o", "short-iso",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        while True:
            line = await proc.stdout.readline()
            if not line:
                await asyncio.sleep(1)
                continue
            raw = line.decode("utf-8", errors="replace").strip()
            msg_match = raw.split("]: ", 1)
            msg = msg_match[1] if len(msg_match) > 1 else raw
            await hub.broadcast({
                "type": "log_line",
                "agent": "trishul",
                "timestamp": _now(),
                "level": "INFO",
                "module": "systemd",
                "message": msg,
                "raw": raw,
                "parsed": {},
                "event": "system_event" if "systemd" in raw else None,
            })
    except Exception:
        pass


async def broadcast_agent_statuses():
    while True:
        await asyncio.sleep(10)
        statuses = {}
        for agent_id, cfg in AGENTS.items():
            service = cfg["service"]
            try:
                result = subprocess.run(
                    ["systemctl", "is-active", service],
                    capture_output=True, text=True, timeout=3
                )
                active = result.stdout.strip()
                result2 = subprocess.run(
                    ["systemctl", "show", service,
                     "--property=ActiveEnterTimestamp,MainPID,MemoryCurrent"],
                    capture_output=True, text=True, timeout=3
                )
                props = {}
                for prop_line in result2.stdout.strip().splitlines():
                    if "=" in prop_line:
                        k, v = prop_line.split("=", 1)
                        props[k] = v
                mem = int(props.get("MemoryCurrent", 0) or 0)
                statuses[agent_id] = {
                    "status":    active,
                    "running":   active == "active",
                    "pid":       props.get("MainPID", ""),
                    "started":   props.get("ActiveEnterTimestamp", ""),
                    "memory_mb": round(mem / 1024 / 1024, 1),
                    "service":   service,
                }
            except Exception:
                statuses[agent_id] = {"status": "unknown", "running": False, "service": service}
        await hub.broadcast({"type": "agent_status", "data": statuses, "timestamp": _now()})


async def broadcast_db_snapshots():
    from db_reader import get_agent_summary
    while True:
        await asyncio.sleep(5)
        for agent_id, cfg in AGENTS.items():
            db_path = cfg.get("db")
            if db_path and os.path.exists(db_path):
                try:
                    summary = await get_agent_summary(db_path, agent_id)
                    await hub.broadcast({
                        "type": "db_snapshot",
                        "agent": agent_id,
                        "data": summary,
                        "timestamp": _now(),
                    })
                except Exception:
                    pass


async def start_background_tasks():
    """Called from FastAPI lifespan."""
    for agent_id, cfg in AGENTS.items():
        log_path = cfg.get("log")
        if log_path:
            asyncio.create_task(tail_agent_log(agent_id, log_path))

    asyncio.create_task(tail_trishul_journal())
    asyncio.create_task(broadcast_agent_statuses())
    asyncio.create_task(broadcast_db_snapshots())

    # Fyers LTP feed
    try:
        from market_data import start_ltp_feed
        asyncio.create_task(start_ltp_feed(hub))
        print("📡 Fyers LTP feed scheduled")
    except Exception as e:
        print(f"⚠️  Fyers LTP feed skipped: {e}")
