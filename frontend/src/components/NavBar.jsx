import { ROUTES } from "../router.js";
import { Shield } from "./Icons.jsx";
import ThemeToggle from "./ThemeToggle.jsx";

const short = (m) => (m ? m.split("/").pop().replace(/:free$/, "") : "");

export default function NavBar({ route, health, theme, onToggleTheme }) {
  const llm = health?.llm;
  const primary = llm?.chain?.find((c) => c.usable);
  return (
    <header className="nav">
      <div className="nav-inner">
        <a className="brand" href={ROUTES.demo}><Shield /> MCP Guardian</a>
        <nav className="nav-links" aria-label="Pages">
          <a className="nav-link" href={ROUTES.demo} aria-current={route === "demo" ? "page" : undefined}>Live demo</a>
          <a className="nav-link" href={ROUTES.testLive} aria-current={route === "testLive" ? "page" : undefined}>Test a server live</a>
        </nav>
        <div className="nav-right">
          <span className={`pill hide-sm ${health == null ? "" : llm?.available ? "ok" : "warn"}`}
            title={llm?.chain?.map((c) => `${c.provider}: ${c.model} (${c.method})`).join("\n")}>
            <span className="dot" />
            {health == null ? "connecting…" : llm?.available ? `${primary?.provider ?? "LLM"} · ${short(primary?.model)}` : "no LLM — heuristic mode"}
          </span>
          {health?.a2a_url && <span className="pill ok hide-sm"><span className="dot" />A2A {health.a2a_url.replace("http://", "")}</span>}
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        </div>
      </div>
    </header>
  );
}
