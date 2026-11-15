import { useEffect, useState } from "react";
import Modal from "./Modal.jsx";

/**
 * Tells the visitor when the AI inspector could not be used, instead of leaving them to notice a small badge:
 *  - the site's daily budget of AI runs is spent (the run is refused), or
 *  - the model did not answer during the run (free-tier limit or provider error) and the regex checks answered.
 * Shown once per run.
 */
export default function ModelNotice({ events }) {
  const [seen, setSeen] = useState(null);
  const first = events[0]?._t ?? null;
  const refused = events.find((e) => e.detail?.guard === "budget");
  const fellBack = events.some((e) => e.engine === "heuristic_fallback");
  const kind = refused ? "budget" : fellBack ? "fallback" : null;

  useEffect(() => { if (!events.length) setSeen(null); }, [events.length]);
  if (!kind || seen === first) return null;

  return (
    <Modal open eyebrow="AI inspector unavailable" onClose={() => setSeen(first)}
      title={kind === "budget" ? "Today's AI runs are used up" : "The AI model did not answer"}
      footer={<button type="button" className="btn primary" data-autofocus onClick={() => setSeen(first)}>OK</button>}>
      {kind === "budget" ? (
        <p>This site shares a daily allowance of AI-inspector runs, and it has been used. It resets at 00:00 UTC (05:30 in India). Please try again then.</p>
      ) : (
        <>
          <p>The free AI model is out of requests for today, or did not respond. For the steps it could not answer, Guardian switched to its built-in regex checks and finished the run.</p>
          <p className="muted">Regex checks are weaker: they catch obvious attack phrases but miss many disguised ones. Steps marked “LLM failed → heuristic” used them.</p>
        </>
      )}
    </Modal>
  );
}
