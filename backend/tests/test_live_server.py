"""Credentials, secret scrubbing, transport probing and the guarded client for the "Check a server" page.
A tiny local ASGI app plays the remote server; no model and no internet are involved."""
from __future__ import annotations

import asyncio
import socket
import threading
import time

import httpx
import pytest

uvicorn = pytest.importorskip("uvicorn")

from src.api import live_server as live  # noqa: E402
from src.security import public_mode as pm  # noqa: E402


def test_bearer_header_and_query_values_are_all_secrets():
    c = live.parse_credentials({"type": "bearer", "token": "Bearer abc123xyz"}, "https://h.example/mcp?apikey=KEY-9999")
    assert c.headers == {"Authorization": "Bearer abc123xyz"}
    assert set(c.secrets) == {"abc123xyz", "KEY-9999"}


def test_bad_credentials_are_refused():
    for bad in ({"type": "bearer", "token": " "}, {"type": "header", "name": "X Y", "value": "v"},
                {"type": "header", "name": "Host", "value": "evil"}, {"type": "wat"}, "oops"):
        with pytest.raises(live.AuthError):
            live.parse_credentials(bad, "https://h.example/mcp")


def test_scrub_and_display_url_hide_every_secret():
    out = live.scrub({"a": ["x SECRET1 y"], "b": "SECRET1/SECRET2"}, ["SECRET1", "SECRET2"])
    assert "SECRET" not in str(out)
    assert "KEY-9999" not in live.display_url("https://h.example/mcp?apikey=KEY-9999")
    assert live.server_key("https://h.example/mcp?apikey=1") == live.server_key("https://h.example/mcp?apikey=2")


async def _app(scope, receive, send):
    if scope["type"] != "http":
        return
    path, method = scope["path"], scope["method"]
    auth = dict(scope["headers"]).get(b"authorization", b"").decode()

    async def reply(status, ctype=b"application/json", body=b"{}", extra=()):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", ctype), *extra]})
        await send({"type": "http.response.body", "body": body})

    if path == "/mcp":
        if auth != "Bearer good":
            return await reply(401, extra=[(b"www-authenticate", b'Bearer resource_metadata="x"')])
        return await reply(200)
    if path == "/host":
        return await reply(200, b"text/plain", dict(scope["headers"]).get(b"host", b""))
    if path == "/open":
        return await reply(200)
    if path == "/sse" and method == "GET":
        return await reply(200, b"text/event-stream", b"event: endpoint\ndata: /m\n\n")
    if path == "/hop":
        return await reply(302, extra=[(b"location", b"http://10.255.255.1/x")])
    return await reply(404)


