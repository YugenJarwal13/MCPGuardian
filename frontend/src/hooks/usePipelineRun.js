import { useCallback, useEffect, useRef, useState } from "react";
import { startRun } from "../api.js";

// Minimum time (ms) a step stays on screen, so a stage the backend finishes in 2 ms is still
// visible to a human. A slow stage (an LLM call) is never delayed: its result is shown the
// moment it arrives. If the queue backs up the pace speeds up, so the UI never lags far behind.
const DWELL_STARTED = 650;
const DWELL_RESULT = 900;
const DWELL_FAST = 160;

/**
 * Owns one live pipeline run over the WebSocket. Both pages use it, so the demo and
 * "Check a server" render the exact same event stream.
 *
 * `events` are the events that have been *revealed* to the UI (a paced view of the real stream);
 * every event is real backend output — pacing only controls when it becomes visible. Human
 * decisions (status "escalate") and terminal events are never delayed.
 */
export function usePipelineRun() {
  const [events, setEvents] = useState([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const handle = useRef(null);
  const queue = useRef([]);
  const timer = useRef(null);
  const closed = useRef(true);
  const lastShown = useRef(0);

  const drain = useCallback(() => {
    if (timer.current) return;
    const next = () => {
      timer.current = null;
      const ev = queue.current.shift();
      if (!ev) {
        if (closed.current) setRunning(false);
        return;
      }
      lastShown.current = performance.now();
      setEvents((prev) => [...prev, { ...ev, _t: lastShown.current }]);
      const urgent = ev.status === "escalate";
      const dwell = queue.current.length > 5 ? DWELL_FAST : ev.status === "started" ? DWELL_STARTED : DWELL_RESULT;
      timer.current = setTimeout(next, urgent ? 0 : dwell);
    };
    // first event: show immediately; later ones respect the dwell since the last reveal
    const wait = Math.max(0, DWELL_STARTED - (performance.now() - lastShown.current));
    timer.current = setTimeout(next, queue.current.length > 5 ? 0 : Math.min(wait, DWELL_STARTED));
  }, []);

  const stop = useCallback(() => {
    handle.current?.close();
    handle.current = null;
    clearTimeout(timer.current);
    timer.current = null;
    queue.current = [];
  }, []);

  useEffect(() => stop, [stop]); // close the socket on unmount

  const start = useCallback(
    (request) => {
      stop();
      setEvents([]);
      setError(null);
      setRunning(true);
      closed.current = false;
      lastShown.current = 0;
      handle.current = startRun(request, {
        onEvent: (ev) => {
          queue.current.push(ev);
          drain();
        },
        onClose: () => {
          closed.current = true;
          if (!queue.current.length && !timer.current) setRunning(false);
        },
        onError: (e) => {
          setError(e.message);
          closed.current = true;
          setRunning(false);
        },
      });
    },
    [stop, drain]
  );

  const approve = useCallback((ok) => handle.current?.approve(ok), []);
  const reset = useCallback(() => {
    stop();
    closed.current = true;
    setEvents([]);
    setError(null);
    setRunning(false);
  }, [stop]);

  return { events, running, error, start, approve, reset };
}
