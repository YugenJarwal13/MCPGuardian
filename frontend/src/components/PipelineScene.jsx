import { engineLabel, narrate } from "../narration.js";
import { foldEvents } from "./PipelineView.jsx";
import { Agent, Envelope, Folder, Gate, Human, Magnifier, Pulse, Scanner, Scroll, ServerBox, ShieldIcon } from "./Sketch.jsx";

// Geometry of the scene (viewBox units). Two lanes inside the Guardian frame:
//   top lane    (agent -> server): read the labels, policy gate, the real call
//   bottom lane (server -> agent): scan the answer, watch behaviour, file the case, decide
const TOP = 140;
const BOT = 400;
const AG = { x: 82, y: 272 };
const SV = { x: 1076, y: 272 };
const ST = {
  static_check: { x: 330, y: TOP, title: "Read the labels", sub: "CrewAI", icon: "mag" },
  tool_call: { x: 650, y: TOP, title: "Policy gate", sub: "rules", icon: "gate" },
  runtime_check: { x: 830, y: BOT, title: "Scan the answer", sub: "CrewAI", icon: "scan" },
  behavioral_check: { x: 640, y: BOT, title: "Watch behaviour", sub: "Google ADK", icon: "pulse" },
  a2a_hop: { x: 450, y: BOT, title: "Case manager", sub: "ADK via A2A", icon: "folder" },
  enforcement: { x: 260, y: BOT, title: "Final decision", sub: "policy", icon: "shield" },
};
const PK_TOP = TOP - 72;
const PK_BOT = BOT + 74;
const SRV_TOP = { x: 992, y: PK_TOP };
const SRV_BOT = { x: 992, y: PK_BOT };
const PK_AGENT = { x: 156, y: 318 };

const clip = (s, n) => (s && s.length > n ? `${s.slice(0, n - 1)}…` : s || "");

function StationIcon({ kind, active, status }) {
  const k = { mag: Magnifier, gate: Gate, scan: Scanner, pulse: Pulse, folder: Folder }[kind];
  if (kind === "shield") {
    return <ShieldIcon scale={0.62} mark={status === "blocked" ? "cross" : status === "passed" ? "check" : "none"} />;
  }
  if (kind === "gate") return <Gate x={-12} y={-12} open={status === "passed"} scale={1.15} />;
  const Cmp = k;
  return <Cmp scale={1.15} />;
}

function Station({ id, cfg, state, top }) {
  const status = state.status;
  const active = status === "active";
  const sub = engineLabel(state) || cfg.sub;
  const frameworkLine = engineLabel(state) ? `${cfg.sub} · ${engineLabel(state)}` : cfg.sub;
  const labelY = top ? cfg.y + 72 : cfg.y - 98;
  const word = state.word ?? { pending: "", active: "working…", passed: id === "enforcement" ? "decided" : "clean", flagged: "flagged", blocked: "stopped",
    escalate: "needs a human", skipped: "skipped", error: "error" }[status];
  return (
    <g className={`station is-${status}`} transform={`translate(${cfg.x} ${cfg.y})`}>
      {active && <circle className="halo" r="58" />}
      <circle className="ring-bg" r="46" />
      {active && <circle className="ring-spin" r="52" />}
      <circle className="ring" r="46" />
      <g className="icon"><StationIcon kind={cfg.icon} active={active} status={status} /></g>
      <g transform={`translate(0 ${labelY - cfg.y})`}>
        <text className="st-title" textAnchor="middle" y="0">{cfg.title}</text>
        <text className="st-sub" textAnchor="middle" y="16">{clip(frameworkLine, 30) || sub}</text>
        {word && <text className="st-word" textAnchor="middle" y="32">{word}</text>}
      </g>
      {status === "passed" && <circle className="tick" cx="34" cy="-34" r="11" />}
      {status === "passed" && <path className="tick-mark" d="M28 -34 l4 4 l8 -9" />}
      {(status === "flagged" || status === "blocked") && <circle className="tick bad" cx="34" cy="-34" r="11" />}
      {(status === "flagged" || status === "blocked") && <path className="tick-mark" d="M29 -39 l10 10 M39 -39 l-10 10" />}
    </g>
  );
}

