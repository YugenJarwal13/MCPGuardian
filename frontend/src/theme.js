import { useCallback, useEffect, useState } from "react";

// Light is the default. The choice persists in localStorage; index.html applies it
// before first paint so a dark-theme user never sees a light flash on refresh.
const KEY = "guardian-theme";

export function readStoredTheme() {
  try {
    const t = localStorage.getItem(KEY);
    if (t === "dark" || t === "light") return t;
  } catch {
    /* storage unavailable (private mode) — fall back to light */
  }
  return "light";
}

export function useTheme() {
  const [theme, setTheme] = useState(readStoredTheme);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try {
      localStorage.setItem(KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);
  const toggle = useCallback(() => setTheme((t) => (t === "dark" ? "light" : "dark")), []);
  return { theme, toggle };
}
