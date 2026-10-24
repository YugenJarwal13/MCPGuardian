import { useState } from "react";
import { Alert, Arrow, Check, Info, Link, Play } from "../components/Icons.jsx";
import RunView from "../components/RunView.jsx";
import { usePipelineRun } from "../hooks/usePipelineRun.js";

const EXAMPLES = [
  ["DVMCP challenge 2", "http://127.0.0.1:9002/sse"],
  ["DVMCP challenge 6", "http://127.0.0.1:9006/sse"],
  ["DVMCP challenge 10", "http://127.0.0.1:9010/sse"],
];
const PUBLIC_EXAMPLES = [
  ["DeepWiki", "https://mcp.deepwiki.com/mcp"],
  ["Microsoft Learn", "https://learn.microsoft.com/api/mcp"],
  ["GitMCP (any repo)", "https://gitmcp.io/modelcontextprotocol/servers"],
];
const NOT_RUN_WHEN_INSPECTING = ["tool_call", "runtime_check", "behavioral_check", "a2a_hop", "enforcement"];
const clip = (s, n) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s || "");

function hostOf(url) {
  try {
    return new URL(url).host;
  } catch {
    return "MCP server";
  }
}

function Steps({ step }) {
  const items = [
    ["Connect and read every tool", "Guardian opens the connection itself and inspects each description. Nothing is executed."],
    ["Choose a tool to try", "Optional. Pick one tool and its arguments."],
    ["Run it through the pipeline", "The call is gated, the answer is scanned, behaviour is checked, a human can veto."],
  ];
  return (
    <div className="steps">
      {items.map(([t, p], i) => (
        <div key={t} className={`step${step === i + 1 ? " on" : ""}${step > i + 1 ? " done" : ""}`}>
          <span className="n">{step > i + 1 ? <Check width={14} height={14} /> : i + 1}</span>
          <span><b>{t}</b>{p}</span>
        </div>
      ))}
    </div>
  );
}

