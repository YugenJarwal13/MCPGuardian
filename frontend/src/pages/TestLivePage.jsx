import { useState } from "react";
import PipelineView from "../components/PipelineView.jsx";
import VerdictBanner from "../components/VerdictBanner.jsx";
import { Play } from "../components/Icons.jsx";
import { usePipelineRun } from "../hooks/usePipelineRun.js";

const EXAMPLES = [
  ["DVMCP Challenge 2", "http://127.0.0.1:9002/sse"],
  ["DVMCP Challenge 6", "http://127.0.0.1:9006/sse"],
  ["DVMCP Challenge 10", "http://127.0.0.1:9010/sse"],
];

const NOT_RUN_WHEN_INSPECTING = ["tool_call", "runtime_check", "behavioral_check", "a2a_hop", "enforcement"];

/**
 * Basic version of "Test a MCP server LIVE". Step 1 connects to the URL you give and
 * statically inspects every tool it offers (no tool is called). Step 2 lets you pick
 * one tool and run the full pipeline on it. Same PipelineView as the demo page.
 */
export default function TestLivePage({ health }) {
  const [url, setUrl] = useState("");
  const [useLlm, setUseLlm] = useState(true);
  const [mode, setMode] = useState("inspect");           // what the current/last run was
  const [pickedTool, setPickedTool] = useState(null);
  const [argsText, setArgsText] = useState("{}");
  const [formError, setFormError] = useState(null);
  const { events, running, error, start, approve, reset } = usePipelineRun();

  const done = [...events].reverse().find((e) => e.stage === "done");
  const tools = done?.detail?.inspect_only ? done.detail.tools : null;

  const inspect = () => {
    if (!/^https?:\/\//i.test(url.trim())) {
      setFormError("Enter an http:// or https:// MCP endpoint, for example http://127.0.0.1:9002/sse");
      return;
    }
    setFormError(null);
    setMode("inspect");
    setPickedTool(null);
    start({ server_url: url.trim(), inspect_only: true, use_llm: useLlm });
  };

  const pick = (t) => {
    setPickedTool(t.name);
    setArgsText(JSON.stringify(t.default_args || {}, null, 2));
  };

  const call = () => {
    let args;
    try {
      args = JSON.parse(argsText || "{}");
    } catch {
      setFormError("Arguments must be valid JSON.");
      return;
    }
    setFormError(null);
    setMode("call");
    start({ server_url: url.trim(), tool_name: pickedTool, arguments: args, use_llm: useLlm });
  };

  return (
    <main className="page">
      <div className="page-head">
        <h1>Test a MCP server live</h1>
        <p>Point the Guardian at an MCP server of your choice. It connects, inspects every tool it offers, and — only if you ask — runs one call through the full pipeline.</p>
      </div>
      <div className="stack">
        <div className="panel">
          <div className="panel-title">1 · Server to inspect</div>
          <label className="field">
            <span>MCP endpoint URL</span>
            <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="http://127.0.0.1:9002/sse"
              spellCheck={false} disabled={running} onKeyDown={(e) => e.key === "Enter" && !running && inspect()} />
          </label>
          <div className="row" style={{ marginTop: 10 }}>
            <span className="muted" style={{ fontSize: "var(--fs-xs)" }}>Try:</span>
            {EXAMPLES.map(([label, u]) => (
              <button key={u} type="button" className="chip neutral" style={{ cursor: "pointer" }} onClick={() => setUrl(u)} disabled={running}>{label}</button>
            ))}
          </div>
          <div className="row" style={{ marginTop: 16 }}>
            <button type="button" className="btn primary" onClick={inspect} disabled={running || !url.trim()}>
              {running && mode === "inspect" ? <><span className="spinner" /> Inspecting</> : <><Play /> Run Guardian</>}
            </button>
            <label className="switch" title={health?.llm?.available ? "" : "No model configured: heuristic detectors will be used"}>
              <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} disabled={running} />
              Use LLM agents
            </label>
            {events.length > 0 && !running && <button type="button" className="btn quiet" onClick={reset}>Clear</button>}
          </div>
          {(formError || error) && <div className="notice error" style={{ marginTop: 12 }}>{formError || error}</div>}
        </div>

        {events.length > 0 && (
          <section aria-label="Pipeline" className="stack">
            <VerdictBanner done={done} />
            <PipelineView events={events} onApprove={approve} notRun={mode === "inspect" ? NOT_RUN_WHEN_INSPECTING : []} />
          </section>
        )}

        {tools && (
          <div className="panel">
            <div className="panel-title">2 · Call one tool through the Guardian</div>
            <table className="tool-table">
              <thead><tr><th>Tool</th><th>Static verdict</th><th>Scope</th><th>Engine</th></tr></thead>
              <tbody>
                {tools.map((t) => (
                  <tr key={t.name} className="pick" aria-selected={pickedTool === t.name} onClick={() => pick(t)}
                    tabIndex={0} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && pick(t)}>
                    <td><code>{t.name}</code></td>
                    <td><span className={`vpill ${t.verdict}`}>{t.verdict}</span> <span className="muted num">{Math.round(t.confidence * 100)}%</span></td>
                    <td>{t.scope ? t.scope.replace("_", " ") : <span className="muted">—</span>}</td>
                    <td className="muted">{t.engine}{t.model ? ` · ${t.model.split("/").pop().replace(/:free$/, "")}` : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {pickedTool && (
              <div style={{ marginTop: 16 }}>
                <label className="field">
                  <span>Arguments for <code>{pickedTool}</code> (JSON)</span>
                  <textarea className="textarea" value={argsText} onChange={(e) => setArgsText(e.target.value)} rows={4} spellCheck={false} disabled={running} />
                </label>
                <div className="row" style={{ marginTop: 12 }}>
                  <button type="button" className="btn primary" onClick={call} disabled={running}>
                    {running && mode === "call" ? <><span className="spinner" /> Running</> : "Call through Guardian"}
                  </button>
                  <span className="muted" style={{ fontSize: "var(--fs-xs)" }}>The call is made on that server only if the policy allows it, or you approve it.</span>
                </div>
              </div>
            )}
          </div>
        )}

        <div className="unsupported">
          <strong>Not yet supported on this page</strong>
          <ul>
            <li>stdio servers (the endpoint must be reachable over http/https: SSE <code>…/sse</code> or streamable HTTP)</li>
            <li>servers that need authentication headers or OAuth</li>
            <li>keeping a session open across several calls, and saving or sharing a report</li>
          </ul>
        </div>
      </div>
    </main>
  );
}
