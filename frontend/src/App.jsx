import { useEffect, useState } from "react";
import { fetchHealth, getAccessKey, setAccessKey } from "./api.js";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import NavBar from "./components/NavBar.jsx";
import { SketchDefs } from "./components/Sketch.jsx";
import DemoPage from "./pages/DemoPage.jsx";
import HomePage from "./pages/HomePage.jsx";
import TestLivePage from "./pages/TestLivePage.jsx";
import { useRoute } from "./router.js";
import { useTheme } from "./theme.js";

export default function App() {
  const { route, section } = useRoute();
  const { theme, toggle } = useTheme();
  const [health, setHealth] = useState(null);
  const [keyDraft, setKeyDraft] = useState("");
  const [hasKey, setHasKey] = useState(!!getAccessKey());

  useEffect(() => {
    const onRejected = () => { setHasKey(false); setKeyDraft(""); };
    window.addEventListener("guardian-key-rejected", onRejected);
    return () => window.removeEventListener("guardian-key-rejected", onRejected);
  }, []);

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => setHealth({ llm: { available: false } }));
  }, []);

  // a new page starts at the top (the landing page handles its own section scrolling)
  useEffect(() => {
    if (route !== "home") window.scrollTo({ top: 0 });
  }, [route]);

  return (
    <>
      <SketchDefs />
      <NavBar route={route} section={section} health={health} theme={theme} onToggleTheme={toggle} />
      {health?.access_required && !hasKey && (
        <form className="wrap" style={{ paddingTop: 14 }} onSubmit={(e) => { e.preventDefault(); if (keyDraft.trim()) { setAccessKey(keyDraft.trim()); setHasKey(true); } }}>
          <div className="notice warn row" style={{ gap: 12 }}>
            <span>This site needs an access key to run checks.</span>
            <input className="input" type="password" autoComplete="off" value={keyDraft} onChange={(e) => setKeyDraft(e.target.value)}
              placeholder="access key" aria-label="Access key" style={{ maxWidth: 260 }} />
            <button type="submit" className="btn primary">Use key</button>
          </div>
        </form>
      )}
      <ErrorBoundary key={route}>
        {route === "testLive" ? <TestLivePage health={health} />
          : route === "demo" ? <DemoPage health={health} />
          : <HomePage section={section} />}
      </ErrorBoundary>
    </>
  );
}
