import { useEffect, useRef, useState } from "react";
import { fetchHealth, fetchServers, fetchTools, resetServer, startRun } from "./api.js";
import PipelineView from "./components/PipelineView.jsx";
import ServerPicker from "./components/ServerPicker.jsx";
import VerdictBanner from "./components/VerdictBanner.jsx";

export default function App() {
  const [health, setHealth] = useState(null);
  const [servers, setServers] = useState(null);
  const [server, setServer] = useState(null);
  const [tools, setTools] = useState([]);
  const [toolsError, setToolsError] = useState(null);
  const [toolName, setToolName] = useState("");
  const [argsText, setArgsText] = useState("{}");
  const [useLlm, setUseLlm] = useState(true);
  const [events, setEvents] = useState([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const runRef = useRef(null);

  const refreshServers = () =>
    fetchServers().then(setServers).catch((e) => setError(`Cannot reach the API: ${e.message}`));

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => {});
    refreshServers();
  }, []);

  const selectServer = (s) => {
    setServer(s);
    setEvents([]);
    setTools([]);
    setToolsError(null);
    setToolName(s.default_tool || "");
    setArgsText(JSON.stringify(s.default_args || {}, null, 2));
    if (s.port && !s.live) {
      setToolsError(`Not running on port ${s.port}. Start it: python scripts/run_dvmcp_native.py`);
      return;
    }
    fetchTools(s.id)
      .then((list) => {
        setTools(list);
        const chosen = list.find((t) => t.name === s.default_tool) || list[0];
        if (chosen) {
          setToolName(chosen.name);
          setArgsText(JSON.stringify(chosen.default_args || {}, null, 2));
        }
      })
      .catch((e) => setToolsError(e.message));
  };

  const selectTool = (name) => {
    setToolName(name);
    const t = tools.find((x) => x.name === name);
    if (t) setArgsText(JSON.stringify(t.default_args || {}, null, 2));
  };

  const run = () => {
    let args;
    try {
      args = JSON.parse(argsText || "{}");
    } catch {
      setError("Arguments must be valid JSON.");
      return;
    }
    setError(null);
    setEvents([]);
    setRunning(true);
    runRef.current = startRun(
      { server_id: server.id, tool_name: toolName || null, arguments: args, use_llm: useLlm },
      {
        onEvent: (ev) => setEvents((prev) => [...prev, ev]),
        onClose: () => setRunning(false),
        onError: (e) => {
          setError(e.message);
          setRunning(false);
        },
      }
    );
  };

  const done = [...events].reverse().find((e) => e.stage === "done");
  const llmReady = health?.llm_available;

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>MCP Guardian</h1>
          <p className="muted">Pick an MCP server, run one tool call, and watch every defence layer decide.</p>
        </div>
        <div className="status-pills">
          <span className={`pill ${llmReady ? "ok" : "warn"}`}>
            {health == null ? "API …" : llmReady ? "LLM configured" : "No LLM key — heuristic mode"}
          </span>
          {health?.a2a_url && <span className="pill ok">A2A {health.a2a_url.replace("http://", "")}</span>}
        </div>
      </header>

      {error && <div className="banner error">{error}</div>}

      <ServerPicker servers={servers} selectedId={server?.id} onSelect={selectServer} disabled={running} />

      {server && (
        <section className="run-panel">
          <div className="run-controls">
            <label>
              Tool
              {tools.length ? (
                <select value={toolName} onChange={(e) => selectTool(e.target.value)} disabled={running}>
                  {tools.map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.name}
                    </option>
                  ))}
                </select>
              ) : (
                <input value={toolName} readOnly />
              )}
            </label>
            <label className="args">
              Arguments (JSON)
              <textarea
                value={argsText}
                onChange={(e) => setArgsText(e.target.value)}
                rows={Math.min(8, argsText.split("\n").length + 1)}
                spellCheck={false}
                disabled={running}
              />
            </label>
            <div className="run-actions">
              <label className="toggle" title={llmReady ? "" : "No provider configured: the API will fall back to heuristics"}>
                <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} disabled={running} />
                Use LLM agents
              </label>
              <button type="button" className="run" onClick={run} disabled={running || !!toolsError}>
                {running ? "Running…" : "Run pipeline"}
              </button>
              <button
                type="button"
                className="ghost"
                disabled={running}
                onClick={() => resetServer(server.id).then(() => setEvents([]))}
                title="Forget this server's behavioural history"
              >
                Reset history
              </button>
            </div>
            {toolsError && <p className="banner warn">{toolsError}</p>}
          </div>

          <VerdictBanner done={done} />
          <PipelineView events={events} onApprove={(ok) => runRef.current?.approve(ok)} />
        </section>
      )}
    </div>
  );
}