export default function TestLivePage({ health }) {
  const [url, setUrl] = useState("");
  const [useLlm, setUseLlm] = useState(true);
  const [mode, setMode] = useState("inspect");           // what the current / last run was
  const [pickedTool, setPickedTool] = useState(null);
  const [argsText, setArgsText] = useState("{}");
  const [formError, setFormError] = useState(null);
  const { events, running, error, start, approve, reset } = usePipelineRun();

  const done = [...events].reverse().find((e) => e.stage === "done");
  const inspected = [...events].reverse().find((e) => e.stage === "done" && e.detail?.inspect_only);
  const tools = inspected ? inspected.detail.tools : null;
  const badCount = tools ? tools.filter((t) => t.verdict !== "clean").length : 0;
  const step = mode === "call" && events.length ? 3 : tools ? 2 : events.length ? 1 : 1;

  const inspect = () => {
    const u = url.trim();
    if (!/^https?:\/\//i.test(u)) {
      setFormError("Enter an http:// or https:// MCP endpoint, for example https://example.com/sse");
      return;
    }
    setFormError(null);
    setMode("inspect");
    setPickedTool(null);
    start({ server_url: u, inspect_only: true, use_llm: useLlm });
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

  const clear = () => {
    reset();
    setPickedTool(null);
    setMode("inspect");
  };

  return (
    <main className="site">
      <section className="page-hero">
        <div className="wrap">
          <div className="eyebrow">Check any server</div>
          <h1>Connect to a live MCP server. Find out if it’s safe.</h1>
          <p className="lead">Paste the web address of an MCP server. Guardian connects, reads every tool it offers with the same AI inspectors, and tells you in plain words whether anything is hiding in there.</p>

          <div className="checker">
            <label className="urlbox">
              <Link width={20} height={20} />
              <span className="sr-only">MCP endpoint URL</span>
              <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://your-server.example.com/sse" spellCheck={false}
                disabled={running} onKeyDown={(e) => e.key === "Enter" && !running && url.trim() && inspect()} />
            </label>
            <button type="button" className="btn primary lg" onClick={inspect} disabled={running || !url.trim()}>
              {running && mode === "inspect" ? <><span className="spinner" /> Checking</> : <>Check if it’s safe <Arrow /></>}
            </button>
          </div>
          <div className="row" style={{ marginTop: 14, maxWidth: 980 }}>
            <span className="muted" style={{ fontSize: "var(--fs-sm)" }}>{health?.public_mode ? "Try a public MCP server:" : "Try a public server or a DVMCP one (start the lab first):"}</span>
            {[...PUBLIC_EXAMPLES, ...(health?.public_mode ? [] : EXAMPLES)].map(([l, u]) => (
              <button key={u} type="button" className="pick-chip" onClick={() => setUrl(u)} disabled={running}>{l}</button>
            ))}
            <label className="switch" style={{ marginLeft: "auto" }} title={health?.llm?.available ? "" : "No model configured: regex rules will be used"}>
              <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} disabled={running} />
              Use AI inspectors
            </label>
            {events.length > 0 && !running && <button type="button" className="btn quiet" onClick={clear}>Clear</button>}
          </div>
          {(formError || error) && <div className="notice error" style={{ marginTop: 14, maxWidth: 980 }}>{formError || error}</div>}
          <Steps step={step} />
        </div>
      </section>

      <div className="wrap" style={{ paddingBottom: 96 }}>
        <div className="stack-lg">
          {events.length === 0 && (
            <div className="help-grid" style={{ marginTop: 6 }}>
              {[
                ["What it checks", "Every tool’s name, description and parameters, for hidden orders aimed at the AI. If you then call a tool, also its reply and its behaviour over time."],
                ["What it doesn’t do", "It is not a full security audit. A clean scan means no hidden instructions were found in the text; it can’t see bugs inside the server’s own code."],
                ["Safe by default", health?.public_mode
                  ? "Only public http(s) addresses are accepted; local and internal ones are refused. Runs are rate-limited, and the AI-inspector budget is shared and resets daily. No tool is called unless you choose to."
                  : "Only http(s) addresses are accepted. Credentials in URLs and cloud-metadata addresses are refused. No tool is called unless you choose to."],
              ].map(([t, p]) => (
                <div key={t} className="fcard"><h3 style={{ fontSize: "1.1rem" }}>{t}</h3><p style={{ fontSize: "0.95rem" }}>{p}</p></div>
              ))}
            </div>
          )}

          {events.length > 0 && (
            <RunView events={events} running={running} onApprove={approve} serverName={hostOf(url)}
              notRun={mode === "inspect" ? NOT_RUN_WHEN_INSPECTING : []} showCompare={mode === "call"} />
          )}

          {tools && mode === "inspect" && (
            <>
              <div className={`final-verdict ${badCount ? "bad" : "ok"}`} role="status">
                <span className="vi">{badCount ? <Alert width={30} height={30} /> : <Check width={30} height={30} />}</span>
                <div>
                  <h2>{badCount ? `${badCount} of ${tools.length} tools carry hidden instructions` : `No hidden instructions found in ${tools.length === 1 ? "the tool" : `all ${tools.length} tools`}`}</h2>
                  <p>{badCount
                    ? "Don’t connect an unprotected AI agent to this server. Guardian would stop the flagged tools before the agent saw them."
                    : "A clean scan isn’t a guarantee: it covers what the tools say about themselves, not what the server does with your data."}</p>
                </div>
              </div>

              <div>
                <h3 style={{ fontSize: "1.4rem", marginBottom: 14 }}>Tool by tool</h3>
                <div className="tool-cards">
                  {tools.map((t) => (
                    <button key={t.name} type="button" className={`tcard${t.verdict !== "clean" ? " bad" : ""}`} aria-pressed={pickedTool === t.name} onClick={() => pick(t)}>
                      <div className="top">
                        <code style={{ fontSize: "0.9rem" }}>{t.name}</code>
                        <span><span className={`vpill ${t.verdict}`}>{t.verdict}</span> <span className="muted num">{Math.round(t.confidence * 100)}%</span></span>
                      </div>
                      <div className="why">{clip(t.reasoning, 230)}</div>
                      {t.flagged_phrases?.length > 0 && <div className="chips" style={{ marginTop: 8 }}>{t.flagged_phrases.slice(0, 3).map((p, i) => <code key={i} className="chip">{clip(p, 60)}</code>)}</div>}
                      <div className="go">{t.scope ? `Can reach: ${t.scope.replace("_", " ")} · ` : ""}{pickedTool === t.name ? "Selected" : "Select to run it through Guardian →"}</div>
                    </button>
                  ))}
                </div>
              </div>
            </>
          )}

          {tools && pickedTool && (
            <div className="panel">
              <div className="panel-title">Run <code>{pickedTool}</code> through the full pipeline</div>
              <label className="field">
                <span>Arguments (JSON)</span>
                <textarea className="textarea" value={argsText} onChange={(e) => setArgsText(e.target.value)} rows={4} spellCheck={false} disabled={running} />
              </label>
              <div className="row" style={{ marginTop: 12 }}>
                <button type="button" className="btn primary" onClick={call} disabled={running}>
                  {running && mode === "call" ? <><span className="spinner" /> Running</> : <><Play /> Call through Guardian</>}
                </button>
                <span className="muted" style={{ fontSize: "var(--fs-xs)" }}>The call reaches the server only if the policy allows it or you approve it.</span>
              </div>
            </div>
          )}

          <div className="unsupported">
            <strong><Info width={14} height={14} style={{ verticalAlign: -2 }} /> Not supported yet</strong>
            <ul>
              <li>stdio servers (the endpoint must be reachable over http/https: SSE <code>…/sse</code> or streamable HTTP)</li>
              <li>servers that need authentication headers or OAuth</li>
              <li>keeping a session open across several calls, and saving or sharing a report</li>
            </ul>
          </div>
        </div>
      </div>
    </main>
  );
}
