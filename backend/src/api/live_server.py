"""Everything the "Check a server" page needs to reach an arbitrary remote MCP endpoint.

* credentials the visitor supplies (bearer token, custom header, API key in the URL, or OAuth) and how they
  are kept: in memory for the duration of a run, never written to logs, traces, events or disk;
* an HTTP client used for every outgoing request that re-checks the destination on each hop, so redirects
  and OAuth discovery documents cannot lead the server to an internal address (public mode);
* a probe that finds out which transport the endpoint speaks (streamable HTTP or legacy SSE) and whether
  it wants credentials, so a failure can be explained instead of timing out;
* the OAuth 2.1 authorisation-code flow (with dynamic client registration) driven through the browser.
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlsplit, urlunsplit

import httpx

from src.security.public_mode import check_public_target, public_mode

AUTH_TYPES = ("none", "bearer", "header", "oauth")
MAX_SECRET = 4096
OAUTH_WAIT_S = 240
OAUTH_SESSION_TTL_S = 3600
PROBE_TIMEOUT_S = 15
_REDACTED = "***"


class AuthError(ValueError):
    """The credentials in the request are unusable (message is shown to the visitor)."""


@dataclass
class Credentials:
    """Parsed ``auth`` block of a run request. ``secrets`` lists every value that must never be shown."""
    kind: str = "none"
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    oauth_session: Optional[str] = None
    secrets: list[str] = field(default_factory=list, repr=False)


def parse_credentials(auth: Any, url: str) -> Credentials:
    """Validate the request's ``auth`` object and the URL's own query string.

    Accepted shapes: ``{"type": "bearer", "token": ...}``, ``{"type": "header", "name": ..., "value": ...}``,
    ``{"type": "oauth", "session": <id from an earlier run, optional>}``, or nothing."""
    cred = Credentials()
    # every query value in the address (``?apikey=...``) is treated as a secret
    for _, value in parse_qsl(urlsplit(url).query, keep_blank_values=False):
        if len(value) >= 4:
            cred.secrets.append(value)
    if not auth:
        return cred
    if not isinstance(auth, dict):
        raise AuthError("The authentication settings are malformed.")
    kind = str(auth.get("type") or "none").lower()
    if kind not in AUTH_TYPES:
        raise AuthError(f"Unknown authentication type '{kind}'.")
    cred.kind = kind
    if kind == "bearer":
        token = str(auth.get("token") or "").strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token:
            raise AuthError("Enter the bearer token, or choose “No authentication”.")
        _check_secret(token)
        cred.headers["Authorization"] = f"Bearer {token}"
        cred.secrets.append(token)
    elif kind == "header":
        name = str(auth.get("name") or "").strip()
        value = str(auth.get("value") or "").strip()
        if not name or not value:
            raise AuthError("Enter both the header name and its value.")
        if not name.replace("-", "").replace("_", "").isalnum():
            raise AuthError("The header name may only contain letters, digits, '-' and '_'.")
        if name.lower() in ("host", "content-length", "transfer-encoding", "connection", "content-type", "accept"):
            raise AuthError(f"The header '{name}' cannot be set here.")
        _check_secret(value)
        cred.headers[name] = value
        cred.secrets.append(value)
    elif kind == "oauth":
        session = auth.get("session")
        cred.oauth_session = str(session) if session else None
    return cred


def _check_secret(value: str) -> None:
    if len(value) > MAX_SECRET or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise AuthError("A credential is too long or contains control characters.")


def scrub(value: Any, secret_values: list[str]) -> Any:
    """Replace every secret in any string nested inside ``value`` (dicts, lists, strings)."""
    if not secret_values:
        return value
    if isinstance(value, str):
        out = value
        for s in secret_values:
            if s:
                out = out.replace(s, _REDACTED)
        return out
    if isinstance(value, dict):
        return {k: scrub(v, secret_values) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v, secret_values) for v in value]
    return value


def display_url(url: str) -> str:
    """The address without its query values, safe to show and log."""
    parts = urlsplit(url)
    if not parts.query:
        return url
    q = urlencode([(k, _REDACTED) for k, _ in parse_qsl(parts.query, keep_blank_values=True)], safe="*")
    return urlunsplit((parts.scheme, parts.netloc, parts.path, q, ""))


def server_key(url: str) -> str:
    """Stable id of a server regardless of credentials (so a rotated key keeps its fingerprint history)."""
    p = urlsplit(url)
    return "custom-" + hashlib.sha1(f"{p.scheme}://{p.netloc}{p.path}".encode()).hexdigest()[:10]


# ---------------------------------------------------------------- guarded HTTP client

class DestinationBlocked(httpx.RequestError):
    """A request (or a redirect hop) was refused because the target is not a public address."""


async def _guard_request(request: httpx.Request) -> None:
    if not public_mode():
        return
    err = await asyncio.to_thread(check_public_target, str(request.url))
    if err:
        raise DestinationBlocked(err, request=request)


def guarded_client_factory(headers: dict[str, str] | None = None, timeout: httpx.Timeout | None = None,
                           auth: httpx.Auth | None = None) -> httpx.AsyncClient:
    """Drop-in for the MCP SDK's ``create_mcp_http_client`` that checks every hop's destination.

    The check runs just before each request is sent, including each redirect hop and every URL the OAuth
    flow discovers, so none of them can reach an internal address. It resolves the name itself, so a host
    that changes its DNS answer in the instant between check and connect is not fully excluded."""
    return httpx.AsyncClient(
        follow_redirects=True,
        max_redirects=5,
        timeout=timeout or httpx.Timeout(30.0, read=300.0),
        headers=headers,
        auth=auth,
        event_hooks={"request": [_guard_request]},
    )


# ---------------------------------------------------------------- endpoint probe

@dataclass
class Probe:
    transport: Optional[str] = None       # "streamable-http" | "sse" | None
    auth_required: bool = False
    oauth_advertised: bool = False
    status: Optional[int] = None
    error: Optional[str] = None


_INIT = {"jsonrpc": "2.0", "id": 0, "method": "initialize",
         "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "mcp-guardian-probe", "version": "1"}}}


async def probe_endpoint(url: str, headers: dict[str, str]) -> Probe:
    """Ask the endpoint what it is, with one POST (streamable HTTP) and, failing that, one GET (SSE)."""
    result = Probe()
    base = dict(headers)
    try:
        async with guarded_client_factory(timeout=httpx.Timeout(PROBE_TIMEOUT_S)) as client:
            post_headers = {**base, "Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
            async with client.stream("POST", url, headers=post_headers, json=_INIT) as r:
                result.status = r.status_code
                ctype = r.headers.get("content-type", "").lower()
                if r.status_code in (401, 403):
                    result.auth_required = True
                    www = r.headers.get("www-authenticate", "").lower()
                    result.oauth_advertised = "resource_metadata" in www or "bearer" in www
                    return result
                if r.status_code < 300 and ("json" in ctype or "event-stream" in ctype):
                    result.transport = "streamable-http"
                    return result
            get_headers = {**base, "Accept": "text/event-stream"}
            async with client.stream("GET", url, headers=get_headers) as r:
                result.status = r.status_code
                if r.status_code in (401, 403):
                    result.auth_required = True
                    return result
                if r.status_code < 300 and "event-stream" in r.headers.get("content-type", "").lower():
                    result.transport = "sse"
                    return result
            result.error = (f"The address answered HTTP {result.status} and is not an MCP endpoint "
                            "(neither streamable HTTP nor SSE).")
    except DestinationBlocked as exc:
        result.error = str(exc)
    except httpx.TimeoutException:
        result.error = "The server did not answer within 15 seconds."
    except httpx.HTTPError as exc:
        result.error = f"Cannot reach the server ({type(exc).__name__}): nothing is listening at that address."
    return result


# ---------------------------------------------------------------- OAuth

class _Storage:
    """Token and client-registration storage for one visitor's session: memory only."""

    def __init__(self) -> None:
        self.tokens: Any = None
        self.client_info: Any = None
        self.created = time.time()

    async def get_tokens(self):
        return self.tokens

    async def set_tokens(self, tokens) -> None:
        self.tokens = tokens

    async def get_client_info(self):
        return self.client_info

    async def set_client_info(self, info) -> None:
        self.client_info = info


