import { Cpu } from "./Icons.jsx";

const PROVIDERS = { openrouter: "OpenRouter", ollama: "Ollama (local)" };

/** "nvidia/nemotron-3.5-lightning:free" -> "Nemotron 3.5 Lightning" */
export function prettyModel(slug) {
  if (!slug) return "";
  const base = slug.split("/").pop().replace(/:free$/, "");
  return base
    .split("-")
    .map((part) => (/^[0-9.]+b?$/i.test(part) ? part : part.charAt(0).toUpperCase() + part.slice(1)))
    .join(" ");
}

/** Which model is answering right now, as a small status pill for the nav bar. */
export default function LlmStatus({ health }) {
  if (health == null) {
    return <span className="llm-pill is-wait"><span className="dot" />Connecting…</span>;
  }
  const chain = health.llm?.chain || [];
  const usable = chain.filter((c) => c.usable);
  const primary = usable[0];
  if (!health.llm?.available || !primary) {
    return (
      <span className="llm-pill is-off" title="No language model is reachable. Check the backend's OpenRouter settings.">
        <span className="dot" />AI model offline
      </span>
    );
  }
  const title = chain
    .map((c) => `${c.usable ? "●" : "○"} ${PROVIDERS[c.provider] || c.provider}: ${prettyModel(c.model)} (${c.method})`)
    .join("\n");
  return (
    <span className="llm-pill is-on" title={title}>
      <span className="dot" />
      <Cpu width={14} height={14} />
      <span className="llm-name">{prettyModel(primary.model)}</span>
      <span className="llm-via">{PROVIDERS[primary.provider] || primary.provider}</span>
      {usable.length > 1 && <span className="llm-more">+{usable.length - 1}</span>}
    </span>
  );
}
