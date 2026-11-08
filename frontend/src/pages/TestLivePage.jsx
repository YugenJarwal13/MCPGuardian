import { useEffect, useMemo, useRef, useState } from "react";
import { probeServer } from "../api.js";
import AutoFollowToggle from "../components/AutoFollowToggle.jsx";
import FlowStepper from "../components/FlowStepper.jsx";
import { Alert, Arrow, Check, Info, Link, Play } from "../components/Icons.jsx";
import { prettyModel } from "../components/LlmStatus.jsx";
import Modal from "../components/Modal.jsx";
import RunView from "../components/RunView.jsx";
import { useAutoFollow } from "../hooks/useAutoFollow.js";
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
const STEPS = ["Enter URL", "Authenticate", "Inspect tools", "Review", "Tool and model", "Run pipeline", "Results"];
const clip = (s, n) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s || "");

function hostOf(url) {
  try {
    return new URL(url).host;
  } catch {
    return "MCP server";
  }
}

const AUTH_METHODS = [
  ["oauth", "Sign in with the server", "A sign-in window opens on the server's own page. Tokens stay in memory for about an hour."],
  ["bearer", "Bearer token", "A personal access token, sent as Authorization: Bearer …"],
  ["header", "API key in a header", "A key the server expects in a custom header, such as X-API-Key."],
];