_SESSIONS: dict[str, _Storage] = {}
_PENDING: dict[str, asyncio.Future] = {}        # OAuth `state` -> future resolved by /oauth/callback


def _prune() -> None:
    now = time.time()
    for sid in [k for k, v in _SESSIONS.items() if now - v.created > OAUTH_SESSION_TTL_S]:
        _SESSIONS.pop(sid, None)


def oauth_session_secret(session_id: Optional[str]) -> tuple[str, _Storage]:
    _prune()
    if session_id and session_id in _SESSIONS:
        return session_id, _SESSIONS[session_id]
    sid = secrets.token_urlsafe(24)
    _SESSIONS[sid] = _Storage()
    return sid, _SESSIONS[sid]


def has_oauth_tokens(session_id: Optional[str]) -> bool:
    s = _SESSIONS.get(session_id or "")
    return bool(s and s.tokens)


def complete_oauth(state: str, code: Optional[str], error: Optional[str]) -> bool:
    """Called by ``GET /oauth/callback``. Returns False if no run is waiting for this state."""
    fut = _PENDING.get(state)
    if fut is None or fut.done():
        return False
    if error or not code:
        fut.set_exception(AuthError(f"The server's sign-in page reported: {error or 'no code returned'}."))
    else:
        fut.set_result((code, state))
    return True


