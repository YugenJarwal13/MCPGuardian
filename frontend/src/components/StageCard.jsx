import { useState } from "react";
import ElapsedTimer from "./ElapsedTimer.jsx";
import EngineBadge from "./EngineBadge.jsx";
import { Alert, Check, Chevron, Cross, Question } from "./Icons.jsx";
import TypingText from "./TypingText.jsx";

const NODE_ICON = { passed: Check, flagged: Alert, escalate: Question, blocked: Cross, error: Cross };

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Text with every flagged phrase wrapped in <mark>. */
export function Highlighted({ text, phrases }) {
  const usable = (phrases || []).filter((p) => p && p.trim().length > 1);
  if (!usable.length) return <>{text}</>;
  const re = new RegExp(`(${usable.map(escapeRegExp).join("|")})`, "i");
  const flagged = new Set(usable.map((p) => p.toLowerCase()));
  return (
    <>
      {text.split(re).map((part, i) =>
        flagged.has(part.toLowerCase()) ? <mark key={i}>{part}</mark> : <span key={i}>{part}</span>
      )}
    </>
  );
}

function Confidence({ verdict, value }) {
  const pct = Math.round((value || 0) * 100);
  return (
    <div className="conf">
      <span className={`vpill ${verdict}`}>{verdict}</span>
      <span className="bar" aria-hidden="true"><i className={verdict} style={{ width: `${pct}%` }} /></span>
      <span className="num">{pct}% confident</span>
    </div>
  );
}

function Row({ label, children }) {
  return (
    <div className="drow">
      <span className="dlabel">{label}</span>
      <div className="dvalue">{children}</div>
    </div>
  );
}

const KNOWN = new Set([
  "verdict", "confidence", "reasoning", "flagged_phrases", "description", "response_preview", "response",
  "arguments", "requested_scope", "other_flagged_tools", "engine", "skipped", "z_score", "new_keys",
  "structural_anomaly", "mean_length", "statistical_anomaly", "calls_observed", "transport", "url", "case_id",
  "case_decision", "round_trip_ms", "inspector_latency_ms", "note", "tools", "selected", "source", "endpoint",
  "decision", "refusal", "reason", "static", "final_decision", "tool", "engines", "models", "anomalous",
  "approved_scope", "provider", "model", "method", "cached", "model_latency_ms", "models_tried", "all_tools",
  "inspect_only", "hint",
]);

function Detail({ stage, detail, message }) {
  const phrases = detail.flagged_phrases || detail.static?.flagged_phrases || [];
  const rest = Object.fromEntries(Object.entries(detail).filter(([k]) => !KNOWN.has(k)));
  return (
    <div className="detail">
      {detail.verdict && <Confidence verdict={detail.verdict} value={detail.confidence} />}
      {detail.reasoning && <p className="reasoning">{detail.reasoning}</p>}
      {stage === "behavioral_check" && <p className="reasoning">{message}</p>}
      {phrases.length > 0 && (
        <Row label="Flagged phrases">
          <div className="chips">{phrases.map((p, i) => <code key={i} className="chip">{p}</code>)}</div>
        </Row>
      )}
      {detail.description && (
        <Row label="Tool description, as served">
          <pre className="quote"><Highlighted text={detail.description.trim()} phrases={phrases} /></pre>
        </Row>
      )}
      {detail.static && (
        <Row label="Static verdict">
          <Confidence verdict={detail.static.verdict} value={detail.static.confidence} />
          <p className="reasoning" style={{ marginTop: 6 }}>{detail.static.reasoning}</p>
        </Row>
      )}
      {(detail.response_preview || detail.response) && (
        <Row label="Tool response">
          <pre className="quote"><Highlighted text={detail.response_preview || detail.response} phrases={phrases} /></pre>
        </Row>
      )}
      {detail.arguments && (
        <Row label="Arguments"><pre className="quote">{JSON.stringify(detail.arguments, null, 2)}</pre></Row>
      )}
      {Array.isArray(detail.tools) && typeof detail.tools[0] === "string" && (
        <Row label="Tools on this server">
          <div className="chips">
            {detail.tools.map((t) => <code key={t} className={`chip ${t === detail.selected ? "sel" : "neutral"}`}>{t}</code>)}
          </div>
        </Row>
      )}
      {detail.z_score !== undefined && (
        <Row label="Fingerprint">
          z-score <b className="num">{detail.z_score}</b> · calls observed <b className="num">{detail.calls_observed}</b>
          {detail.new_keys?.length > 0 && <> · new keys <code>{detail.new_keys.join(", ")}</code></>}
          {detail.statistical_anomaly !== undefined && <> · statistics say <b>{detail.statistical_anomaly ? "anomalous" : "normal"}</b></>}
        </Row>
      )}
      {detail.transport && (
        <Row label="Transport">
          {detail.transport}{detail.url && <> → <code>{detail.url}</code></>}
          {detail.case_id && <><br />case <code>{detail.case_id}</code> recorded as <b>{detail.case_decision}</b></>}
          {detail.round_trip_ms != null && <> · <span className="num">{detail.round_trip_ms} ms</span> round trip</>}
        </Row>
      )}
      {detail.requested_scope && <Row label="Sensitive scope (from schema)">{detail.requested_scope}</Row>}
      {detail.approved_scope && <Row label="Approved scope">{detail.approved_scope}</Row>}
      {detail.other_flagged_tools?.length > 0 && <Row label="Other flagged tools">{detail.other_flagged_tools.join(", ")}</Row>}
      {detail.provider && (
        <Row label="Answered by">
          {detail.provider} · <code>{detail.model}</code>{detail.method && <> · {detail.method}</>}
          {detail.model_latency_ms != null && <> · <span className="num">{(detail.model_latency_ms / 1000).toFixed(1)} s</span></>}
          {detail.cached && <> · cached</>}
          {detail.models_tried?.length > 1 && (
            <ul className="tried">{detail.models_tried.map((t, i) => <li key={i}>{t}</li>)}</ul>
          )}
        </Row>
      )}
      {detail.refusal && <Row label="Returned to the agent instead">{detail.refusal}</Row>}
      {detail.reason && <Row label="Why">{detail.reason}</Row>}
      {detail.note && <Row label="Note">{detail.note}</Row>}
      {detail.hint && <Row label="Hint">{detail.hint}</Row>}
      {detail.endpoint && <Row label="Endpoint">{detail.endpoint}{detail.source && <> ({detail.source})</>}</Row>}
      {Object.keys(rest).length > 0 && (
        <details className="raw"><summary>Raw detail</summary><pre>{JSON.stringify(rest, null, 2)}</pre></details>
      )}
    </div>
  );
}

