// Turns the real backend events into plain-English narration for people who are not security
// engineers. Every number, name and quote below comes from the event stream; nothing is invented.

const pct = (c) => `${Math.round((c || 0) * 100)}%`;
const short = (m) => (m ? m.split("/").pop().replace(/:free$/, "") : "");
const q = (s, n = 90) => {
  const t = String(s || "").replace(/\s+/g, " ").trim();
  return `“${t.length > n ? `${t.slice(0, n)}…` : t}”`;
};

export function engineWord(ev) {
  if (!ev) return "";
  if (ev.engine === "llm") return `using the language model ${short(ev.model || ev.detail?.model)}`;
  if (ev.engine === "heuristic_fallback") return "the model failed, so the built-in regex rules answered";
  if (ev.engine === "timeout") return "the model did not answer in time, so Guardian escalates to a human";
  if (ev.engine === "heuristic") return "using Guardian's built-in regex rules";
  return "";
}

/** Short label for a station's second line: which engine decided. */
export function engineLabel(state) {
  if (!state) return "";
  if (state.engine === "llm") return short(state.model || state.detail?.model) || "LLM";
  if (state.engine === "heuristic") return "regex rules";
  if (state.engine === "heuristic_fallback") return "regex (LLM failed)";
  if (state.engine === "timeout") return "LLM timed out";
  return "";
}

/**
 * @param {object} fold   foldEvents(events) — one entry per stage
 * @param {object|null} last   the most recently revealed event
 * @returns {{title:string, body:string, tone:string, tech:string}}
 */
export function narrate(fold, last) {
  if (!last) {
    return { title: "Ready when you are", tone: "idle", tech: "",
      body: "Press the button and watch what happens between an AI agent and a tool server, one step at a time." };
  }
  const d = last.detail || {};
  const tool = d.selected || d.tool || "the tool";
  const tech = `${last.stage} · ${last.status}${last.engine && last.engine !== "none" ? ` · ${last.engine}` : ""}${last.elapsed_ms ? ` · ${Math.round(last.elapsed_ms)} ms` : ""}`;
  const mk = (title, body, tone = "info") => ({ title, body, tone, tech });
  const st = last.status;

  switch (last.stage) {
    case "connect":
      if (st === "started") return mk("Stepping in between", "Your agent wants to use a tool server. Instead of letting it connect directly, MCP Guardian opens the connection itself and stays in the middle of everything that follows.");
      if (st === "error" && d.guard) return mk(d.guard === "rate_limit" ? "Slow down a little" : "Input refused", last.message, "bad");
      if (st === "error") return mk("Could not reach the server", last.message, "bad");
      return mk("Connected", `Guardian is now talking to ${d.endpoint || "the server"}. The agent still hasn't seen anything.`, "ok");
    case "list_tools":
      if (st === "started") return mk("Asking: what tools do you offer?", "Every MCP server describes its tools in plain text: a name, a short manual, and the inputs it needs. An AI agent reads those descriptions and trusts them. That makes them the favourite hiding place for attacks.");
      if (st === "error") return mk("Tool not available", last.message, "bad");
      return mk(`${(d.tools || []).length} tool${(d.tools || []).length === 1 ? "" : "s"} on offer`,
        `The server handed over its tool descriptions${d.tools?.length ? `: ${d.tools.slice(0, 5).join(", ")}${d.tools.length > 5 ? "…" : ""}` : ""}. Before the agent is allowed to read any of them, Guardian reads them first.`, "ok");
    case "static_check":
      if (st === "started") return mk("Inspector 1 reads the fine print", `A CrewAI agent, the “MCP Tool Metadata Auditor”, reads each description like a security reviewer. It is looking for hidden orders aimed at the AI instead of at a human reader. ${last.message}`);
      if (st === "flagged") {
        const ph = d.flagged_phrases || [];
        return mk("Hidden instructions found", `The auditor (${engineWord(last) || "static analysis"}) marked “${tool}” as ${d.verdict}, ${pct(d.confidence)} confident. ${d.reasoning || ""}${ph.length ? ` It points at ${q(ph[0], 70)}.` : ""}`, "bad");
      }
      return mk("The descriptions look clean", `The auditor (${engineWord(last) || "static analysis"}) found no hidden orders in “${tool}”. ${d.reasoning ? `In its words: ${q(d.reasoning, 170)}` : ""}`, "ok");
    case "tool_call":
      if (st === "started" && /^Policy/.test(last.message)) return mk("Policy gate", "Before anything runs, Guardian applies its policy: poisoned tools are stopped outright, and tools that can touch passwords, files or the network need a human to say yes.");
      if (st === "started") return mk("Only now: the real call", `The call to “${tool}” is finally allowed through to the real server. The answer will be held back until it has been checked.`);
      if (st === "escalate") return mk("A human must decide", `${d.reason || last.message}${d.requested_scope ? ` This tool can reach ${String(d.requested_scope).replace("_", " ")}.` : ""} Nothing runs until you choose.`, "warn");
      if (st === "blocked") return mk("Stopped at the gate", `${d.refusal || last.message} The real server was never called.`, "bad");
      return mk("The tool answered", "The server replied. Guardian is holding that reply. The agent has not seen it yet.", "ok");
    case "runtime_check":
      if (st === "started") return mk("Inspector 2 reads the answer", "A second CrewAI agent, the “Response Auditor”, reads the reply. Facts and data are fine; commands hidden inside the data are not.");
      if (st === "flagged") return mk("A command was hiding in the answer", `${d.reasoning || last.message}`, "bad");
      return mk("The answer is ordinary data", d.reasoning ? `${q(d.reasoning, 200)}` : "No injected instruction found in the response.", "ok");
    case "behavioral_check":
      if (st === "started") return mk("Is this tool acting differently?", "Google ADK keeps a statistical fingerprint of how each tool normally behaves: how long its answers are, which fields it returns. A tool that earns trust and then changes (a “rug pull”) shows up as drift.");
      if (st === "flagged") return mk("This tool changed its behaviour", last.message, "bad");
      return mk("Behaves as usual", `${last.message}${d.z_score !== undefined ? ` (z-score ${d.z_score}, ${d.calls_observed} call${d.calls_observed === 1 ? "" : "s"} observed)` : ""}`, "ok");
    case "a2a_hop":
      if (st === "started") return mk("Reporting to the case manager", "The verdicts are packaged as an A2A (Agent-to-Agent) message and sent over the network to a separate Google ADK agent that keeps the case file.");
      if (st === "error") return mk("Case manager unreachable", last.message, "warn");
      return mk("Case filed", `Case ${d.case_id || ""} was recorded as “${d.case_decision}”${d.round_trip_ms != null ? ` in ${d.round_trip_ms} ms` : ""}.`, "ok");
    case "enforcement":
      if (st === "started") return mk("Making the final call", "Guardian combines every verdict: allow it, block it, or ask a human.");
      if (st === "escalate") return mk("A human must decide", "The response needs a human review before the agent may see it.", "warn");
      if (st === "blocked") return mk("Blocked", last.message, "bad");
      return mk("Allowed", last.message, "ok");
    case "done": {
      if (st === "error") return mk("The run stopped", last.message, "bad");
      if (d.inspect_only) {
        const tools = d.tools || [];
        const bad = tools.filter((t) => t.verdict !== "clean").length;
        return mk(bad ? `${bad} of ${tools.length} tools look dangerous` : `All ${tools.length} tools look clean`,
          bad ? "Guardian read every description on this server and found hidden instructions. No tool was called." : "Guardian read every description and found nothing suspicious. No tool was called.", bad ? "bad" : "ok");
      }
      const f = d.final_decision;
      if (f === "allow" || f === "escalate_approved") return mk("Safe: delivered to the agent", "Every check passed, so the agent received the response.", "ok");
      return mk("Blocked: the agent never saw it", "Guardian stopped the attack. The agent got a safe refusal instead of the poisoned content.", "bad");
    }
    default:
      return mk(last.stage, last.message);
  }
}

