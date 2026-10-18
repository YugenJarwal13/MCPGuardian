import { Alert, Check, Cross, Question } from "./Icons.jsx";

const COPY = {
  allow: ["ALLOW", "The response was delivered to the agent.", Check, "allow"],
  block: ["BLOCK", "Nothing malicious reached the agent.", Cross, "block"],
  escalate_approved: ["ALLOWED by a human", "A reviewer approved it; the response was released.", Question, "escalate"],
  escalate_denied: ["BLOCK — denied by a human", "A reviewer withheld the response.", Cross, "block"],
};

const short = (m) => (m ? m.split("/").pop().replace(/:free$/, "") : "?");

export default function VerdictBanner({ done }) {
  if (!done) return null;
  if (done.status === "error") {
    return (
      <div className="verdict error" role="alert">
        <span className="v-icon"><Cross /></span>
        <div><div className="v-title">Run failed</div><div className="v-sub">{done.message}</div></div>
      </div>
    );
  }
  if (done.detail?.inspect_only) {
    const tools = done.detail.tools || [];
    const flagged = tools.filter((t) => t.verdict !== "clean").length;
    return (
      <div className={`verdict ${flagged ? "escalate" : "allow"}`} role="status">
        <span className="v-icon">{flagged ? <Alert /> : <Check />}</span>
        <div>
          <div className="v-title">{flagged ? `${flagged} of ${tools.length} tools flagged` : `All ${tools.length} tools look clean`}</div>
          <div className="v-sub">Static inspection only — no tool was called.</div>
        </div>
      </div>
    );
  }
  const final = done.detail?.final_decision || "allow";
  const [title, sub, Icon, tone] = COPY[final] || [done.message, "", Check, "info"];
  const models = Object.entries(done.detail?.models || {}).filter(([, v]) => v);
  return (
    <div className={`verdict ${tone}`} role="status">
      <span className="v-icon"><Icon /></span>
      <div><div className="v-title">{title}</div><div className="v-sub">{sub}</div></div>
      <span className="v-models">
        {models.length ? models.map(([k, v]) => `${k}: ${short(v)}`).join(" · ")
          : "engines: " + Object.entries(done.detail?.engines || {}).map(([k, v]) => `${k}=${v}`).join(" · ")}
      </span>
    </div>
  );
}