export default function TestLivePage({ health }) {
  const [url, setUrl] = useState("");
  const [formError, setFormError] = useState(null);
  const [probing, setProbing] = useState(false);
  const [probeInfo, setProbeInfo] = useState(null);
  const [modal, setModal] = useState(null);                    // null | "auth" | "inspected" | "configure"
  const [mode, setMode] = useState("inspect");                 // what the current / last run was
  const [authType, setAuthType] = useState("none");
  const [token, setToken] = useState("");
  const [hName, setHName] = useState("");
  const [hValue, setHValue] = useState("");
  const [authError, setAuthError] = useState(null);
  const [snapshot, setSnapshot] = useState(null);              // the finished inspection: survives later call runs
  const [pickedTool, setPickedTool] = useState(null);
  const [argsText, setArgsText] = useState("{}");
  const [argsError, setArgsError] = useState(null);
  const [model, setModel] = useState("");
  const { events, running, error, authSession, start, approve, reset } = usePipelineRun();
  const { enabled: follow, setEnabled: setFollow, follow: goTo } = useAutoFollow();

  const runRef = useRef(null);
  const resultsRef = useRef(null);
  const seenInspection = useRef(null);
  const seenAuthFailure = useRef(null);
  const followRun = useRef(false);        // scroll to the run once its first event has rendered the section

  const modelReady = !health || health.llm?.available;
  const chain = (health?.llm?.chain || []).filter((c) => c.usable);
  const tools = snapshot?.tools || null;
  const done = [...events].reverse().find((e) => e.stage === "done");
  const inspectedEvent = mode === "inspect" ? [...events].reverse().find((e) => e.stage === "done" && e.detail?.inspect_only) : null;
  const authFailure = [...events].reverse().find((e) => e.stage === "connect" && e.status === "error" && e.detail?.auth_required);
  const signIn = useMemo(() => {
    const last = [...events].reverse().find((e) => e.detail?.oauth_url);
    const connected = events.some((e) => e.stage === "connect" && e.status === "passed");
    return last && !connected && running ? last.detail.oauth_url : null;
  }, [events, running]);
  const badCount = tools ? tools.filter((t) => t.verdict !== "clean").length : 0;

  // where the visitor is in the flow, for the stepper
  const current = probing ? 0
    : modal === "auth" || signIn ? 1
    : running && mode === "inspect" ? 2
    : modal === "configure" ? 4
    : running && mode === "call" ? 5
    : mode === "call" && done ? 6
    : snapshot ? 3
    : 0;
  const skipped = probeInfo && !probeInfo.auth_required ? [1] : [];

  const authBlock = (type = authType) => {
    if (type === "bearer") return { type: "bearer", token };
    if (type === "header") return { type: "header", name: hName, value: hValue };
    if (type === "oauth") return { type: "oauth", session: authSession || undefined };
    return undefined;
  };
  const authReady = (type) => type === "none" || type === "oauth" || (type === "bearer" && token.trim())
    || (type === "header" && hName.trim() && hValue.trim());

  // ---- 1. enter the URL, find out what the server needs ---------------------------------------------------------
  const check = () => {
    const u = url.trim();
    if (!/^https?:\/\//i.test(u)) {
      setFormError("Enter an http:// or https:// MCP endpoint, for example https://example.com/mcp");
      return;
    }
    reset();
    setFormError(null);
    setSnapshot(null);
    setProbeInfo(null);
    setProbing(true);
    probeServer(u)
      .then((info) => {
        setProbing(false);
        if (!info.ok) {
          setFormError(info.error);
          return;
        }
        setProbeInfo(info);
        if (info.auth_required) {
          setAuthType(info.oauth_advertised ? "oauth" : "bearer");
          setAuthError(null);
          setModal("auth");
        } else {
          setAuthType("none");
          begin("none");
        }
      })
      .catch((e) => {
        setProbing(false);
        setFormError(e.message);
      });
  };

  // ---- 3. connect and inspect ----------------------------------------------------------------------------------
  const begin = (type) => {
    setMode("inspect");
    setPickedTool(null);
    followRun.current = true;
    start({ server_url: url.trim(), inspect_only: true, use_llm: true, auth: authBlock(type) });
  };

  const continueAuth = () => {
    if (!authReady(authType)) {
      setAuthError(authType === "header" ? "Enter both the header name and its value." : "Enter the token first.");
      return;
    }
    setAuthError(null);
    setModal(null);
    begin(authType);
  };

  // the run reported that the server wants credentials (wrong or missing): ask again, with the reason
  useEffect(() => {
    if (authFailure && seenAuthFailure.current !== authFailure.run_id) {
      seenAuthFailure.current = authFailure.run_id;
      setAuthError(authFailure.message);
      setModal("auth");
    }
  }, [authFailure]);

  // OAuth: open the server's sign-in window by itself (the dialog below has the link if a blocker stops it)
  const opened = useRef(null);
  useEffect(() => {
    if (signIn && opened.current !== signIn) {
      opened.current = signIn;
      window.open(signIn, "mcp-guardian-signin", "width=520,height=720");
    }
  }, [signIn]);

  // ---- 4. the inspection finished ------------------------------------------------------------------------------
  useEffect(() => {
    if (!inspectedEvent || running || seenInspection.current === inspectedEvent.run_id) return;
    seenInspection.current = inspectedEvent.run_id;
    setSnapshot({ tools: inspectedEvent.detail.tools || [], notInspected: inspectedEvent.detail.not_inspected || [] });
    setModal("inspected");
    setTimeout(() => goTo(resultsRef.current), 60);
  }, [inspectedEvent, running, goTo]);

  useEffect(() => {
    if (followRun.current && events.length > 0) {
      followRun.current = false;
      setTimeout(() => goTo(runRef.current), 60);
    }
  }, [events.length, goTo]);

  // a finished call: bring the verdict into view
  useEffect(() => {
    if (mode === "call" && done && !running) setTimeout(() => goTo(runRef.current), 60);
  }, [mode, done, running, goTo]);

  // ---- 5. tool and model ----------------------------------------------------------------------------------------
  const suggested = tools ? (tools.find((t) => t.safe_to_try) || tools.find((t) => t.looks_read_only) || tools[0]) : null;
  const pick = (t) => {
    setPickedTool(t.name);
    setArgsText(JSON.stringify(t.default_args || {}, null, 2));
    setArgsError(null);
  };
  const openConfigure = (toolName) => {
    const t = tools?.find((x) => x.name === toolName) || suggested;
    if (!t) return;
    pick(t);
    setModal("configure");
  };

  // ---- 6. run the full pipeline ---------------------------------------------------------------------------------
  const runPipeline = () => {
    let args;
    try {
      args = JSON.parse(argsText || "{}");
    } catch {
      setArgsError("The arguments must be valid JSON.");
      return;
    }
    if (args === null || typeof args !== "object" || Array.isArray(args)) {
      setArgsError("The arguments must be a JSON object, for example {\"query\": \"...\"}.");
      return;
    }
    setModal(null);
    setMode("call");
    followRun.current = true;
    start({ server_url: url.trim(), tool_name: pickedTool, arguments: args, use_llm: true, auth: authBlock(),
      ...(model ? { model } : {}) });
  };

  const clear = () => {
    reset();
    setSnapshot(null);
    setProbeInfo(null);
    setPickedTool(null);
    setModal(null);
    setMode("inspect");
    setFormError(null);
  };

  const picked = tools?.find((t) => t.name === pickedTool);
  const flagged = tools ? tools.filter((t) => t.verdict !== "clean" || t.definition_changed) : [];

  return (
    <main className="site">
      <section className="page-hero">
        <div className="wrap">
          <div className="eyebrow">Check any server</div>
          <h1>Connect to a live MCP server. Find out if it’s safe.</h1>
          <p className="lead">Paste the web address of an MCP server. Guardian finds out what it needs, has its AI inspectors read every tool it offers, and tells you in plain words whether anything is hiding in there.</p>

          <div className="checker">
            <label className="urlbox">
              <Link width={20} height={20} />
              <span className="sr-only">MCP endpoint URL</span>
              <input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://your-server.example.com/mcp" spellCheck={false}
                disabled={running || probing} onKeyDown={(e) => e.key === "Enter" && !running && !probing && url.trim() && check()} />
            </label>
            <button type="button" className="btn primary lg" onClick={check} disabled={running || probing || !url.trim() || !modelReady}>
              {probing ? <><span className="spinner" /> Contacting server</> : running && mode === "inspect" ? <><span className="spinner" /> Checking</> : <>Check if it’s safe <Arrow /></>}
            </button>
          </div>
          <div className="row" style={{ marginTop: 14, maxWidth: 980 }}>
            <span className="muted" style={{ fontSize: "var(--fs-sm)" }}>{health?.public_mode ? "Try a public MCP server:" : "Try a public server, or a DVMCP one (start the lab first):"}</span>
            {[...PUBLIC_EXAMPLES, ...(health?.public_mode ? [] : EXAMPLES)].map(([l, u]) => (
              <button key={u} type="button" className="pick-chip" onClick={() => setUrl(u)} disabled={running || probing}>{l}</button>
            ))}
          </div>
          <div className="toolbar">
            <AutoFollowToggle enabled={follow} onChange={setFollow} />
            {running && <button type="button" className="btn quiet" onClick={clear}>Cancel</button>}
            {!running && (events.length > 0 || snapshot) && <button type="button" className="btn quiet" onClick={clear}>Start over</button>}
          </div>
          {(formError || error) && <div className="notice error" role="alert" style={{ marginTop: 14, maxWidth: 980 }}>{formError || error}</div>}
          {!modelReady && <div className="notice error" style={{ marginTop: 14, maxWidth: 980 }}>No language model is reachable, so servers cannot be checked. Check the backend’s OpenRouter settings.</div>}
          <FlowStepper steps={STEPS} current={current} skipped={skipped} label="Check a server: progress" />
        </div>
      </section>

      <div className="wrap" style={{ paddingBottom: 96 }}>
        <div className="stack-lg">
          {events.length === 0 && !snapshot && (
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
            <section ref={runRef} className="flow-section" aria-label="Pipeline run">
              <div className="section-head">
                <span className="num">{mode === "call" ? "RUN" : "INSPECT"}</span>
                <h2>{mode === "call" ? "Full security pipeline" : "Connecting and reading every tool"}</h2>
              </div>
              <RunView events={events} running={running} onApprove={approve} serverName={hostOf(url)}
                notRun={mode === "inspect" ? NOT_RUN_WHEN_INSPECTING : []} showCompare={mode === "call"} />
              {mode === "call" && done && !running && tools && (
                <div className="row" style={{ marginTop: 16 }}>
                  <button type="button" className="btn" onClick={() => openConfigure(pickedTool)}>Run another tool</button>
                </div>
              )}
            </section>
          )}

          {tools && (
            <section ref={resultsRef} className="flow-section" aria-label="Inspection results">
              <div className="section-head">
                <span className="num">RESULTS</span>
                <h2>Inspection of {hostOf(url)}</h2>
              </div>
              <div className={`final-verdict ${badCount ? "bad" : "ok"}`} role="status">
                <span className="vi">{badCount ? <Alert width={30} height={30} /> : <Check width={30} height={30} />}</span>
                <div>
                  <h2>{badCount ? `${badCount} of ${tools.length} tools contain instructions aimed at the AI` : `No hidden instructions found in ${tools.length === 1 ? "the tool" : `all ${tools.length} tools`}`}</h2>
                  <p>{badCount
                    ? "Read the quoted phrase on each flagged tool. Real attacks hide orders such as sending data elsewhere or ignoring the user; some servers add legitimate usage hints (for example “always read this guide first”). On real clean tools this detector raises a false alarm on roughly one tool in twenty-five."
                    : "A clean scan isn’t a guarantee: it covers what the tools say about themselves, not what the server does with your data."}</p>
                </div>
              </div>

              <h3 style={{ fontSize: "1.3rem", margin: "26px 0 14px" }}>Tool by tool</h3>
              <div className="tool-cards">
                {tools.map((t) => (
                  <button key={t.name} type="button" className={`tcard${t.verdict !== "clean" ? " bad" : ""}`} onClick={() => openConfigure(t.name)}>
                    <div className="top">
                      <code style={{ fontSize: "0.9rem" }}>{t.name}</code>
                      <span><span className={`vpill ${t.verdict}`}>{t.verdict}</span></span>
                    </div>
                    <div className="why">{clip(t.reasoning, 230)}</div>
                    {t.flagged_phrases?.length > 0 && <div className="chips" style={{ marginTop: 8 }}>{t.flagged_phrases.slice(0, 3).map((p, i) => <code key={i} className="chip">{clip(p, 60)}</code>)}</div>}
                    <div className="go">{t.scope ? `Can reach: ${t.scope.replace("_", " ")} · ` : ""}Run it through the full pipeline →</div>
                  </button>
                ))}
              </div>
              {snapshot.notInspected.length > 0 && (
                <div className="notice warn" style={{ marginTop: 14 }}>
                  This server offers {tools.length + snapshot.notInspected.length} tools. To keep runs affordable only {tools.length} were inspected.
                  Not inspected: {snapshot.notInspected.slice(0, 8).join(", ")}{snapshot.notInspected.length > 8 ? ` and ${snapshot.notInspected.length - 8} more` : ""}.
                </div>
              )}
            </section>
          )}

          <details className="limits unsupported">
            <summary><Info width={14} height={14} style={{ verticalAlign: -2 }} /> What is not supported yet</summary>
            <ul>
              <li>stdio servers (the endpoint must be reachable over http/https: SSE or streamable HTTP)</li>
              <li>servers with a custom sign-in flow (anything other than a token, an API-key header, a key in the address, or OAuth)</li>
              <li>servers’ resources and prompts: only their tools are inspected</li>
              <li>keeping a session open across several calls, and saving or sharing a report</li>
            </ul>
          </details>
        </div>
      </div>

      {/* 2. authentication: only asked once the server has said it needs it */}
      <Modal open={modal === "auth" && !signIn} eyebrow="Step 2 of 7 · Authenticate" title="This server needs you to sign in"
        onClose={clear}
        footer={<>
          <button type="button" className="btn" onClick={clear}>Cancel</button>
          <button type="button" className="btn primary" onClick={continueAuth} data-autofocus>Continue <Arrow /></button>
        </>}>
        <p>{probeInfo?.host || hostOf(url)} answered that it requires authentication{probeInfo?.oauth_advertised ? " and offers OAuth sign-in" : ""}. Choose how Guardian should identify itself. Credentials are used for this check only and are hidden from logs and traces.</p>
        {authError && <div className="notice error modal-error" role="alert">{authError}</div>}
        <div className="choice-list" role="radiogroup" aria-label="Authentication method">
          {AUTH_METHODS.map(([id, label, help]) => (
            <label key={id} className={`choice${authType === id ? " on" : ""}`}>
              <input type="radio" name="auth" checked={authType === id} onChange={() => { setAuthType(id); setAuthError(null); }} />
              <span><b>{label}{id === "oauth" && probeInfo?.oauth_advertised && <span className="tag">Offered</span>}</b><small>{help}</small></span>
            </label>
          ))}
        </div>
        {authType === "bearer" && (
          <label className="field"><span>Token</span>
            <input className="input" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} placeholder="paste the token" /></label>
        )}
        {authType === "header" && (
          <div className="row" style={{ alignItems: "flex-end", gap: 12, flexWrap: "nowrap" }}>
            <label className="field" style={{ flex: 1 }}><span>Header name</span>
              <input className="input" value={hName} onChange={(e) => setHName(e.target.value)} placeholder="X-API-Key" spellCheck={false} /></label>
            <label className="field" style={{ flex: 2 }}><span>Value</span>
              <input className="input" type="password" autoComplete="off" value={hValue} onChange={(e) => setHValue(e.target.value)} placeholder="paste the key" /></label>
          </div>
        )}
      </Modal>

      {/* 2b. the server's own sign-in window is open */}
      <Modal open={!!signIn} eyebrow="Step 2 of 7 · Authenticate" title="Finish signing in"
        onClose={clear}
        footer={<>
          <button type="button" className="btn" onClick={clear}>Cancel</button>
          <a className="btn primary" href={signIn || "#"} target="mcp-guardian-signin" rel="noreferrer" data-autofocus>Open sign-in page <Arrow /></a>
        </>}>
        <p>A sign-in window should have opened on {hostOf(url)}. Approve access there and Guardian continues by itself. If nothing opened, your browser may have blocked the pop-up: use the button below.</p>
        <p className="muted" style={{ fontSize: "var(--fs-sm)" }}><span className="spinner" /> Waiting for you to approve access…</p>
      </Modal>

      {/* 4. the inspection finished */}
      <Modal open={modal === "inspected"} eyebrow="Step 4 of 7 · Review" title="Inspection complete"
        onClose={() => setModal(null)}
        footer={<>
          <button type="button" className="btn" onClick={() => setModal(null)}>Review the results</button>
          <button type="button" className="btn primary" onClick={() => openConfigure(pickedTool)} data-autofocus>Choose tool and model <Arrow /></button>
        </>}>
        <p>Guardian connected to {hostOf(url)} and read the tool descriptions. No tool was called.</p>
        <div className="stat-row">
          <div className="stat"><b>{tools?.length ?? 0}</b><span>Inspected</span></div>
          <div className={`stat${flagged.length ? " bad" : ""}`}><b>{flagged.length}</b><span>Flagged</span></div>
          <div className="stat"><b>{snapshot?.notInspected.length ?? 0}</b><span>Not inspected</span></div>
        </div>
        {flagged.length > 0 ? (
          <ul className="flag-list">
            {flagged.slice(0, 6).map((t) => (
              <li key={t.name}><span className={`vpill ${t.verdict}`}>{t.definition_changed ? "changed" : t.verdict}</span><code>{t.name}</code></li>
            ))}
            {flagged.length > 6 && <li className="muted">and {flagged.length - 6} more</li>}
          </ul>
        ) : <p>Nothing suspicious was found in the descriptions.</p>}
        <p>Next you can pick one tool and the model that should inspect it, and run it through the full pipeline: policy gate, the real call, the check of the reply, behaviour and the final decision.</p>
      </Modal>

      {/* 5. tool and model */}
      <Modal wide open={modal === "configure"} eyebrow="Step 5 of 7 · Tool and model" title="Choose what to run"
        onClose={() => setModal(null)}
        footer={<>
          <button type="button" className="btn" onClick={() => setModal(snapshot && mode === "inspect" ? "inspected" : null)}>Back</button>
          <button type="button" className="btn primary" onClick={runPipeline} disabled={!pickedTool || running || !modelReady}>
            <Play /> Run full pipeline
          </button>
        </>}>
        <p>The call goes through the policy gate first, so a tool Guardian judges dangerous is stopped before the server sees anything.</p>
        <div className="field-label">Tool</div>
        <div className={`choice-list${(tools || []).length > 6 ? " tool-choices" : ""}`} role="radiogroup" aria-label="Tool">
          {(tools || []).map((t) => (
            <label key={t.name} className={`choice${pickedTool === t.name ? " on" : ""}`}>
              <input type="radio" name="tool" checked={pickedTool === t.name} onChange={() => pick(t)} />
              <span>
                <b><code>{t.name}</code> <span className={`vpill ${t.verdict}`}>{t.verdict}</span>
                  {(t.safe_to_try || t.looks_read_only) && <span className="tag">Looks read-only</span>}</b>
                <small>{clip(t.description || t.reasoning, 150)}</small>
              </span>
            </label>
          ))}
        </div>
        <label className="field">
          <span>Arguments (JSON){picked?.safe_to_try ? " · no input needed" : ""}</span>
          <textarea className="textarea" value={argsText} onChange={(e) => { setArgsText(e.target.value); setArgsError(null); }} rows={4} spellCheck={false} />
        </label>
        {argsError && <div className="notice error modal-error" role="alert" style={{ marginTop: 10 }}>{argsError}</div>}
        {chain.length > 0 && (
          <label className="field" style={{ marginTop: 14 }}>
            <span>Inspector model</span>
            <select className="select" value={model} onChange={(e) => setModel(e.target.value)}>
              <option value="">Automatic: the first available model</option>
              {chain.map((c) => <option key={c.model} value={c.model}>{prettyModel(c.model)} · {c.provider === "ollama" ? "local" : "OpenRouter"}</option>)}
            </select>
          </label>
        )}
        <p className="muted" style={{ fontSize: "var(--fs-xs)", margin: "8px 0 0" }}>
          The chosen model reads the tool description and the reply. If it fails or times out, Guardian falls back to the next one, and says so in the result.
        </p>
      </Modal>
    </main>
  );
}
