import { useEffect, useRef } from "react";
import { consoleLine } from "../narration.js";

/**
 * A terminal view of the backend: one line per event the pipeline emitted (the same events the
 * audit trail records), with its timing, model and verdict fields. Auto-scrolls while a run is live.
 */
export default function ConsolePanel({ events, running }) {
  const box = useRef(null);
  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [events.length]);
  return (
    <section className="term" aria-label="Backend console">
      <header className="term-bar">
        <span className="tl r" /><span className="tl y" /><span className="tl g" />
        <span className="term-title">guardian · backend events{events[0]?.trace_id ? ` · trace ${events[0].trace_id.slice(0, 12)}` : ""}</span>
        <span className="term-live">{running ? <><i className="live-pip" /> live</> : events.length ? "finished" : "idle"}</span>
      </header>
      <div className="term-body" ref={box} tabIndex={0}>
        {events.length === 0 && <div className="term-line dim">$ waiting for a run. Every backend step is printed here.</div>}
        {events.map((ev, i) => {
          const l = consoleLine(ev);
          return (
            <div key={i} className={`term-line s-${l.status}`}>
              <span className="t-time">{l.time}</span>
              <span className="t-stage">{l.stage}</span>
              <span className={`t-status ${l.status}`}>{l.status}</span>
              <span className="t-msg">{l.message}</span>
              {l.extra && <span className="t-extra">{l.extra}</span>}
              {l.phrases.length > 0 && <span className="t-phr">flagged: {l.phrases.slice(0, 3).map((p) => `“${p}”`).join(" ")}</span>}
            </div>
          );
        })}
        {running && <div className="term-line dim"><span className="caret-t" /></div>}
      </div>
    </section>
  );
}
