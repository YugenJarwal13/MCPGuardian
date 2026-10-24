import { useEffect, useState } from "react";
import { fetchServers, fetchTools, resetServer } from "../api.js";
import { Info, Play } from "../components/Icons.jsx";
import RunView from "../components/RunView.jsx";
import { usePipelineRun } from "../hooks/usePipelineRun.js";

const label = (s) => s.name.replace(/^DVMCP\s*[-–:]?\s*/i, "").replace(/^Challenge\s*/i, "Ch. ");

function Chip({ s, selected, onSelect, disabled }) {
  const offline = s.port && !s.live;
  return (
    <button type="button" className={`pick-chip${offline ? " off" : ""}`} aria-pressed={selected} disabled={disabled}
      onClick={() => onSelect(s)} title={s.attack_category ? s.attack_category.replaceAll("_", " ") : "in-process fixture"}>
      {s.port ? <span className={`d${s.live ? "" : " off"}`} /> : null}{label(s)}
    </button>
  );
}

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

  const selectServer = (s) => {
    reset();
    setServer(s);
    setTools([]);
    setToolsError(null);
    setFormError(null);
    setToolName(s.default_tool || "");
    setArgsText(JSON.stringify(s.default_args || {}, null, 2));
    if (s.port && !s.live) {
      setToolsError(`This DVMCP server is not running on port ${s.port}. Start the lab with: python scripts/run_dvmcp_native.py`);
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

  useEffect(() => {
    fetchServers()
      .then((data) => {
        setServers(data);
        const first = [...data.poisoned, ...data.clean].find((s) => s.id === "dvmcp-ch2" && s.live)
          || data.poisoned.find((s) => s.live) || data.clean[0];
        if (first) selectServer(first);
      })
      .catch((e) => setFormError(`Cannot reach the API: ${e.message}. Start it with: bash backend/scripts/run_api.sh`));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  const llmReady = health?.llm?.available;

  return (
    <main className="site">
      <section className="page-hero">
        <div className="wrap">
          <div className="eyebrow">Live demo</div>
          <h1>Watch Guardian protect an agent, one step at a time.</h1>
          <div className="about-note">
            <span className="ic"><Info /></span>
            <p>
              <b>About this demo.</b> The servers below come from <b>DVMCP</b> (Damn Vulnerable MCP Server), an open-source
              training lab of ten deliberately vulnerable MCP servers, alongside a few offline stand-ins and clean reference servers. We use them purely as a
              controlled dataset to demonstrate the pipeline; nothing here touches a real service. Every step you see is
              produced by the real backend: the CrewAI inspectors, the Google ADK behaviour layer and the A2A hand-off.
            </p>
          </div>
        </div>
      </section>

      <div className="wrap" style={{ paddingBottom: 96 }}>
        <div className="stack-lg">
          <div className="panel ctrl">
            <div>
              <div className="panel-title">1 · Pick a server</div>
              {!servers && !formError && <p className="muted">Loading servers…</p>}
              {servers && (
                <>
                  <div className="group-h">Poisoned (should be caught)</div>
                  <div className="chips-pick">{servers.poisoned.map((s) => <Chip key={s.id} s={s} selected={server?.id === s.id} onSelect={selectServer} disabled={running} />)}</div>
                  <div className="group-h">Clean (should sail through)</div>
                  <div className="chips-pick">{servers.clean.map((s) => <Chip key={s.id} s={s} selected={server?.id === s.id} onSelect={selectServer} disabled={running} />)}</div>
                </>
              )}
            </div>
            <div>
              <div className="panel-title">2 · Run it{server ? <span className="muted"> · {server.name}</span> : null}</div>
              {server ? (
                <>
                  <label className="field">
                    <span>Tool</span>
                    {tools.length ? (
                      <select className="select" value={toolName} onChange={(e) => selectTool(e.target.value)} disabled={running}>
                        {tools.map((t) => <option key={t.name} value={t.name}>{t.name}</option>)}
                      </select>
                    ) : <input className="input" value={toolName} readOnly />}
                  </label>
                  <label className="field">
                    <span>Arguments (JSON)</span>
                    <textarea className="textarea" value={argsText} onChange={(e) => setArgsText(e.target.value)}
                      rows={Math.min(6, argsText.split("\n").length + 1)} spellCheck={false} disabled={running} />
                  </label>
                  <div className="row" style={{ marginTop: 14 }}>
                    <button type="button" className="btn primary" onClick={run} disabled={running || !!toolsError}>
                      {running ? <><span className="spinner" /> Running</> : <><Play /> Run the pipeline</>}
                    </button>
                    <label className="switch" title={llmReady ? "" : "No model is configured: the API falls back to the regex rules"}>
                      <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} disabled={running} />
                      Use AI inspectors
                    </label>
                    <button type="button" className="btn quiet" disabled={running} title="Forget this server's behavioural history"
                      onClick={() => resetServer(server.id).then(reset)}>Reset history</button>
                  </div>
                </>
              ) : <p className="muted">Choose a server on the left.</p>}
              {(formError || error) && <div className="notice error" style={{ marginTop: 12 }}>{formError || error}</div>}
              {toolsError && <div className="notice warn" style={{ marginTop: 12 }}>{toolsError}</div>}
              {useLlm && health && !llmReady && <div className="notice warn" style={{ marginTop: 12 }}>No language model is reachable, so the inspectors will run on regex rules. Each step labels which engine answered.</div>}
            </div>
          </div>

          <RunView events={events} running={running} onApprove={approve} serverName={server?.name?.replace(/^DVMCP\s*[-–:]?\s*/i, "DVMCP ")} />
        </div>
      </div>
    </main>
  );
}
