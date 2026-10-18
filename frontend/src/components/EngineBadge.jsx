const shortModel = (m) => (m ? m.split("/").pop().replace(/:free$/, "") : "");

/** Which engine decided: the LLM (and which model), the heuristic, or a degraded path. */
export default function EngineBadge({ engine, provider, model, method, cached }) {
  if (!engine || engine === "none") return null;
  const title = [provider && `provider: ${provider}`, model && `model: ${model}`, method && `method: ${method}`,
    cached && "answer served from the local cache"].filter(Boolean).join("\n");
  if (engine === "llm") {
    return (
      <span className="badge llm" title={title}>
        <span>LLM</span>
        {model && <span className="m">{shortModel(model)}</span>}
        {cached && <span aria-label="cached">· cached</span>}
      </span>
    );
  }
  if (engine === "heuristic_fallback") return <span className="badge warn" title="The model call failed; the regex heuristic answered instead.">LLM failed → heuristic</span>;
  if (engine === "timeout") return <span className="badge warn" title="The model did not answer in time; the call is escalated to a human.">LLM timed out → escalate</span>;
  return <span className="badge" title="Deterministic regex / statistics, no model call.">heuristic</span>;
}
