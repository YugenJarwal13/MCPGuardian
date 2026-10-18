import { useEffect, useState } from "react";
import { fetchServers, fetchTools, resetServer } from "../api.js";
import PipelineView from "../components/PipelineView.jsx";
import ServerPicker from "../components/ServerPicker.jsx";
import VerdictBanner from "../components/VerdictBanner.jsx";
import { Play } from "../components/Icons.jsx";
import { usePipelineRun } from "../hooks/usePipelineRun.js";

export default function DemoPage({ health }) {
  const [servers, setServers] = useState(null);
  const [server, setServer] = useState(null);
  const [tools, setTools] = useState([]);
  const [toolsError, setToolsError] = useState(null);
  const [toolName, setToolName] = useState("");
  const [argsText, setArgsText] = useState("{}");
  const [useLlm, setUseLlm] = useState(true);
  const [formError, setFormError] = useState(null);
  const { events, running, error, start, approve, reset } = usePipelineRun();

  useEffect(() => {
    fetchServers().then(setServers).catch((e) => setFormError(`Cannot reach the API: ${e.message}`));
  }, []);

  const selectServer = (s) => {
    reset();
    setServer(s);
    setTools([]);
    setToolsError(null);
    setFormError(null);
    setToolName(s.default_tool || "");
    setArgsText(JSON.stringify(s.default_args || {}, null, 2));
    if (s.port && !s.live) {
      setToolsError(`Not running on port ${s.port}. Start it with: python scripts/run_dvmcp_native.py`);
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
      setFormError("Arguments must be valid JSON.");
      return;
    }
    setFormError(null);
    start({ server_id: server.id, tool_name: toolName || null, arguments: args, use_llm: useLlm });
  };

  const done = [...events].reverse().find((e) => e.stage === "done");
  const llmReady = health?.llm?.available;

  return (
    <main className="page">
      <div className="page-head">
        <h1>Watch a tool call get screened</h1>
        <p>Pick an MCP server, run one tool call, and see every defence layer decide — live, stage by stage.</p>
      </div>
      <div className="workspace">
        <aside className="sidebar">
          <div className="panel">
            <div className="panel-title">1 · Choose a server</div>
            <ServerPicker servers={servers} selectedId={server?.id} onSelect={selectServer} disabled={running} />
          </div>
          {server && (
            <div className="panel">
              <div className="panel-title">2 · Run it</div>
              <label className="field">
                <span>Tool</span>
                {tools.length ? (
                  <select className="select" value={toolName} onChange={(e) => selectTool(e.target.value)} disabled={running}>
                    {tools.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
                  </select>
                ) : (
                  <input className="input" value={toolName} readOnly />
                )}
              </label>
              <label className="field">
                <span>Arguments (JSON)</span>
                <textarea className="textarea" value={argsText} onChange={(e) => setArgsText(e.target.value)}
                  rows={Math.min(8, argsText.split("\n").length + 1)} spellCheck={false} disabled={running} />
              </label>
              <div className="row" style={{ marginTop: 14 }}>
                <label className="switch" title={llmReady ? "" : "No model is configured: the API falls back to the heuristic detectors"}>
                  <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} disabled={running} />
                  Use LLM agents
                </label>
              </div>
              <div className="row" style={{ marginTop: 14 }}>
                <button type="button" className="btn primary" onClick={run} disabled={running || !!toolsError}>
                  {running ? <><span className="spinner" /> Running</> : <><Play /> Run pipeline</>}
                </button>
                <button type="button" className="btn quiet" disabled={running} title="Forget this server's behavioural history"
                  onClick={() => resetServer(server.id).then(reset)}>Reset history</button>
              </div>
              {(formError || error) && <div className="notice error" style={{ marginTop: 12 }}>{formError || error}</div>}
              {toolsError && <div className="notice warn" style={{ marginTop: 12 }}>{toolsError}</div>}
            </div>
          )}
        </aside>
        <section aria-label="Pipeline">
          {!server && <div className="notice">Select a server on the left to begin. Clean servers should sail through; poisoned ones should be stopped at a specific stage.</div>}
          {server && <VerdictBanner done={done} />}
          {server && <PipelineView events={events} onApprove={approve} />}
        </section>
      </div>
    </main>
  );
}
