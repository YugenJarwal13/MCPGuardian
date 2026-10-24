import { useEffect, useState } from "react";
import { fetchHealth } from "./api.js";
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
      <ErrorBoundary key={route}>
        {route === "testLive" ? <TestLivePage health={health} />
          : route === "demo" ? <DemoPage health={health} />
          : <HomePage section={section} />}
      </ErrorBoundary>
    </>
  );
}
