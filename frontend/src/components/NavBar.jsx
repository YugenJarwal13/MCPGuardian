import { ROUTES } from "../router.js";
import { Github, Shield } from "./Icons.jsx";
import LlmStatus from "./LlmStatus.jsx";
import ThemeToggle from "./ThemeToggle.jsx";

const REPO = "https://github.com/YugenJarwal13/MCPGuardian";

export default function NavBar({ route, section, health, theme, onToggleTheme }) {
  const cur = (r, s = null) => (route === r && (route !== "home" || section === s) ? "page" : undefined);
  return (
    <header className="nav">
      <div className="nav-inner">
        <a className="brand" href={ROUTES.home}>
          <span className="brand-mark"><Shield /></span> MCP Guardian
        </a>
        <nav className="nav-links" aria-label="Pages">
          <a className="nav-link" href={ROUTES.home} aria-current={cur("home")}>Overview</a>
          <a className="nav-link" href={ROUTES.results} aria-current={cur("home", "results")}>Results</a>
          <a className="nav-link" href={ROUTES.demo} aria-current={cur("demo")}>Live demo</a>
          <a className="nav-link" href={ROUTES.testLive} aria-current={cur("testLive")}>Check a server</a>
        </nav>
        <div className="nav-right">
          <span className="hide-sm"><LlmStatus health={health} /></span>
          <a className="icon-btn" href={REPO} target="_blank" rel="noreferrer" aria-label="Source on GitHub" title="Source on GitHub"><Github /></a>
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
          <a className="btn primary nav-cta" href={ROUTES.demo}>Watch it live</a>
        </div>
      </div>
    </header>
  );
}
