import StageCard from "./StageCard.jsx";

// Fixed pipeline, rendered upfront so the whole path is visible before a run.
export const STAGES = [
  ["connect", "Connect", "Open the MCP session"],
  ["list_tools", "List tools", "tools/list — the metadata the agent will trust"],
  ["static_check", "Static check · CrewAI", "Inspect tool descriptions before any call"],
  ["tool_call", "Policy gate & tool call", "Enforce, then execute on the real server"],
  ["runtime_check", "Runtime check · CrewAI", "Inspect the live response for injected instructions"],
  ["behavioral_check", "Behavioural check · ADK", "Fingerprint drift / rug-pull detection"],
  ["a2a_hop", "A2A hop", "CrewAI verdict → A2A → ADK case manager"],
  ["enforcement", "Enforcement", "Allow, block, or ask a human"],
  ["done", "Verdict", "What the agent finally receives"],
];

/** Fold the event stream into one display state per stage. */
export function foldEvents(events) {
  const state = Object.fromEntries(STAGES.map(([id]) => [id, { stage: id, status: "pending" }]));
  for (const ev of events) {
    const prev = state[ev.stage] || {};
    if (ev.status === "started") {
      state[ev.stage] = { ...prev, stage: ev.stage, status: "active", message: ev.message,
        detail: {}, engine: ev.engine };
    } else {
      state[ev.stage] = { ...prev, ...ev,
        // keep the richest detail seen for this stage (a later "passed" after an
        // approval should not wipe the verdict that caused the escalation)
        detail: Object.keys(ev.detail || {}).length ? ev.detail : prev.detail || {},
        engine: ev.engine !== "none" ? ev.engine : prev.engine };
    }
  }
  return state;
}

export default function PipelineView({ events, onApprove }) {
  const state = foldEvents(events);
  return (
    <ol className="pipeline">
      {STAGES.map(([id, title, subtitle]) => (
        <StageCard key={id} title={title} subtitle={subtitle} state={state[id]} onApprove={onApprove} />
      ))}
    </ol>
  );
}
