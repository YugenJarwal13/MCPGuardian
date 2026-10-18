import { useEffect, useState } from "react";

// Tiny hash router: "#/" is the live demo, "#/test-live" is "Test a MCP server LIVE".
export const ROUTES = { demo: "#/", testLive: "#/test-live" };

function current() {
  return window.location.hash === ROUTES.testLive ? "testLive" : "demo";
}

export function useRoute() {
  const [route, setRoute] = useState(current);
  useEffect(() => {
    const onHash = () => setRoute(current());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  return route;
}
