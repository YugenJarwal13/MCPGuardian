import { useEffect, useMemo, useRef, useState } from "react";
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
  ["Cloudflare Docs", "https://docs.mcp.cloudflare.com/mcp"],
  ["Context7", "https://mcp.context7.com/mcp"],
  ["CoinGecko", "https://mcp.api.coingecko.com/mcp"],
  ["Hugging Face Hub", "https://huggingface.co/mcp"],
  ["GitMCP", "https://gitmcp.io/modelcontextprotocol/servers"],
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
  const [mode, setMode] = useState("inspect");           // what the current / last run was
  const [pickedTool, setPickedTool] = useState(null);
  const [argsText, setArgsText] = useState("{}");
  const [formError, setFormError] = useState(null);
  const [authType, setAuthType] = useState("none");
  const [token, setToken] = useState("");
  const [hName, setHName] = useState("");
  const [hValue, setHValue] = useState("");
  const [authOpen, setAuthOpen] = useState(false);
  const { events, running, error, authSession, start, approve, reset } = usePipelineRun();

  // credentials live only in this component's memory: never in storage, never in the address bar
  const authBlock = () => {
    if (authType === "bearer") return { type: "bearer", token };
    if (authType === "header") return { type: "header", name: hName, value: hValue };
    if (authType === "oauth") return { type: "oauth", session: authSession || undefined };
    return undefined;
  };
  const authReady = authType === "none" || authType === "oauth" || (authType === "bearer" && token.trim())
    || (authType === "header" && hName.trim() && hValue.trim());
  const authFailure = [...events].reverse().find((e) => e.stage === "connect" && e.status === "error" && e.detail?.auth_required);
  const signIn = useMemo(() => {
    const last = [...events].reverse().find((e) => e.detail?.oauth_url);
    const connected = events.some((e) => e.stage === "connect" && e.status === "passed");
    return last && !connected && running ? last.detail.oauth_url : null;
  }, [events, running]);
  const opened = useRef(null);
  useEffect(() => {
    if (signIn && opened.current !== signIn) {
      opened.current = signIn;
      window.open(signIn, "mcp-guardian-signin", "width=520,height=720");   // may be blocked: the banner has a link
    }
  }, [signIn]);
  useEffect(() => { if (authFailure) setAuthOpen(true); }, [authFailure]);

  const modelReady = !health || health.llm?.available;
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
    if (!authReady) {
      setAuthOpen(true);
      setFormError("Fill in the authentication details, or choose “No authentication”.");
      return;
    }
    setFormError(null);
    setMode("inspect");
    setPickedTool(null);
    start({ server_url: u, inspect_only: true, use_llm: true, auth: authBlock() });
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
    start({ server_url: url.trim(), tool_name: pickedTool, arguments: args, use_llm: true, auth: authBlock() });
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
          <p className="lead">Paste the web address of an MCP server. Guardian connects, has its AI inspectors read every tool it offers, and tells you in plain words whether anything is hiding in there.</p>

          <div className="checker">
            <label className="urlbox">
              <Link width={20} height={20} />
              <span className="sr-only">MCP endpoint URL</span>
              <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://your-server.example.com/sse" spellCheck={false}
                disabled={running} onKeyDown={(e) => e.key === "Enter" && !running && url.trim() && inspect()} />
            </label>
            <button type="button" className="btn primary lg" onClick={inspect} disabled={running || !url.trim() || !modelReady}>
              {running && mode === "inspect" ? <><span className="spinner" /> Checking</> : <>Check if it’s safe <Arrow /></>}
            </button>
          </div>
          <div className="row" style={{ marginTop: 14, maxWidth: 980 }}>
            <span className="muted" style={{ fontSize: "var(--fs-sm)" }}>{health?.public_mode ? "Try a public MCP server:" : "Try a public server, or a DVMCP one (start the lab first):"}</span>
            {[...PUBLIC_EXAMPLES, ...(health?.public_mode ? [] : EXAMPLES)].map(([l, u]) => (
              <button key={u} type="button" className="pick-chip" onClick={() => setUrl(u)} disabled={running}>{l}</button>
            ))}
            {events.length > 0 && !running && <button type="button" className="btn quiet" onClick={clear}>Clear</button>}
          </div>
          <div className="auth-box" style={{ marginTop: 10, maxWidth: 980 }}>
            <button type="button" className="btn quiet" aria-expanded={authOpen} onClick={() => setAuthOpen(!authOpen)}>
              Authentication: {{ none: "none", bearer: "bearer token", header: "custom header", oauth: "sign in (OAuth)" }[authType]} {authOpen ? "▴" : "▾"}
            </button>
            {authOpen && (
              <div className="panel" style={{ marginTop: 8 }}>
                <label className="field">
                  <span>How does this server want you to identify yourself?</span>
                  <select className="select" value={authType} onChange={(e) => setAuthType(e.target.value)} disabled={running}>
                    <option value="none">No authentication (public server)</option>
                    <option value="oauth">Sign in with the server (OAuth): a sign-in window opens</option>
                    <option value="bearer">Bearer token / personal access token</option>
                    <option value="header">API key in a custom header</option>
                  </select>
                </label>
                {authType === "bearer" && (
                  <label className="field"><span>Token (sent as “Authorization: Bearer …”)</span>
                    <input className="input" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} disabled={running} placeholder="paste the token" /></label>
                )}
                {authType === "header" && (
                  <div className="row" style={{ alignItems: "flex-end", gap: 12 }}>
                    <label className="field" style={{ flex: 1 }}><span>Header name</span>
                      <input className="input" value={hName} onChange={(e) => setHName(e.target.value)} disabled={running} placeholder="X-API-Key" spellCheck={false} /></label>
                    <label className="field" style={{ flex: 2 }}><span>Value</span>
                      <input className="input" type="password" autoComplete="off" value={hValue} onChange={(e) => setHValue(e.target.value)} disabled={running} placeholder="paste the key" /></label>
                  </div>
                )}
                {authType === "oauth" && <p className="muted" style={{ fontSize: "var(--fs-sm)", margin: "10px 0 0" }}>Guardian registers itself with the server, then asks you to approve access in the server’s own sign-in window. The tokens stay in memory on the Guardian server for about an hour and are never written to disk.</p>}
                <p className="muted" style={{ fontSize: "var(--fs-xs)", margin: "10px 0 0" }}>A key the server expects in the address (for example <code>?apikey=…</code>) can simply stay in the URL. Credentials are used for this check only and are hidden from the event log, the traces and the audit trail.</p>
              </div>
            )}
          </div>
          {authFailure && (
            <div className="notice warn" style={{ marginTop: 14, maxWidth: 980 }}>
              {authFailure.message}{authFailure.detail?.oauth_advertised && authType === "none" ? " This server offers OAuth sign-in: choose “Sign in with the server” under Authentication." : ""}
            </div>
          )}
          {signIn && (
            <div className="notice warn" style={{ marginTop: 14, maxWidth: 980 }} role="status">
              <b>Sign-in needed.</b> A window should have opened. If not,{" "}
              <a href={signIn} target="mcp-guardian-signin" rel="noreferrer">open the server’s sign-in page</a>, approve access, then come back: the check continues by itself.
            </div>
          )}
          {(formError || error) && <div className="notice error" style={{ marginTop: 14, maxWidth: 980 }}>{formError || error}</div>}
          {!modelReady && <div className="notice error" style={{ marginTop: 14, maxWidth: 980 }}>No language model is reachable, so servers cannot be checked. Check the backend's OpenRouter settings.</div>}
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
                  : "Only http(s) addresses are accepted. Passwords inside the address and cloud-metadata addresses are refused. No tool is called unless you choose to."],
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
                  <h2>{badCount ? `${badCount} of ${tools.length} tools contain instructions aimed at the AI` : `No hidden instructions found in ${tools.length === 1 ? "the tool" : `all ${tools.length} tools`}`}</h2>
                  <p>{badCount
                    ? "Read the quoted phrase on each flagged tool. Real attacks hide orders such as sending data elsewhere or ignoring the user; some servers add legitimate usage hints (for example “always read this guide first”). On real clean tools this detector raises a false alarm about 4% of the time."
                    : "A clean scan isn’t a guarantee: it covers what the tools say about themselves, not what the server does with your data."}</p>
                </div>
              </div>

              {inspected.detail.not_inspected?.length > 0 && (
                <div className="notice warn">
                  This server offers {tools.length + inspected.detail.not_inspected.length} tools. To keep runs affordable only {tools.length} were inspected.
                  Not inspected: {inspected.detail.not_inspected.slice(0, 8).join(", ")}{inspected.detail.not_inspected.length > 8 ? ` and ${inspected.detail.not_inspected.length - 8} more` : ""}.
                </div>
              )}

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
              <li>servers with a custom sign-in flow (anything other than a token, an API-key header, a key in the address, or OAuth)</li>
              <li>servers’ resources and prompts: only their tools are inspected</li>
              <li>keeping a session open across several calls, and saving or sharing a report</li>
            </ul>
          </div>
        </div>
      </div>
    </main>
  );
}