def build_oauth(url: str, redirect_uri: str, storage: _Storage,
                announce: Callable[[str], Awaitable[None]]):
    """An ``httpx.Auth`` that signs in with OAuth. ``announce(auth_url)`` tells the browser to open the page."""
    from mcp.client.auth import OAuthClientProvider
    from mcp.shared.auth import OAuthClientMetadata

    metadata = OAuthClientMetadata(
        client_name="MCP Guardian",
        redirect_uris=[redirect_uri],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        token_endpoint_auth_method="none",
    )

    mine: dict[str, str] = {}

    async def redirect_handler(auth_url: str) -> None:
        state = dict(parse_qsl(urlsplit(auth_url).query)).get("state")
        if not state:
            raise AuthError("The server's sign-in address carries no state value.")
        mine["state"] = state
        _PENDING[state] = asyncio.get_running_loop().create_future()
        await announce(auth_url)

    async def callback_handler() -> tuple[str, Optional[str]]:
        state = mine.get("state")
        if state is None or state not in _PENDING:
            raise AuthError("No sign-in is in progress.")
        try:
            return await asyncio.wait_for(_PENDING[state], OAUTH_WAIT_S)
        except asyncio.TimeoutError:
            raise AuthError("The sign-in was not completed in time.") from None
        finally:
            _PENDING.pop(state, None)

    return OAuthClientProvider(url, metadata, storage, redirect_handler, callback_handler, timeout=OAUTH_WAIT_S)


def oauth_redirect_uri(origin: Optional[str], server_addr: Optional[tuple]) -> str:
    """Where the sign-in page sends the visitor back: this API's ``/oauth/callback``.

    ``GUARDIAN_PUBLIC_URL`` (the site's public address) wins. Locally the backend's own socket address is
    used, which stays correct behind the Vite dev proxy; on a public host the page's origin is the fallback."""
    import os

    configured = os.environ.get("GUARDIAN_PUBLIC_URL", "").strip().rstrip("/")
    if configured:
        return f"{configured}/oauth/callback"
    if not public_mode() and server_addr:
        host, port = server_addr[0], server_addr[1]
        host = "127.0.0.1" if host in ("0.0.0.0", "::", "::1", "testserver") else host
        return f"http://{host}:{port}/oauth/callback"
    return f"{(origin or '').rstrip('/')}/oauth/callback"
