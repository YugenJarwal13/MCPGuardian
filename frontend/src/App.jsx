import { useEffect, useState } from "react";
import { fetchHealth } from "./api.js";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import NavBar from "./components/NavBar.jsx";
import DemoPage from "./pages/DemoPage.jsx";
import TestLivePage from "./pages/TestLivePage.jsx";
import { useRoute } from "./router.js";
import { useTheme } from "./theme.js";

export default function App() {
  const route = useRoute();
  const { theme, toggle } = useTheme();
  const [health, setHealth] = useState(null);

  useEffect(() => {
    fetchHealth().then(setHealth).catch(() => setHealth({ llm: { available: false } }));
  }, []);

  return (
    <>
      <NavBar route={route} health={health} theme={theme} onToggleTheme={toggle} />
      <ErrorBoundary key={route}>
        {route === "testLive" ? <TestLivePage health={health} /> : <DemoPage health={health} />}
      </ErrorBoundary>
    </>
  );
}