@pytest.fixture(scope="module")
def base():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(_app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True


def test_probe_detects_auth_and_transports(base):
    p = asyncio.run(live.probe_endpoint(f"{base}/mcp", {}))
    assert p.auth_required and p.oauth_advertised and p.transport is None
    ok = asyncio.run(live.probe_endpoint(f"{base}/mcp", {"Authorization": "Bearer good"}))
    assert ok.transport == "streamable-http" and not ok.auth_required
    sse = asyncio.run(live.probe_endpoint(f"{base}/sse", {}))
    assert sse.transport == "sse"
    nope = asyncio.run(live.probe_endpoint(f"{base}/nothing", {}))
    assert nope.transport is None and "not an MCP endpoint" in nope.error


def test_guarded_client_refuses_a_redirect_to_an_internal_address(base, monkeypatch):
    monkeypatch.setenv("GUARDIAN_PUBLIC", "1")

    async def go():
        async with live.guarded_client_factory() as c:
            await c.get(f"{base}/hop")

    with pytest.raises(live.DestinationBlocked):          # 127.0.0.1 is not a public address
        asyncio.run(go())


def test_connection_is_pinned_to_the_address_that_was_validated(base, monkeypatch):
    """DNS rebinding: the name answers once; the connection must use that answer, not resolve again."""
    monkeypatch.setenv("GUARDIAN_PUBLIC", "1")
    answers = iter([["127.0.0.1"], ["10.0.0.1"], ["10.0.0.1"]])
    calls = []
    monkeypatch.setattr(live, "_resolve", lambda name: calls.append(name) or next(answers))
    monkeypatch.setattr(live, "_is_public", lambda ip: ip == "127.0.0.1")     # the first answer passes the check
    port = base.rsplit(":", 1)[1]

    async def go():
        async with live.guarded_client_factory() as c:
            r = await c.get(f"http://rebind.test:{port}/host")
            return r.text

    assert asyncio.run(go()) == f"rebind.test:{port}"      # reached the validated IP, Host header kept
    assert calls == ["rebind.test"]                         # resolved exactly once


def test_a_name_that_resolves_to_an_internal_address_is_refused(monkeypatch):
    monkeypatch.setenv("GUARDIAN_PUBLIC", "1")
    monkeypatch.setattr(live, "_resolve", lambda name: ["93.184.216.34", "10.0.0.5"])

    async def go():
        async with live.guarded_client_factory() as c:
            await c.get("http://mixed.test/")

    with pytest.raises(live.DestinationBlocked):
        asyncio.run(go())


def test_oauth_callback_resolves_only_a_waiting_run():
    assert live.complete_oauth("unknown", "code", None) is False

    async def go():
        fut = asyncio.get_running_loop().create_future()
        live._PENDING["st"] = fut
        assert live.complete_oauth("st", "the-code", None) is True
        return await fut

    assert asyncio.run(go()) == ("the-code", "st")
    live._PENDING.pop("st", None)


def test_oauth_sessions_are_private_and_reusable():
    sid, store = live.oauth_session_secret(None)
    assert live.oauth_session_secret(sid)[1] is store
    assert live.oauth_session_secret("not-a-real-id")[0] != "not-a-real-id"
    assert not live.has_oauth_tokens(sid)


# ---- a real MCP server (streamable HTTP, bearer-protected) driven through the WebSocket pipeline ----

@pytest.fixture(scope="module")
def mcp_base():
    pytest.importorskip("mcp.server.fastmcp")
    from mcp.server.fastmcp import FastMCP

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    mcp = FastMCP("fixture", host="127.0.0.1", port=port, stateless_http=True)

    @mcp.tool()
    def add(a: int, b: int) -> int:
        """Add two integers."""
        return a + b

    for i in range(6):
        mcp.tool(name=f"echo_{i}", description=f"Echo number {i} back.")(lambda text="x": text)

    inner = mcp.streamable_http_app()

    async def guarded(scope, receive, send):
        if scope["type"] == "http":
            tok = dict(scope["headers"]).get(b"authorization", b"").decode()
            if tok != "Bearer sekret-token-77":
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
                return
        await inner(scope, receive, send)

    async def app(scope, receive, send):
        if scope["type"] == "lifespan":
            await inner(scope, receive, send)
        else:
            await guarded(scope, receive, send)

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True


@pytest.fixture()
def client():
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _run_ws(client, req):
    out = []
    with client.websocket_connect("/ws/run") as ws:
        ws.send_json(req)
        try:
            while True:
                out.append(ws.receive_json())
        except Exception:
            pass
    return out


def test_pipeline_reports_that_the_server_wants_credentials(client, mcp_base):
    evs = _run_ws(client, {"server_url": mcp_base, "inspect_only": True, "use_llm": False})
    err = next(e for e in evs if e["stage"] == "connect" and e["status"] == "error")
    assert err["detail"]["auth_required"] is True and "requires authentication" in err["message"]


def test_pipeline_inspects_a_bearer_protected_server_and_never_leaks_the_token(client, mcp_base):
    evs = _run_ws(client, {"server_url": f"{mcp_base}?apikey=URLKEY-4242", "inspect_only": True, "use_llm": False,
                           "auth": {"type": "bearer", "token": "sekret-token-77"}})
    done = evs[-1]
    assert done["stage"] == "done" and done["detail"]["inspect_only"]
    assert len(done["detail"]["tools"]) == 7
    dump = str(evs)
    assert "sekret-token-77" not in dump and "URLKEY-4242" not in dump


def test_wrong_token_is_reported_as_rejected(client, mcp_base):
    evs = _run_ws(client, {"server_url": mcp_base, "inspect_only": True, "use_llm": False,
                           "auth": {"type": "bearer", "token": "wrong-token"}})
    err = next(e for e in evs if e["stage"] == "connect" and e["status"] == "error")
    assert "rejected the credentials" in err["message"]
    assert "wrong-token" not in str(evs)
