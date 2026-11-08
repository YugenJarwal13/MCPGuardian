// Thin client for the FastAPI backend (src/api). In dev, Vite proxies these
// paths to :8000; set VITE_API_BASE to talk to another origin directly.
const BASE = import.meta.env.VITE_API_BASE || "";

// Optional access key (the server may require one). Kept for this browser tab only.
export function getAccessKey() {
  try {
    return sessionStorage.getItem("guardian-access-key") || "";
  } catch {
    return "";
  }
}
export function setAccessKey(key) {
  try {
    sessionStorage.setItem("guardian-access-key", key);
  } catch {
    /* storage unavailable: the key then lasts until reload */
  }
}
const authHeaders = () => (getAccessKey() ? { "X-Access-Key": getAccessKey() } : {});

async function getJSON(path) {
  const res = await fetch(`${BASE}${path}`, { headers: authHeaders() });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.json();
}

export const fetchHealth = () => getJSON("/health");
export const fetchServers = () => getJSON("/servers");
export const fetchTools = (serverId) => getJSON(`/servers/${serverId}/tools`);
export const resetServer = (serverId) =>
  fetch(`${BASE}/servers/${serverId}/reset`, { method: "POST", headers: authHeaders() });

/** Ask an MCP endpoint what it speaks and whether it wants credentials, before any run starts. */
export async function probeServer(url) {
  const res = await fetch(`${BASE}/probe`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ url }),
  });
  let body = {};
  try {
    body = await res.json();
  } catch {
    /* not JSON */
  }
  if (!res.ok) throw new Error(body.detail || res.statusText || "The check could not be started.");
  return body;
}

function wsUrl(path) {
  if (BASE) return BASE.replace(/^http/, "ws") + path;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}

/**
 * Start a pipeline run. Calls onEvent(event) for every streamed stage event.
 * Returns { approve(bool), close() }.
 */
export function startRun(request, { onEvent, onClose, onError, onSession }) {
  const ws = new WebSocket(wsUrl("/ws/run"));
  ws.onopen = () => ws.send(JSON.stringify({ ...request, ...(getAccessKey() ? { access_key: getAccessKey() } : {}) }));
  ws.onmessage = (msg) => {
    const data = JSON.parse(msg.data);
    if (data.type === "auth_session") onSession?.(data.session);   // handle to this visitor's in-memory sign-in
    else {
      if (data.detail?.guard === "auth") {          // the key was refused: forget it so the page asks again
        setAccessKey("");
        window.dispatchEvent(new Event("guardian-key-rejected"));
      }
      onEvent(data);
    }
  };
  ws.onerror = () => onError?.(new Error("WebSocket error: is the API running on port 8000?"));
  ws.onclose = () => onClose?.();
  return {
    approve: (approved) => ws.send(JSON.stringify({ type: "approval", approved })),
    close: () => ws.close(),
  };
}
