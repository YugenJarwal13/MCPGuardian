import { useCallback, useState } from "react";

const KEY = "guardian-auto-follow";

/**
 * "Auto-follow": when a stage finishes, scroll the page to the next section so nobody has to hunt for it.
 * On by default; the choice is remembered per browser. `follow(element)` does nothing while it is off.
 */
export function useAutoFollow() {
  const [enabled, setEnabled] = useState(() => {
    try {
      return localStorage.getItem(KEY) !== "off";
    } catch {
      return true;
    }
  });

  const set = useCallback((on) => {
    setEnabled(on);
    try {
      localStorage.setItem(KEY, on ? "on" : "off");
    } catch {
      /* storage unavailable: the choice then lasts until reload */
    }
  }, []);

  const follow = useCallback((el) => {
    if (!enabled || !el) return;
    const calm = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    el.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
  }, [enabled]);

  return { enabled, setEnabled: set, follow };
}
