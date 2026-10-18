import { useCallback, useEffect, useRef, useState } from "react";
import { startRun } from "../api.js";

/**
 * Owns one live pipeline run over the WebSocket. Both pages use it, so the demo and
 * "Test a server live" render the exact same event stream with the same PipelineView.
 * Each event is stamped with the local receive time (`_t`) so an active stage can show
 * a live elapsed timer.
 */
export function usePipelineRun() {
  const [events, setEvents] = useState([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);
  const handle = useRef(null);

  const stop = useCallback(() => {
    handle.current?.close();
    handle.current = null;
  }, []);

  useEffect(() => stop, [stop]); // close the socket on unmount

  const start = useCallback(
    (request) => {
      stop();
      setEvents([]);
      setError(null);
      setRunning(true);
      handle.current = startRun(request, {
        onEvent: (ev) => setEvents((prev) => [...prev, { ...ev, _t: performance.now() }]),
        onClose: () => setRunning(false),
        onError: (e) => {
          setError(e.message);
          setRunning(false);
        },
      });
    },
    [stop]
  );

  const approve = useCallback((ok) => handle.current?.approve(ok), []);
  const reset = useCallback(() => {
    stop();
    setEvents([]);
    setError(null);
    setRunning(false);
  }, [stop]);

  return { events, running, error, start, approve, reset };
}