/** Inline approval panel (not a modal). */
function DecisionPanel({ detail, onApprove, message }) {
  const why = detail.reason || (detail.anomalous ? "The behavioural layer saw this tool change." : message);
  return (
    <div className="decision" role="group" aria-label="Human decision required">
      <h4>Your decision</h4>
      <p>{why} {detail.requested_scope && <>This tool can reach <b>{detail.requested_scope.replace("_", " ")}</b>.</>}</p>
      <div className="row">
        <button type="button" className="btn primary" onClick={() => onApprove(true)}>Approve</button>
        <button type="button" className="btn danger" onClick={() => onApprove(false)}>Deny</button>
        <span className="muted" style={{ fontSize: "var(--fs-xs)" }}>Nothing runs until you choose.</span>
      </div>
    </div>
  );
}

export default function StageCard({ index, title, subtitle, state, onApprove }) {
  const { status, message, detail = {}, engine, provider, model, elapsed_ms: elapsed, stage, startedAt } = state;
  const [pinned, setPinned] = useState(null); // null = follow the default; a click pins it
  const active = status === "active";
  const resolved = !["pending", "active", "skipped"].includes(status);
  const hasDetail = resolved && Object.keys(detail).length > 0;
  const autoOpen = ["flagged", "blocked", "escalate"].includes(status);
  const open = hasDetail && (pinned ?? autoOpen);
  const Icon = NODE_ICON[status];

  return (
    <li className={`stage is-${status}`} style={{ "--i": index }}>
      <div className="rail">
        <span className="node">{Icon ? <Icon /> : null}</span>
      </div>
      <article className="card">
        <button type="button" className={`card-head${hasDetail ? " clickable" : ""}`}
          onClick={() => hasDetail && setPinned(!open)} aria-expanded={hasDetail ? open : undefined}
          disabled={!hasDetail} aria-label={`${title}${hasDetail ? ", show details" : ""}`}>
          <span>
            <span className="stage-title">{title}</span>
            <span className="stage-sub" style={{ display: "block" }}>{subtitle}</span>
          </span>
          <span className="card-meta">
            <EngineBadge engine={engine} provider={provider} model={model} method={detail.method} cached={detail.cached} />
            <ElapsedTimer active={active} startedAt={startedAt} finalMs={elapsed} />
            {hasDetail && <span className="chev" data-open={open}><Chevron /></span>}
          </span>
        </button>
        <p className="status-line" aria-live={active ? "off" : "polite"}>
          {active && message ? <TypingText text={message} /> : message || (status === "pending" ? "Waiting…" : "")}
        </p>
        {status === "escalate" && <DecisionPanel detail={detail} message={message} onApprove={onApprove} />}
        <div className="expand" data-open={open}>
          <div className="expand-inner">{hasDetail && <Detail stage={stage} detail={detail} message={message} />}</div>
        </div>
      </article>
    </li>
  );
}
