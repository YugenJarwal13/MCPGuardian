import { useEffect, useState } from "react";

const fmt = (ms) => (ms < 1000 ? `${Math.round(ms)} ms` : `${(ms / 1000).toFixed(ms < 10000 ? 1 : 0)} s`);

/** Live while a stage is active (ticks from when its `started` event arrived), then the server's final time. */
export default function ElapsedTimer({ active, startedAt, finalMs }) {
  const [now, setNow] = useState(() => performance.now());
  useEffect(() => {
    if (!active) return undefined;
    const id = setInterval(() => setNow(performance.now()), 100);
    return () => clearInterval(id);
  }, [active]);
  if (active && startedAt) return <span className="timer live">{fmt(now - startedAt)}</span>;
  if (!active && finalMs > 0) return <span className="timer">{fmt(finalMs)}</span>;
  return null;
}
