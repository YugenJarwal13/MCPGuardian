import { useEffect, useState } from "react";
import { fetchServers, fetchTools, resetServer } from "../api.js";
import { Info, Play } from "../components/Icons.jsx";
import RunView from "../components/RunView.jsx";
import { usePipelineRun } from "../hooks/usePipelineRun.js";

const shortName = (s) => s.name.replace(/^DVMCP\s*[-–:]?\s*/i, "").replace(/^Challenge\s*/i, "Ch. ");

function Chip({ s, selected, onSelect, disabled }) {
  const offline = s.port && !s.live;
  return (
    <button type="button" className={`pick-chip${offline ? " off" : ""}`} aria-pressed={selected} disabled={disabled}
      onClick={() => onSelect(s)} title={s.attack_category ? s.attack_category.replaceAll("_", " ") : "in-process fixture"}>
      {s.port ? <span className={`d${s.live ? "" : " off"}`} /> : null}{shortName(s)}
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
  const [formError, setFormError] = useState(null);
  const { events, running, error, start, approve, reset } = usePipelineRun();

  const modelReady = !health || health.llm?.available;

  const selectServer = (s) => {
    reset();
    setServer(s);
    setTools([]);
    setToolsError(null);
    setFormError(null);
    setToolName(s.default_tool || "");
    setArgsText(JSON.stringify(s.default_args || {}, null, 2));
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
    let args;
    try {
      args = JSON.parse(argsText || "{}");
    } catch {
      setFormError("Arguments must be valid JSON.");
      return;
    }
    setFormError(null);
    start({ server_id: server.id, tool_name: toolName || null, arguments: args, use_llm: true });
  };

  return (
    <main className="site">
      <section className="page-hero">
        <div className="wrap">
          <div className="eyebrow">Live demo</div>
          <h1>Watch Guardian protect an agent, one step at a time.</h1>
          <p className="lead sm">Pick a server, run one tool call, and follow every check as the real backend performs it.</p>
          <div className="about-note">
            <span className="ic"><Info /></span>
            <p>
              <b>About the data.</b> The poisoned servers come from <b>DVMCP</b> (Damn Vulnerable MCP Server), an open-source lab
              of ten deliberately vulnerable MCP servers. It is used here only as a controlled dataset to demonstrate the
              pipeline, alongside a few offline stand-ins and clean reference servers. Nothing on this page touches a real service.
            </p>
          </div>
        </div>
      </section>

      <div className="wrap" style={{ paddingBottom: 96 }}>
        <div className="stack-lg">
          <div className="ctrl-card">
            <div className="ctrl-col">
              <div className="ctrl-title"><i>1</i> Pick a server</div>
              {!servers && !formError && <p className="muted">Loading servers…</p>}
              {servers && (
                <>
                  <div className="group-h">Poisoned · should be caught</div>
                  <div className="chips-pick">{servers.poisoned.map((s) => <Chip key={s.id} s={s} selected={server?.id === s.id} onSelect={selectServer} disabled={running} />)}</div>
                  <div className="group-h">Clean · should pass</div>
                  <div className="chips-pick">{servers.clean.map((s) => <Chip key={s.id} s={s} selected={server?.id === s.id} onSelect={selectServer} disabled={running} />)}</div>
                </>
              )}
            </div>
            <div className="ctrl-col">
              <div className="ctrl-title"><i>2</i> Run a tool call{server ? <span className="muted"> on {server.name}</span> : null}</div>
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
                  <details className="args-box">
                    <summary>Arguments (JSON)</summary>
                    <textarea className="textarea" value={argsText} onChange={(e) => setArgsText(e.target.value)}
                      rows={Math.min(6, argsText.split("\n").length + 1)} spellCheck={false} disabled={running} />
                  </details>
                  <div className="row" style={{ marginTop: 16 }}>
                    <button type="button" className="btn primary lg grow" onClick={run} disabled={running || !!toolsError || !modelReady}>
                      {running ? <><span className="spinner" /> Running</> : <><Play /> Run the pipeline</>}
                    </button>
                    <button type="button" className="btn quiet" disabled={running} title="Forget this server's behavioural history"
                      onClick={() => resetServer(server.id).then(reset)}>Reset history</button>
                  </div>
                </>
              ) : <p className="muted">Choose a server on the left.</p>}
              {(formError || error) && <div className="notice error" style={{ marginTop: 12 }}>{formError || error}</div>}
              {toolsError && <div className="notice warn" style={{ marginTop: 12 }}>{toolsError}</div>}
              {!modelReady && <div className="notice error" style={{ marginTop: 12 }}>No language model is reachable, so the pipeline cannot run. Check the backend's OpenRouter settings.</div>}
            </div>
          </div>

          <RunView events={events} running={running} onApprove={approve} serverName={server?.name?.replace(/^DVMCP\s*[-–:]?\s*/i, "DVMCP ")} />
        </div>
      </div>
    </main>
  );
}
