"""FastAPI app for the live pipeline UI.

    uvicorn src.api.main:app --port 8000        (or: bash scripts/run_api.sh)

On startup the ADK case manager is served as a real A2A endpoint (its own HTTP
listener, SQLite-backed ADK sessions in logs/cases.db) and the pipeline talks to
it through ``RemoteA2AClient`` — the ``a2a_hop`` stage is a genuine network hop.
"""
from __future__ import annotations

import contextlib

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.a2a_bridge.a2a_server import serve_in_background
from src.a2a_bridge.bridge import RemoteA2AClient
from src.adk_layer.pipeline_manager import PipelineManager
from src.api import runner, servers
from src.api.events import STAGES
from src.config import REPO_ROOT, resolve_path
from src.crewai_layer.crew import llm_available


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    db = resolve_path("fingerprint_db").with_name("cases.db")
    manager = PipelineManager(db_path=str(db))
    async with serve_in_background(manager) as a2a_url:
        client = RemoteA2AClient({"pipeline_manager": a2a_url})
        app.state.manager = manager
        app.state.a2a_url = a2a_url
        app.state.a2a_client = client
        try:
            yield
        finally:
            await client.aclose()


app = FastAPI(title="MCP Guardian live pipeline", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)
app.include_router(servers.router)
app.include_router(runner.router)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "llm_available": llm_available(), "a2a_url": app.state.a2a_url,
            "stages": STAGES}


@app.post("/servers/{server_id}/reset")
def reset_server(server_id: str) -> dict:
    """Forget a server's behavioural history (and fixture call counts)."""
    try:
        servers.get_spec(server_id)
    except KeyError:
        raise HTTPException(404, f"unknown server '{server_id}'")
    runner.reset_server_state(server_id)
    return {"reset": server_id}


# Serve the built React app (frontend/dist) at / when it exists.
_DIST = REPO_ROOT / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=_DIST, html=True), name="frontend")
