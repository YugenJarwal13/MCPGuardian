import StageCard from "./StageCard.jsx";

// The fixed pipeline, rendered upfront so the whole path is visible before a run starts.
export const STAGES = [
  ["connect", "Connect", "Open the MCP session"],
  ["list_tools", "List tools", "tools/list — the metadata the agent will trust"],
  ["static_check", "Static check", "CrewAI inspects the tool descriptions before any call"],
  ["tool_call", "Policy gate & tool call", "Enforce the policy, then run the call on the real server"],
  ["runtime_check", "Runtime check", "CrewAI inspects the live response for injected instructions"],
  ["behavioral_check", "Behavioural check", "Google ADK: fingerprint drift and rug-pull detection"],
  ["a2a_hop", "A2A hop", "The verdict travels to the ADK case manager over A2A"],
  ["enforcement", "Enforcement", "Allow, block, or ask a human"],
  ["done", "Verdict", "What the agent finally receives"],
];

/** Fold the event stream into one display state per stage. */
export function foldEvents(events) {
  const state = Object.fromEntries(STAGES.map(([id]) => [id, { stage: id, status: "pending", detail: {} }]));
  for (const ev of events) {
    if (!state[ev.stage]) continue;
    const prev = state[ev.stage];
    if (ev.status === "started") {
      state[ev.stage] = { ...prev, stage: ev.stage, status: "active", message: ev.message, startedAt: prev.startedAt ?? ev._t,
        detail: prev.detail, engine: undefined };
    } else {
      const richer = Object.keys(ev.detail || {}).length ? ev.detail : prev.detail;
      state[ev.stage] = {
        ...prev, ...ev, detail: richer || {}, startedAt: prev.startedAt,
        // keep the model that produced the verdict across a later approval event on the same stage
        engine: ev.engine && ev.engine !== "none" ? ev.engine : prev.engine,
        provider: ev.provider || prev.provider, model: ev.model || prev.model,
      };
    }
  }
  return state;
}

/**
 * Renders the live pipeline. `notRun` lists stages deliberately not executed (e.g. an
 * inspection-only run), which are shown as skipped rather than pending forever.
 */
export default function PipelineView({ events, onApprove, notRun = [] }) {
  const state = foldEvents(events);
  return (
    <ol className="pipeline" aria-label="Guardian pipeline">
      {STAGES.map(([id, title, subtitle], i) => {
        const s = notRun.includes(id) && state[id].status === "pending"
          ? { ...state[id], status: "skipped", message: "Not run in this mode." } : state[id];
        return <StageCard key={id} index={i} title={title} subtitle={subtitle} state={s} onApprove={onApprove} />;
      })}
    </ol>
  );
}
