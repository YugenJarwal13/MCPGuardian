import ConsolePanel from "./ConsolePanel.jsx";
import { Alert } from "./Icons.jsx";
import PipelineScene, { SceneNarration } from "./PipelineScene.jsx";
import PipelineView, { foldEvents } from "./PipelineView.jsx";
import { Highlighted } from "./StageCard.jsx";
import VerdictBanner from "./VerdictBanner.jsx";

/** A human decision is needed: shown right under the animation, not buried in a card. */
function ApprovalPanel({ fold, onApprove }) {
  const s = Object.values(fold).find((x) => x.status === "escalate");
  if (!s) return null;
  const d = s.detail || {};
  const why = d.reason || (d.anomalous ? "The behaviour layer saw this tool change." : s.message);
  return (
    <div className="decision approval" role="group" aria-label="Human decision required">
      <h4><Alert width={16} height={16} style={{ verticalAlign: -3 }} /> Your decision</h4>
      <p>{why} {d.requested_scope && <>This tool can reach <b>{String(d.requested_scope).replace("_", " ")}</b>.</>} Nothing runs, and nothing reaches the agent, until you choose.</p>
      <div className="row">
        <button type="button" className="btn primary" onClick={() => onApprove(true)}>Approve</button>
        <button type="button" className="btn danger" onClick={() => onApprove(false)}>Deny</button>
      </div>
    </div>
  );
}

/** "Without Guardian" vs "With Guardian": what the agent would have trusted, and what it actually got. */
function Compare({ fold, done }) {
  const st = fold.static_check;
  const rt = fold.runtime_check;
  const tc = fold.tool_call;
  const d = done.detail || {};
  if (d.inspect_only) return null;
  const staticBad = ["flagged", "blocked"].includes(st.status);
  const runtimeBad = rt.status === "flagged";
  if (!staticBad && !runtimeBad) return null;
  const phrases = [...(st.detail.flagged_phrases || []), ...(rt.detail.flagged_phrases || [])];
  const released = d.final_decision === "allow" || d.final_decision === "escalate_approved";
  const agentGot = released ? (d.response || "(the tool's response)")
    : tc.detail?.refusal || "A safe refusal: “This request was blocked by MCP Guardian.” No poisoned content was passed on.";
  return (
    <div className="compare">
      <div className="cmp without">
        <h4>Without Guardian, the agent would have trusted</h4>
        {staticBad && <pre><Highlighted text={(st.detail.description || "").trim()} phrases={phrases} /></pre>}
        {runtimeBad && <pre style={{ marginTop: staticBad ? 10 : 0 }}><Highlighted text={(rt.detail.response_preview || "").trim()} phrases={phrases} /></pre>}
      </div>
      <div className="cmp with">
        <h4>With Guardian, the agent received</h4>
        <pre>{agentGot}</pre>
      </div>
    </div>
  );
}

/** Everything a run shows: animation, plain-English narration, decision, backend console, technical cards. */
export default function RunView({ events, running, onApprove, serverName, notRun = [], showCompare = true }) {
  const fold = foldEvents(events);
  const done = [...events].reverse().find((e) => e.stage === "done");
  return (
    <div className="stack-lg">
      <PipelineScene events={events} serverName={serverName} notRun={notRun} />
      <SceneNarration events={events} />
      <ApprovalPanel fold={fold} onApprove={onApprove} />
      {done && <VerdictBanner done={done} />}
      {done && showCompare && <Compare fold={fold} done={done} />}
      <ConsolePanel events={events} running={running} />
      <details className="under-hood">
        <summary>Under the hood: every stage in detail</summary>
        <div><PipelineView events={events} onApprove={onApprove} notRun={notRun} /></div>
      </details>
    </div>
  );
}
