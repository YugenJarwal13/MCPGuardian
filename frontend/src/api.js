// Thin client for the FastAPI backend (src/api). In dev, Vite proxies these
// paths to :8000; set VITE_API_BASE to talk to another origin directly.
const BASE = import.meta.env.VITE_API_BASE || "";

async function getJSON(path) {
  const res = await fetch(`${BASE}${path}`);
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
  fetch(`${BASE}/servers/${serverId}/reset`, { method: "POST" });

function wsUrl(path) {
  if (BASE) return BASE.replace(/^http/, "ws") + path;
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}${path}`;
}

/**
 * Start a pipeline run. Calls onEvent(event) for every streamed stage event.
 * Returns { approve(bool), close() }.
 */
export function startRun(request, { onEvent, onClose, onError }) {
  const ws = new WebSocket(wsUrl("/ws/run"));
  ws.onopen = () => ws.send(JSON.stringify(request));
  ws.onmessage = (msg) => onEvent(JSON.parse(msg.data));
  ws.onerror = () => onError?.(new Error("WebSocket error — is the API running on :8000?"));
  ws.onclose = () => onClose?.();
  return {
    approve: (approved) => ws.send(JSON.stringify({ type: "approval", approved })),
    close: () => ws.close(),
  };
}