/** Where the data packet is, what it carries and whether it is (still) trusted. */
function packetFor(fold, last) {
  if (!last) return null;
  const d = last.detail || {};
  const tainted = ["static_check", "runtime_check", "behavioral_check"].some((s) => ["flagged", "blocked"].includes(fold[s].status));
  const base = (pos, label, kind = "env", tone) => ({ ...pos, label, kind, tone: tone || (tainted ? "bad" : "ok") });
  const s = last.status;
  switch (last.stage) {
    case "connect":
      return s === "error" ? base(SRV_TOP, "unreachable", "env", "bad") : base(SRV_TOP, s === "started" ? "hello?" : "connected ✓", "env", "ok");
    case "list_tools":
      if (s === "started") return base(SRV_TOP, "tools/list?", "env", "ok");
      return base({ x: ST.static_check.x, y: PK_TOP }, `${(d.tools || []).length} descriptions`, "scroll", "ok");
    case "static_check":
      return base({ x: ST.static_check.x, y: PK_TOP }, s === "started" ? "reading…" : s === "flagged" ? "hidden order!" : "looks clean", "scroll",
        s === "flagged" ? "bad" : "ok");
    case "tool_call":
      if (s === "started" && /^Policy/.test(last.message)) return base({ x: ST.tool_call.x, y: PK_TOP }, `call ${clip(d.tool || fold.list_tools.detail?.selected || "tool", 12)}`);
      if (s === "started") return base(SRV_TOP, "running the tool");
      if (s === "blocked") return base({ x: ST.tool_call.x, y: PK_TOP }, "blocked", "env", "bad");
      if (s === "escalate") return base({ x: ST.tool_call.x, y: PK_TOP }, "waiting for you", "env", "warn");
      return base(SRV_BOT, "response", "scroll");
    case "runtime_check":
      return base({ x: ST.runtime_check.x, y: PK_BOT }, s === "started" ? "reading answer…" : s === "flagged" ? "hidden order!" : "ordinary data", "scroll",
        s === "flagged" ? "bad" : tainted ? "bad" : "ok");
    case "behavioral_check":
      return base({ x: ST.behavioral_check.x, y: PK_BOT }, s === "started" ? "comparing…" : s === "flagged" ? "drift!" : "as usual", "scroll");
    case "a2a_hop":
      return base({ x: ST.a2a_hop.x, y: PK_BOT }, "A2A message", "env");
    case "enforcement":
      return base({ x: ST.enforcement.x, y: PK_BOT }, s === "blocked" ? "withheld" : s === "escalate" ? "needs human" : "deciding…", "env",
        s === "blocked" ? "bad" : s === "escalate" ? "warn" : undefined);
    case "done": {
      if (last.status === "error") return base(PK_AGENT, "stopped", "env", "bad");
      if (d.inspect_only) return base({ x: ST.static_check.x, y: PK_TOP }, "inspected", "scroll", (d.tools || []).some((t) => t.verdict !== "clean") ? "bad" : "ok");
      const ok = d.final_decision === "allow" || d.final_decision === "escalate_approved";
      return ok ? base(PK_AGENT, "delivered ✓", "scroll", "ok") : base({ x: ST.enforcement.x, y: PK_BOT }, "withheld", "env", "bad");
    }
    default:
      return null;
  }
}

function Packet({ p }) {
  if (!p) return null;
  const w = Math.max(70, p.label.length * 6.4 + 18);
  return (
    <g className={`packet tone-${p.tone}`} style={{ transform: `translate(${p.x}px, ${p.y}px)` }}>
      <g className="bob">{p.kind === "scroll" ? <Scroll scale={0.78} bad={p.tone === "bad"} /> : <Envelope scale={0.78} bad={p.tone === "bad"} />}</g>
      <g transform="translate(24 -2)">
        <rect className="pk-chip" x="0" y="-12" width={w} height="24" rx="12" />
        <text className="pk-text" x={w / 2} y="4" textAnchor="middle">{p.label}</text>
      </g>
    </g>
  );
}

