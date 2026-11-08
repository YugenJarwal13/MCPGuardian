import { useCallback, useEffect, useRef, useState } from "react";
import { fetchServers, fetchTools, resetServer, startRun } from "../api.js";
import AutoFollowToggle from "../components/AutoFollowToggle.jsx";
import FlowStepper from "../components/FlowStepper.jsx";
import { Info, Play } from "../components/Icons.jsx";
import { prettyModel } from "../components/LlmStatus.jsx";
import RunView from "../components/RunView.jsx";
import { useAutoFollow } from "../hooks/useAutoFollow.js";
import { usePipelineRun } from "../hooks/usePipelineRun.js";

const STEPS = ["Select a scenario", "Configure the tool", "Execute the pipeline", "Review the results"];

// One short line per DVMCP challenge, shown on its card. The titles come from the server list.
const BLURB = {
  1: "Hidden instructions", 2: "Malicious descriptions", 3: "Unnecessary permissions", 4: "Behaviour changes",
  5: "Cross-tool manipulation", 6: "Injected tool responses", 7: "Credential exposure", 8: "Malicious commands",
  9: "Unauthorised access", 10: "Combined attacks",
};

const challengeNumber = (s) => (/^dvmcp-ch(\d+)$/.exec(s.id) || [])[1];
const cleanTitle = (s) => s.name.replace(/^Challenge\s*\d+\s*[—–-]\s*/i, "").replace(/\s*\(.*\)\s*$/, "");

function Card({ s, selected, onSelect, disabled }) {
  const n = challengeNumber(s);
  const offline = s.port && !s.live;
  const raw = n ? BLURB[n] : (s.attack_category || "clean reference").replaceAll("_", " ");
  const blurb = raw.charAt(0).toUpperCase() + raw.slice(1);
  return (
    <button type="button" className={`scenario${selected ? " on" : ""}${offline ? " off" : ""}`} aria-pressed={selected}
      disabled={disabled} onClick={() => onSelect(s)}>
      <span className="sc-num">{n ? String(n).padStart(2, "0") : "·"}</span>
      <span className="sc-text"><b>{n ? cleanTitle(s) : s.name.replace(/\s*\(.*\)\s*$/, "")}</b><small>{blurb}</small></span>
      {s.port ? <span className={`sc-state${s.live ? "" : " off"}`}>{s.live ? "running" : "not running"}</span> : null}
    </button>
  );
}

function Group({ title, count, children }) {
  return (
    <div className="sc-group">
      <div className="group-h">{title} <span className="sc-count">{count}</span></div>
      <div className="scenario-grid">{children}</div>
    </div>
  );
}

