import { useState } from "react";

const ICONS = {
  pending: "○",
  active: "◌",
  passed: "✓",
  flagged: "!",
  blocked: "✕",
  escalate: "?",
  error: "⚠",
};

const ENGINE_LABEL = { llm: "LLM", heuristic: "heuristic", heuristic_fallback: "LLM failed → heuristic" };

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Render text with every flagged phrase wrapped in <mark>. */
function Highlighted({ text, phrases }) {
  const usable = (phrases || []).filter((p) => p && p.trim().length > 1);
  if (!usable.length) return <>{text}</>;
  const re = new RegExp(`(${usable.map(escapeRegExp).join("|")})`, "i");
  const flagged = new Set(usable.map((p) => p.toLowerCase()));
  return (
    <>
      {text.split(re).map((part, i) =>
        flagged.has(part.toLowerCase()) ? (
          <mark key={i}>{part}</mark>
        ) : (
          <span key={i}>{part}</span>
        )
      )}
    </>
  );
}

function Confidence({ verdict, value }) {
  const pct = Math.round((value || 0) * 100);
  return (
    <div className="confidence">
      <span className={`verdict-pill ${verdict}`}>{verdict}</span>
      <div className="bar">
        <div className={`fill ${verdict}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="muted">{pct}% confident</span>
    </div>
  );
}

function Row({ label, children }) {
  return (
    <div className="detail-row">
      <span className="detail-label">{label}</span>
      <div className="detail-value">{children}</div>
    </div>
  );
}

const SHOWN = new Set([
  "verdict", "confidence", "reasoning", "flagged_phrases", "description", "response_preview",
  "response", "arguments", "requested_scope", "other_flagged_tools", "engine", "skipped",
  "z_score", "new_keys", "structural_anomaly", "mean_length", "statistical_anomaly",
  "calls_observed", "transport", "url", "case_id", "case_decision", "round_trip_ms",
  "inspector_latency_ms", "note", "tools", "selected", "source", "endpoint", "decision",
  "refusal", "reason", "static", "final_decision", "tool", "engines", "anomalous",
  "approved_scope",
]);

function Detail({ stage, detail, message }) {
  const phrases = detail.flagged_phrases || detail.static?.flagged_phrases || [];
  const rest = Object.fromEntries(Object.entries(detail).filter(([k]) => !SHOWN.has(k)));
  return (
    <div className="detail">
      {detail.verdict && <Confidence verdict={detail.verdict} value={detail.confidence} />}
      {detail.reasoning && <p className="reasoning">{detail.reasoning}</p>}
      {stage === "behavioral_check" && <p className="reasoning">{message}</p>}
      {phrases.length > 0 && (
        <Row label="Flagged phrases">
          <div className="chips">
            {phrases.map((p, i) => (
              <code key={i} className="chip">{p}</code>
            ))}
          </div>
        </Row>
      )}
      {detail.description && (
        <Row label="Tool description (as served)">
          <pre className="quote">
            <Highlighted text={detail.description.trim()} phrases={phrases} />
          </pre>
        </Row>
      )}
      {detail.static && (
        <Row label="Static verdict">
          <Confidence verdict={detail.static.verdict} value={detail.static.confidence} />
          <p className="reasoning">{detail.static.reasoning}</p>
        </Row>
      )}
      {(detail.response_preview || detail.response) && (
        <Row label="Tool response">
          <pre className="quote">
            <Highlighted text={detail.response_preview || detail.response} phrases={phrases} />
          </pre>
        </Row>
      )}
      {detail.arguments && (
        <Row label="Arguments">
          <pre className="quote small">{JSON.stringify(detail.arguments, null, 2)}</pre>
        </Row>
      )}
      {detail.z_score !== undefined && (
        <Row label="Fingerprint">
          z-score <b>{detail.z_score}</b> · calls observed <b>{detail.calls_observed}</b>
          {detail.new_keys?.length > 0 && <> · new keys <code>{detail.new_keys.join(", ")}</code></>}
          {detail.statistical_anomaly !== undefined && (
            <> · statistics say <b>{detail.statistical_anomaly ? "anomalous" : "normal"}</b></>
          )}
        </Row>
      )}
      {detail.transport && (
        <Row label="A2A hop">
          {detail.transport} → <code>{detail.url}</code>
          <br />
          case <code>{detail.case_id}</code> recorded as <b>{detail.case_decision}</b>
          {detail.round_trip_ms != null && <> · {detail.round_trip_ms} ms round trip</>}
        </Row>
      )}
      {detail.requested_scope && <Row label="Requested scope">{detail.requested_scope}</Row>}
      {detail.approved_scope && <Row label="Approved scope">{detail.approved_scope}</Row>}
      {detail.other_flagged_tools?.length > 0 && (
        <Row label="Other flagged tools on this server">{detail.other_flagged_tools.join(", ")}</Row>
      )}
      {detail.tools && <Row label="Tools">{detail.tools.join(", ")}</Row>}
      {detail.refusal && <Row label="Returned to the agent instead">{detail.refusal}</Row>}
      {detail.reason && <Row label="Why">{detail.reason}</Row>}
      {detail.note && <Row label="Note">{detail.note}</Row>}
      {detail.inspector_latency_ms !== undefined && (
        <Row label="Inspector latency">{detail.inspector_latency_ms} ms</Row>
      )}
      {detail.endpoint && <Row label="Endpoint">{detail.endpoint} ({detail.source})</Row>}
      {Object.keys(rest).length > 0 && (
        <details className="raw">
          <summary>Raw detail</summary>
          <pre>{JSON.stringify(rest, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}

export default function StageCard({ title, subtitle, state, onApprove }) {
  const { status, message, detail = {}, engine, elapsed_ms: elapsed, stage } = state;
  // null = follow the default (auto-open anything that was caught); a click pins it.
  const [open, setOpen] = useState(null);
  const resolved = !["pending", "active"].includes(status);
  const hasDetail = resolved && Object.keys(detail).length > 0;
  const autoOpen = ["flagged", "blocked", "escalate"].includes(status);
  const expanded = open ?? autoOpen;

  return (
    <li className={`stage ${status}`}>
      <div className="stage-rail">
        <span className={`stage-icon ${status}`} aria-hidden="true">
          {ICONS[status]}
        </span>
      </div>
      <div className="stage-body">
        <button
          type="button"
          className="stage-head"
          onClick={() => hasDetail && setOpen(!expanded)}
          disabled={!hasDetail}
          aria-expanded={expanded}
        >
          <span className="stage-title">{title}</span>
          <span className="stage-meta">
            {engine && engine !== "none" && (
              <span className={`engine ${engine}`}>{ENGINE_LABEL[engine] || engine}</span>
            )}
            {resolved && elapsed > 0 && <span className="muted">{Math.round(elapsed)} ms</span>}
            {hasDetail && <span className="chevron">{expanded ? "▾" : "▸"}</span>}
          </span>
        </button>
        <p className="stage-message">{message || subtitle}</p>
        {status === "escalate" && (
          <div className="approval">
            <span>Human-in-the-loop: allow this to proceed?</span>
            <button type="button" className="approve" onClick={() => onApprove(true)}>
              Approve
            </button>
            <button type="button" className="deny" onClick={() => onApprove(false)}>
              Deny
            </button>
          </div>
        )}
        {expanded && hasDetail && <Detail stage={stage} detail={detail} message={message} />}
      </div>
    </li>
  );
}
