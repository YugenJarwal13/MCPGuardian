import { useEffect, useState } from "react";

// Tiny hash router. "#/" is the landing page, "#/results" the landing page scrolled to the results,
// "#/demo" the live demo and "#/test-live" the "check any MCP server" page.
export const ROUTES = {
  home: "#/",
  results: "#/results",
  demo: "#/demo",
  testLive: "#/test-live",
};

function parse() {
  const h = window.location.hash;
  if (h === ROUTES.demo) return { route: "demo", section: null };
  if (h === ROUTES.testLive) return { route: "testLive", section: null };
  if (h === ROUTES.results) return { route: "home", section: "results" };
  return { route: "home", section: null };
}

export function useRoute() {
  const [state, setState] = useState(parse);
  useEffect(() => {
    const onHash = () => setState(parse());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return state;
}
