const COPY = {
  allow: ["ALLOW", "The response was delivered to the agent."],
  block: ["BLOCK", "Nothing malicious reached the agent."],
  escalate_approved: ["ESCALATE → approved", "A human reviewed and released it."],
  escalate_denied: ["ESCALATE → denied", "A human reviewed and withheld it."],
};

export default function VerdictBanner({ done }) {
  if (!done) return null;
  if (done.status === "error") {
    return (
      <div className="verdict error" role="alert">
        <strong>Run failed</strong>
        <span>{done.message}</span>
      </div>
    );
  }
  const final = done.detail?.final_decision || "allow";
  const [title, sub] = COPY[final] || [done.message, ""];
  const tone = final === "allow" ? "allow" : final.startsWith("escalate") ? "escalate" : "block";
  const engines = done.detail?.engines || {};
  return (
    <div className={`verdict ${tone}`} role="status">
      <strong>{title}</strong>
      <span>{sub}</span>
      {Object.keys(engines).length > 0 && (
        <span className="muted engines-used">
          engines: {Object.entries(engines).map(([k, v]) => `${k}=${v}`).join(" · ")}
        </span>
      )}
    </div>
  );
}
