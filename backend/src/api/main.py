"""FastAPI app for the live pipeline UI.

    uvicorn src.api.main:app --port 8000        (or: bash scripts/run_api.sh)

On startup the ADK case manager is served as a real A2A endpoint (its own HTTP
listener, SQLite-backed ADK sessions in logs/cases.db) and the pipeline talks to
it through ``RemoteA2AClient`` - the ``a2a_hop`` stage is a real network hop.
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
from src.observability import init_tracing


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    init_tracing()
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
    """Status for the UI. Never includes keys; only which models are configured."""
    from src.crewai_layer.crew import uses_chain
    from src.llm_chain import get_chain

    available = llm_available()
    llm: dict = {"available": available}
    if uses_chain():
        llm["chain"] = get_chain().describe()
        llm["events"] = get_chain().events[-5:]
    from src.observability import langfuse_configured
    from src.security.public_mode import limiter, public_mode

    pub = public_mode()
    return {"ok": True, "llm_available": available, "llm": llm, "a2a_url": app.state.a2a_url,
            "stages": STAGES, "public_mode": pub,
            "llm_runs_left_today": limiter().llm_runs_left() if pub else None,
            "tracing": {"file": True, "langfuse": langfuse_configured()}}


_CALLBACK_PAGE = ("<!doctype html><meta charset=utf-8><title>MCP Guardian</title>"
                  "<body style='font:16px system-ui;padding:3rem;max-width:34rem;margin:auto'>"
                  "<h2>{title}</h2><p>{body}</p><script>setTimeout(()=>window.close(),1500)</script>")


@app.get("/oauth/callback")
def oauth_callback(state: str = "", code: str | None = None, error: str | None = None):
    """Where a server's sign-in page sends the visitor back. Hands the code to the run that is waiting."""
    from fastapi.responses import HTMLResponse

    from src.api.live_server import complete_oauth

    if complete_oauth(state, code, error):
        page = _CALLBACK_PAGE.format(title="Signed in", body="You can close this window and return to MCP Guardian.")
        return HTMLResponse(page)
    return HTMLResponse(_CALLBACK_PAGE.format(
        title="Nothing is waiting for this sign-in",
        body="The check may have timed out. Go back to MCP Guardian and start it again."), status_code=400)


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
