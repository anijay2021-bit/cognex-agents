from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import uvicorn, os
from ws_hub import ws_router, start_background_tasks
from routers.agents import router as agents_router
from routers.trades import router as trades_router
from routers.config_editor import router as config_router
from routers.live_mode import router as live_router

@asynccontextmanager
async def lifespan(app):
    await start_background_tasks()
    print("COGNEX Dashboard started")
    yield

app = FastAPI(title="COGNEX Dashboard", version="2.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:8000","http://127.0.0.1:8000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

import base64, secrets as _secrets
_DASH_USER = os.environ.get("DASH_USER", "")
_DASH_PASS = os.environ.get("DASH_PASS", "")

@app.middleware("http")
async def _basic_auth(request, call_next):
    # Auth active only when BOTH env vars are set (dashboard is localhost-only)
    if not _DASH_USER or not _DASH_PASS:
        return await call_next(request)
    p = request.url.path
    if p == "/api/health" or p.startswith("/ws"):
        return await call_next(request)
    hdr = request.headers.get("authorization", "")
    ok = False
    if hdr.startswith("Basic "):
        try:
            u, _, pw = base64.b64decode(hdr[6:]).decode().partition(":")
            ok = _secrets.compare_digest(u, _DASH_USER) and _secrets.compare_digest(pw, _DASH_PASS)
        except Exception:
            ok = False
    if not ok:
        from starlette.responses import Response
        return Response(status_code=401, headers={"WWW-Authenticate": "Basic realm=COGNEX"})
    return await call_next(request)
app.include_router(ws_router)
app.include_router(agents_router, prefix="/api/agents", tags=["Agents"])
app.include_router(trades_router, prefix="/api/data",   tags=["Data"])
app.include_router(config_router, prefix="/api/config", tags=["Config"])
app.include_router(live_router,   prefix="/api/live",   tags=["Live Mode"])

@app.get("/api/health")
def health():
    return {"status": "ok", "version": "2.1.0"}

_sd = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(_sd) and os.listdir(_sd):
    app.mount("/", StaticFiles(directory=_sd, html=True), name="static")
