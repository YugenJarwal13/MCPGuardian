import { Highlighted } from "./StageCard.jsx";

const W = 320;
const H = 120;

/** Response size per call, with the call where a new field first appeared marked. */
function Bars({ history, flagged }) {
  const max = Math.max(...history.map((h) => h.length), 1);
  const slot = W / history.length;
  const seen = new Set();
  return (
    <svg viewBox={`0 0 ${W} ${H + 26}`} className="drift-svg" role="img" aria-label="Response size for each call">
      {history.map((h, i) => {
        const fresh = h.keys.filter((k) => !seen.has(k));
        const isNew = i > 0 && fresh.length > 0;
        h.keys.forEach((k) => seen.add(k));
        const bh = Math.max(6, (h.length / max) * H);
        const last = i === history.length - 1;
        const bad = isNew || (last && flagged);
        return (
          <g key={h.n}>
            <rect x={i * slot + slot * 0.18} y={H - bh} width={slot * 0.64} height={bh} rx="4"
              className={bad ? "bar-bad" : "bar-ok"} />
            {isNew && <text x={i * slot + slot / 2} y={H - bh - 6} textAnchor="middle" className="bar-flag">+ {fresh[0]}</text>}
            <text x={i * slot + slot / 2} y={H + 16} textAnchor="middle" className="bar-n">{h.n}</text>
          </g>
        );
      })}
    </svg>
  );
}

/** Rug-pull view: how the tool's responses changed over its calls. */
export default function DriftPanel({ detail, flagged }) {
  const history = detail?.history || [];
  if (history.length < 2) return null;
  const newKeys = detail.new_keys || [];
  return (
    <section className="drift" aria-label="Behaviour over time">
      <div className="drift-head">
        <h3>Behaviour over time</h3>
        <span className={`vpill ${flagged ? "malicious" : "clean"}`}>{flagged ? "changed" : "steady"}</span>
      </div>
      <p className="muted">Size of the tool's response on each call. Guardian keeps a running profile of every tool and compares each new
        response with it (length, and which fields appear).</p>
      <div className="drift-grid">
        <div>
          <Bars history={history} flagged={flagged} />
          <div className="drift-axis">call number</div>
        </div>
        <div className="drift-diff">
          {detail.previous_response && <><div className="dlabel">Previous call</div><pre className="quote">{detail.previous_response}</pre></>}
          {detail.response && <><div className="dlabel">This call</div>
            <pre className="quote"><Highlighted text={detail.response} phrases={newKeys} /></pre></>}
        </div>
      </div>
    </section>
  );
}