function Bubble({ x, y, w, lines, tone, tail = "down" }) {
  const h = 20 + lines.length * 16;
  return (
    <g transform={`translate(${x} ${y})`}>
      <g className={`bubble tone-${tone}`}>
        <rect className="bub" x="0" y="0" width={w} height={h} rx="12" />
        {tail === "down" && <path className="bub" d={`M${w / 2 - 8} ${h} l8 14 l8 -14`} />}
        {lines.map((l, i) => (
          <text key={i} className={`bub-text${i === 0 && lines.length > 1 ? " dim" : ""}`} x={w / 2} y={20 + i * 16} textAnchor="middle">{l}</text>
        ))}
      </g>
    </g>
  );
}

function wrap(text, n, maxLines) {
  const words = String(text || "").split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = "";
  for (const w of words) {
    if ((cur + " " + w).trim().length > n) {
      lines.push(cur);
      cur = w;
    } else cur = (cur + " " + w).trim();
  }
  if (cur) lines.push(cur);
  const out = lines.slice(0, maxLines);
  if (lines.length > maxLines) out[maxLines - 1] = clip(out[maxLines - 1] + "…", n);
  return out;
}

/**
 * The live pipeline as a picture a non-engineer can follow. Driven only by the events the
 * backend streams: every station lights up when its stage starts, shows what it concluded,
 * and the data packet physically travels the same path the real call takes.
 */