export default function DemoPage({ health }) {
  const [servers, setServers] = useState(null);
  const [server, setServer] = useState(null);
  const [tools, setTools] = useState([]);
  const [toolsError, setToolsError] = useState(null);
  const [toolName, setToolName] = useState("");
  const [argsText, setArgsText] = useState("{}");
  const [formError, setFormError] = useState(null);
  const [model, setModel] = useState("");
  const [ran, setRan] = useState(false);
  const { events, running, error, start, approve, reset } = usePipelineRun();
  const { enabled: follow, setEnabled: setFollow, follow: goTo } = useAutoFollow();

  const configRef = useRef(null);
  const liveRef = useRef(null);
  const resultsRef = useRef(null);
  const userPicked = useRef(false);

  const modelReady = !health || health.llm?.available;
  const chain = (health?.llm?.chain || []).filter((c) => c.usable);
  const done = [...events].reverse().find((e) => e.stage === "done");

  // Rug-pull fixture: it behaves for 10 calls and changes on call 11, so the page tracks the call count.
  const [calls, setCalls] = useState(0);
  const [ff, setFf] = useState(null);
  const flipsAfter = server?.flips_after;
  const isRugPull = flipsAfter != null;
  const refreshCalls = useCallback(() => {
    if (!server) return;
    fetchServers().then((data) => {
      const s = [...data.poisoned, ...data.clean].find((x) => x.id === server.id);
      if (s) setCalls(s.calls_made ?? 0);
    }).catch(() => {});
  }, [server]);
  useEffect(() => { refreshCalls(); }, [refreshCalls, running]);

  const parseArgs = () => {
    try {
      const args = JSON.parse(argsText || "{}");
      if (args === null || typeof args !== "object" || Array.isArray(args)) throw new Error("not an object");
      return args;
    } catch {
      setFormError("The arguments must be a JSON object.");
      return null;
    }
  };

  const fastForward = async () => {
    const args = parseArgs();
    if (!args) return;
    const total = Math.max(0, flipsAfter - calls);
    reset();
    for (let i = 0; i < total; i += 1) {
      setFf({ done: i, total });
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, 90000);
        const handle = startRun({ server_id: server.id, tool_name: toolName || null, arguments: args, use_llm: true }, {
          onEvent: (ev) => { if (ev.stage === "done") { clearTimeout(timer); handle.close(); resolve(); } },
          onClose: resolve, onError: resolve,
        });
      });
    }
    setFf(null);
    refreshCalls();
  };

  const selectServer = (s) => {
    reset();
    setRan(false);
    setServer(s);
    setTools([]);
    setToolsError(null);
    setFormError(null);
    setToolName(s.default_tool || "");
    setArgsText(JSON.stringify(s.default_args || {}, null, 2));
    if (userPicked.current) setTimeout(() => goTo(configRef.current), 60);     // the first, automatic pick doesn't scroll
    if (s.port && !s.live) {
      setToolsError(`This DVMCP server is not running on port ${s.port}. Start the lab with start-lab.cmd.`);
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
  const onPick = (s) => { userPicked.current = true; selectServer(s); };

  useEffect(() => {
    fetchServers()
      .then((data) => {
        setServers(data);
        const first = [...data.poisoned, ...data.clean].find((s) => s.id === "dvmcp-ch2" && s.live)
          || data.poisoned.find((s) => s.live) || data.clean[0];
        if (first) selectServer(first);
      })
      .catch((e) => setFormError(`Cannot reach the API: ${e.message}. Start it with start-backend.cmd.`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectTool = (name) => {
    setToolName(name);
    const t = tools.find((x) => x.name === name);
    if (t) setArgsText(JSON.stringify(t.default_args || {}, null, 2));
  };

  const run = () => {
    const args = parseArgs();
    if (!args) return;
    setFormError(null);
    setRan(true);
    start({ server_id: server.id, tool_name: toolName || null, arguments: args, use_llm: true, ...(model ? { model } : {}) });
    setTimeout(() => goTo(liveRef.current), 60);
  };

  // finished: take the visitor to the verdict
  useEffect(() => {
    if (ran && done && !running) setTimeout(() => goTo(resultsRef.current), 400);
  }, [ran, done, running, goTo]);

  const current = !ran ? (server ? 1 : 0) : running ? 2 : done ? 3 : 2;
  const dvmcp = servers?.poisoned.filter((s) => s.id.startsWith("dvmcp-")) || [];
  const fixtures = servers?.poisoned.filter((s) => !s.id.startsWith("dvmcp-")) || [];
  const serverLabel = server?.name?.replace(/^DVMCP\s*[-–:]?\s*/i, "DVMCP ");

  return (
    <main className="site">
      <section className="page-hero">
        <div className="wrap">
          <div className="eyebrow">Live demo</div>
          <h1>Watch Guardian in action.</h1>
          <p className="lead sm">Explore attack scenarios and observe how each layer protects an AI agent. Every step shown is performed by the real backend.</p>
          <div className="about-note">
            <span className="ic"><Info /></span>
            <p>
              <b>About the data.</b> The attack scenarios come from <b>DVMCP</b> (Damn Vulnerable MCP Server), an open-source lab
              of ten deliberately vulnerable MCP servers. It is used here only as a controlled dataset to demonstrate the
              pipeline, alongside a few offline stand-ins and clean reference servers. Nothing on this page touches a real service.
            </p>
          </div>
          <div className="toolbar"><AutoFollowToggle enabled={follow} onChange={setFollow} /></div>
          <FlowStepper steps={STEPS} current={current} label="Live demo: progress" />
        </div>
      </section>

      <div className="wrap" style={{ paddingBottom: 96 }}>
        <div className="stack-lg">
          <section className="flow-section" aria-label="Select a scenario">
            <div className="section-head">
              <span className="num">01</span><h2>Select a scenario</h2>
              <p>Choose an attack to replay, or a clean server to confirm Guardian lets honest tools through.</p>
            </div>
            {!servers && !formError && <p className="muted">Loading scenarios…</p>}
            {servers && (
              <>
                <Group title="Attack scenarios" count={`${dvmcp.length} scenarios`}>
                  {dvmcp.map((s) => <Card key={s.id} s={s} selected={server?.id === s.id} onSelect={onPick} disabled={running} />)}
                </Group>
                {fixtures.length > 0 && (
                  <Group title="Offline stand-ins" count="no lab needed">
                    {fixtures.map((s) => <Card key={s.id} s={s} selected={server?.id === s.id} onSelect={onPick} disabled={running} />)}
                  </Group>
                )}
                <Group title="Clean reference servers" count={`${servers.clean.length} servers`}>
                  {servers.clean.map((s) => <Card key={s.id} s={s} selected={server?.id === s.id} onSelect={onPick} disabled={running} />)}
                </Group>
              </>
            )}
          </section>

          <section ref={configRef} className="flow-section" aria-label="Configure the tool">
            <div className="section-head">
              <span className="num">02</span><h2>Configure the tool</h2>
              <p>{server ? <>The call that will be sent to <b>{serverLabel}</b>.</> : "Select a scenario first."}</p>
            </div>
            {server && (
              <div className="panel config-panel">
                <div className="config-grid">
                  <label className="field">
                    <span>Tool</span>
                    {tools.length ? (
                      <select className="select" value={toolName} onChange={(e) => selectTool(e.target.value)} disabled={running}>
                        {tools.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
                      </select>
                    ) : <input className="input" value={toolName} readOnly />}
                  </label>
                  {chain.length > 0 && (
                    <label className="field">
                      <span>Inspector model</span>
                      <select className="select" value={model} onChange={(e) => setModel(e.target.value)} disabled={running}>
                        <option value="">Automatic: the first available model</option>
                        {chain.map((c) => <option key={c.model} value={c.model}>{prettyModel(c.model)} · {c.provider === "ollama" ? "local" : "OpenRouter"}</option>)}
                      </select>
                    </label>
                  )}
                </div>
                <label className="field" style={{ marginTop: 12 }}>
                  <span>Arguments (JSON)</span>
                  <textarea className="textarea" value={argsText} onChange={(e) => setArgsText(e.target.value)}
                    rows={Math.min(7, argsText.split("\n").length + 1)} spellCheck={false} disabled={running} />
                </label>
                {isRugPull && (
                  <div className="rug-note">
                    <b>Rug pull:</b> {server.rug_hint} Calls so far: <b className="num">{calls}</b>.
                    {calls < flipsAfter && (
                      <button type="button" className="btn" onClick={fastForward} disabled={running || !!ff || !modelReady}>
                        {ff ? <><span className="spinner" /> Calling {ff.done + 1}/{ff.total}</> : `Fast-forward to the change (${flipsAfter - calls} quiet calls)`}
                      </button>
                    )}
                    {calls === flipsAfter && <span> The next call is the one that changes.</span>}
                    {calls > flipsAfter && <span> It has already changed; use Reset history to start over.</span>}
                  </div>
                )}
                {(formError || error) && <div className="notice error" role="alert" style={{ marginTop: 12 }}>{formError || error}</div>}
                {toolsError && <div className="notice warn" style={{ marginTop: 12 }}>{toolsError}</div>}
                {!modelReady && <div className="notice error" style={{ marginTop: 12 }}>No language model is reachable, so the pipeline cannot run. Check the backend’s OpenRouter settings.</div>}
                <div className="row" style={{ marginTop: 16 }}>
                  <button type="button" className="btn primary lg grow" onClick={run} disabled={running || !!ff || !!toolsError || !modelReady}>
                    {running ? <><span className="spinner" /> Running</> : <><Play /> Run the pipeline</>}
                  </button>
                  <button type="button" className="btn quiet" disabled={running || !!ff} title="Forget this server's behavioural history"
                    onClick={() => resetServer(server.id).then(() => { reset(); setRan(false); refreshCalls(); })}>Reset history</button>
                </div>
              </div>
            )}
          </section>

          <section ref={liveRef} className="flow-section" aria-label="Execute the pipeline">
            <div className="section-head">
              <span className="num">03</span><h2>Execute the pipeline</h2>
              <p>The call moves through each layer in turn. Anything that needs a decision from you appears here.</p>
            </div>
            <RunView part="live" events={events} running={running} onApprove={approve} serverName={serverLabel} />
          </section>

          <section ref={resultsRef} className="flow-section" aria-label="Review the results">
            <div className="section-head">
              <span className="num">04</span><h2>Review the results</h2>
              <p>The verdict, what the agent would have trusted without Guardian, and every stage in detail.</p>
            </div>
            {events.length === 0 && <div className="empty-slot">The verdict appears here once a run has finished.</div>}
            <RunView part="results" events={events} running={running} onApprove={approve} serverName={serverLabel} />
          </section>
        </div>
      </div>
    </main>
  );
}