/** One terminal-style line per event, built from the real fields. */
export function consoleLine(ev) {
  const d = ev.detail || {};
  const bits = [];
  if (d.verdict) bits.push(`verdict=${d.verdict}`);
  if (d.confidence != null) bits.push(`conf=${Number(d.confidence).toFixed(2)}`);
  if (ev.engine && ev.engine !== "none") bits.push(`engine=${ev.engine}`);
  if (ev.model || d.model) bits.push(`model=${short(ev.model || d.model)}`);
  if (d.method) bits.push(`via=${d.method}`);
  if (d.model_latency_ms != null) bits.push(`llm=${(d.model_latency_ms / 1000).toFixed(1)}s`);
  if (d.cached) bits.push("cached");
  if (d.z_score !== undefined) bits.push(`z=${d.z_score}`);
  if (d.case_id) bits.push(`case=${d.case_id}`);
  if (d.round_trip_ms != null) bits.push(`a2a=${d.round_trip_ms}ms`);
  if (d.final_decision) bits.push(`decision=${d.final_decision}`);
  if (ev.elapsed_ms) bits.push(`${Math.round(ev.elapsed_ms)}ms`);
  let time = "";
  try {
    time = new Date(ev.timestamp).toLocaleTimeString([], { hour12: false }) + "." + String(new Date(ev.timestamp).getMilliseconds()).padStart(3, "0");
  } catch {
    time = "";
  }
  return { time, stage: ev.stage, status: ev.status, message: ev.message, extra: bits.join("  "), phrases: d.flagged_phrases || [] };
}