export default function PipelineScene({ events, serverName, notRun = [] }) {
  const fold = foldEvents(events);
  for (const id of Object.keys(fold)) {
    if (fold[id].detail?.skipped) fold[id] = { ...fold[id], status: "skipped" };
  }
  const last = events[events.length - 1] || null;
  const packet = packetFor(fold, last);
  const inspected = [...events].reverse().find((e) => e.stage === "done" && e.detail?.inspect_only);
  if (inspected) {
    // inspection-only run: the first station speaks for the whole server, not for one tool
    const all = inspected.detail.tools || [];
    const bad = all.filter((t) => t.verdict !== "clean").length;
    fold.static_check = { ...fold.static_check, status: bad ? "flagged" : "passed",
      word: bad ? `${bad} of ${all.length} flagged` : `all ${all.length} clean` };
  }
  const done = events.find((e) => e.stage === "done") ? [...events].reverse().find((e) => e.stage === "done") : null;
  const final = done?.detail?.final_decision;
  const inspectOnly = !!done?.detail?.inspect_only;
  const allowed = final === "allow" || final === "escalate_approved";

  const staticFlag = fold.static_check.status === "flagged";
  const runtimeFlag = fold.runtime_check.status === "flagged";
  const danger = staticFlag || runtimeFlag || (inspectOnly && (done.detail.tools || []).some((t) => t.verdict !== "clean"));
  const phrase = (runtimeFlag ? fold.runtime_check : fold.static_check).detail?.flagged_phrases?.[0];
  const decisionLabel = final === "allow" ? "ALLOW" : final === "escalate_approved" ? "ALLOWED" : final === "block" || final === "escalate_denied" ? "BLOCK" : null;
  const waitingAt = Object.entries(fold).find(([, s]) => s.status === "escalate")?.[0];
  const waitingHuman = !!waitingAt;

  const agentSays = !done ? null
    : inspectOnly ? null
    : allowed ? { lines: ["Got a safe", "response ✓"], tone: "ok" }
      : { lines: ["Refused safely.", "Nothing harmful", "reached me."], tone: "ok" };
  const mood = !last ? "happy" : done && !done.detail?.inspect_only ? "happy" : "alert";
  const banner = last && last.status !== "escalate" ? clip(last.message.replace(/…$/, ""), 78) : last ? "Waiting for a human decision" : "Press “Run” to start";

  return (
    <div className="scene-wrap">
      <svg className="scene" viewBox="0 0 1160 548" role="img" aria-label="Animated diagram of the Guardian pipeline">
        {/* frame */}
        <rect className="g-frame" x="176" y="46" width="840" height="470" rx="30" />
        <g transform="translate(496 46)">
          <rect className="g-tab" x="-82" y="-15" width="164" height="30" rx="15" />
          <text className="g-tab-text" textAnchor="middle" y="5">MCP GUARDIAN</text>
        </g>

        {/* lanes */}
        <path className={`lane${last ? " live" : ""}`} d={`M 120 236 Q 120 ${TOP} 176 ${TOP} H 1010 Q 1046 ${TOP} 1046 226`} />
        <path className={`lane${last ? " live" : ""}`} d={`M 1046 318 Q 1046 ${BOT} 1010 ${BOT} H 176 Q 120 ${BOT} 120 312`} />
        <text className="lane-tag" x="196" y="176">① before the call</text>
        <text className="lane-tag" x="196" y="506">② before the agent sees the answer</text>

        {/* actors */}
        <Agent x={AG.x} y={AG.y} mood={mood} />
        <text className="lbl" x={AG.x} y={AG.y + 76} textAnchor="middle">AI agent</text>
        <ServerBox x={SV.x} y={SV.y} danger={danger} />
        <text className="lbl" x={SV.x} y={SV.y + 76} textAnchor="middle">{clip(serverName || "MCP server", 20)}</text>
        {agentSays && <Bubble x={8} y={96} w={148} lines={agentSays.lines} tone={agentSays.tone} />}
        {danger && phrase && (
          <Bubble x={992} y={64} w={162} lines={["hidden in the text:", ...wrap(`“${phrase}”`, 24, 2)]} tone="bad" />
        )}

        {/* stations */}
        {Object.entries(ST).map(([id, cfg]) => (
          <Station key={id} id={id} cfg={cfg} top={cfg.y === TOP} state={notRun.includes(id) && fold[id].status === "pending" ? { ...fold[id], status: "skipped" } : fold[id]} />
        ))}

        {/* human */}
        {waitingHuman && (
          <g transform={`translate(${ST[waitingAt].x + 84} ${ST[waitingAt].y + (ST[waitingAt].y === TOP ? 6 : -6)})`}>
            <g className="human-wait">
              <Human scale={1.1} />
              <text className="lbl acc" y="40" textAnchor="middle">your call</text>
            </g>
          </g>
        )}

        {/* verdict stamp */}
        {decisionLabel && !inspectOnly && (
          <g className={`stamp-final ${allowed ? "ok" : "bad"}`} transform={`translate(${ST.enforcement.x} ${BOT}) rotate(-9)`}>
            <rect x="-62" y="-20" width="124" height="40" rx="8" />
            <text y="8" textAnchor="middle">{decisionLabel}</text>
          </g>
        )}

        {/* the live status line */}
        <g transform="translate(596 268)">
          <rect className="banner" x="-300" y="-17" width="600" height="34" rx="17" />
          <text className="banner-text" textAnchor="middle" y="5">{banner}</text>
        </g>

        <Packet p={packet} />
      </svg>
    </div>
  );
}

export function SceneNarration({ events }) {
  const fold = foldEvents(events);
  const last = events[events.length - 1] || null;
  const n = narrate(fold, last);
  return (
    <div className={`narration tone-${n.tone}`} role="status" aria-live="polite">
      <div className="nar-kicker">{last ? "What is happening right now" : "How this works"}</div>
      <h3 key={`${last?.stage}-${last?.status}`}>{n.title}</h3>
      <p key={`p-${last?.stage}-${last?.status}-${last?.message}`}>{n.body}</p>
      {n.tech && <code className="nar-tech">{n.tech}</code>}
    </div>
  );
}
