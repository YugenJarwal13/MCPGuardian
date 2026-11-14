import { useState } from "react";
import { Alert, Arrow, Check, Info } from "../components/Icons.jsx";
import E from "../data/agent_evals.json";
import R from "../data/results.json";

const pct = (x, d = 1) => (x == null ? "n/a" : `${(x * 100).toFixed(d)}%`);
const pc = (x) => (x == null ? "n/a" : `${x}%`);
const num = (x) => (x == null ? "n/a" : Number(x).toLocaleString());

function Tile({ value, label, tone }) {
  return <div className={`stat${tone === "bad" ? " bad" : ""}${tone === "ok" ? " good" : ""}`}><b>{value}</b><span>{label}</span></div>;
}

function Tbl({ head, rows, small }) {
  return (
    <div className="etable-wrap">
      <table className={`etable${small ? " small" : ""}`}>
        <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>{rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function How({ children }) {
  return <p className="how"><Info width={14} height={14} /> <span>{children}</span></p>;
}

function Verdict({ ok, children }) {
  return <span className={`vpill ${ok ? "clean" : "suspicious"}`}>{children}</span>;
}

const TABS = [
  ["overview", "Overview"],
  ["static", "Static inspector"],
  ["runtime", "Runtime inspector"],
  ["behaviour", "Behaviour layer"],
  ["a2a", "Case manager and A2A"],
  ["pipeline", "Whole pipeline"],
  ["cost", "Cost and traces"],
];

/* ------------------------------------------------------------------ panels */

function Overview({ goto }) {
  const j = E.judge;
  const rt = E.runtime;
  const rows = [
    ["Static inspector", "CrewAI", "Reads each tool description", `Precision ${pct(R.llm.static_only.precision)}, recall ${pct(R.llm.static_only.recall)} on ${num(R.run.cases)} cases`, "Evaluated", "static"],
    ["Runtime inspector", "CrewAI", "Reads each tool reply",
      rt && rt.answered_by_model ? `Recall ${pc(rt.model.recall_pct)} on ${rt.model.attacks} response attacks (hosted model)` : `Recall ${pct(R.groups.custom_atk.llm.rate)} on ${R.groups.custom_atk.n} response attacks (local model)`,
      rt && rt.answered_by_model ? "Evaluated" : "Partly", "runtime"],
    ["Behaviour statistics", "ADK layer", "Watches response size and fields over time", `${E.behaviour_stats.series_with_a_false_alarm} false alarms in ${E.behaviour_stats.clean_series} clean series; blind to small or same-length changes`, "Evaluated", "behaviour"],
    ["Behaviour judge", "ADK LlmAgent", "Decides whether flagged drift is a rug pull", j ? `Caught ${j.true_pos} of ${j.true_pos + j.false_neg} judged rug pulls, ${j.false_pos} false alarms (${j.judged} of ${j.cases} cases judged)` : "not run", "Small sample", "behaviour"],
    ["Case manager", "ADK + A2A", "Records each case and a decision", `${E.a2a.messages} messages, ${pc(Math.round(E.a2a.fidelity * 100))} intact, decisions match the policy`, "Evaluated", "a2a"],
    ["Whole pipeline", "All of the above", "Stage order, decisions, when the server is called", `${E.trajectory.n} scenarios, ${pc(Math.round(E.trajectory.decision_correct * 100))} correct decisions; DVMCP: ${E.dvmcp.attack_content_delivered} of ${E.dvmcp.all_inspection_by_model} delivered`, "Evaluated", "pipeline"],
  ];
  return (
    <div className="stack-lg flush">
      <Tbl head={["Agent", "Framework", "Job", "Headline", "Status", ""]}
        rows={rows.map(([a, f, job, h, st, tab]) => [<b>{a}</b>, f, job, h, <span className={`vpill ${st === "Evaluated" ? "clean" : "suspicious"}`}>{st}</span>,
          <button type="button" className="linkbtn" onClick={() => goto(tab)}>Details <Arrow width={12} height={12} /></button>])} />
      <div className="notice">
        <b>Read these numbers with care.</b> The scenarios, drift cases and response cases were written by the project author. The model-based
        sets are small, so rates are indicative and shown with the counts behind them. A rate from the regex fallback is never reported as a model rate.
      </div>
      <div className="panel">
        <div className="panel-title">Re-run everything</div>
        <pre className="cmd">cd backend{"\n"}python -m src.evaluation.agent_evals                 # all evaluations{"\n"}python -m src.evaluation.agent_evals --tier1         # no model calls{"\n"}python -m src.evaluation.agent_evals --only runtime --budget 40</pre>
        <p className="muted" style={{ fontSize: "var(--fs-sm)", margin: 0 }}>Model requests used so far: {E.budget.provider_requests} to the provider and {E.budget.judge_requests} for the ADK judge. Free-tier daily quota exhausted at the last run: {String(E.budget.quota_exhausted_at_end)}.</p>
      </div>
    </div>
  );
}

function Static() {
  const s = R.llm.static_only;
  const g = R.groups;
  const gr = E.grounding.static;
  const rel = E.reliability.ollama_full;
  const rows = ["mcptox", "dvmcp", "benign_real"].map((k) => [g[k].label, g[k].kind === "recall" ? "recall" : "false alarms", `${g[k].llm.flagged}/${g[k].n}`, pct(g[k].llm.rate), `${pct(g[k].llm.lo, 0)} to ${pct(g[k].llm.hi, 0)}`, pct(g[k].regex.rate)]);
  return (
    <div className="stack-lg flush">
      <div className="stat-row four">
        <Tile value={pct(s.precision)} label="Precision" tone="ok" />
        <Tile value={pct(s.recall)} label="Recall" />
        <Tile value={s.f1.toFixed(3)} label="F1" />
        <Tile value={pct(g.benign_real.llm.rate)} label="False alarms, real clean tools" />
      </div>
      <Tbl head={["Group", "Measures", "Flagged", "Model rate", "95% interval", "Regex baseline"]} rows={rows} />
      <div className="grid-2">
        <div className="panel"><div className="panel-title">Evidence is really in the text</div>
          <p className="big">{pc(gr.grounded_phrases_pct)}</p>
          <p className="muted">of {num(gr.phrases)} flagged phrases (in {num(gr.cases_with_phrases)} cases) appear verbatim in the description. {pc(gr.cases_fully_grounded_pct)} of cases are fully grounded. A deterministic check for invented evidence.</p></div>
        <div className="panel"><div className="panel-title">Reliability (local full run)</div>
          <p className="big">{pc(rel.model_answer_pct)}</p>
          <p className="muted">of {num(rel.answers)} answers came from the model, with no fallback or timeout. Median fresh call {(rel.fresh_call_latency_ms_p50 / 1000).toFixed(1)} s, p95 {(rel.p95 / 1000).toFixed(1)} s.</p></div>
      </div>
      <How>Local <b>{R.run.model}</b> on a GPU slice ({R.run.cases.toLocaleString()} cases, prompt {R.run.prompt_version}); MCPTox is the real benchmark, DVMCP was read from the live lab. DVMCP recall is low partly because several challenges have benign tool descriptions. Full tables: <code>docs/evaluation_report.md</code>.</How>
    </div>
  );
}

function Runtime() {
  const rt = E.runtime;
  const g = R.groups;
  const done = rt && rt.answered_by_model > 0;
  const gr = E.grounding.runtime;
  return (
    <div className="stack-lg flush">
      <div className="stat-row four">
        <Tile value={pct(g.custom_atk.llm.rate)} label={`Response attacks caught (${g.custom_atk.llm.flagged}/${g.custom_atk.n})`} />
        <Tile value={`${g.custom_hn.llm.flagged}/${g.custom_hn.n}`} label="Hard negatives wrongly flagged" tone="ok" />
        <Tile value={`${g.custom_ben.llm.flagged}/${g.custom_ben.n}`} label="Plain benign replies flagged" tone="ok" />
        <Tile value={pct(g.custom_atk.regex.rate)} label="Regex baseline recall" />
      </div>
      <p className="muted" style={{ margin: 0 }}>Local <b>{R.run.model}</b> on the 50 hand-written response cases (29 attacks, 12 hard negatives that merely contain instruction-like words, 9 plain benign replies).</p>
      {done ? (
        <>
          <h3 className="sub">Hosted free-tier model</h3>
          <Tbl head={["", "Attacks caught", "Recall", "95% interval", "False alarms on clean", "Hard-negative false alarms", "Precision"]}
            rows={[["Model", `${rt.model.caught}/${rt.model.attacks}`, pc(rt.model.recall_pct), (rt.model.recall_ci95 || []).join(" to ") + "%", `${rt.model.false_alarms}/${rt.model.clean_cases}`, rt.model.hard_negative_false_alarms, pc(rt.model.precision_pct)],
              ["Regex, same cases", `${rt.regex_on_the_same_cases.caught}/${rt.regex_on_the_same_cases.attacks}`, pc(rt.regex_on_the_same_cases.recall_pct), (rt.regex_on_the_same_cases.recall_ci95 || []).join(" to ") + "%", `${rt.regex_on_the_same_cases.false_alarms}/${rt.regex_on_the_same_cases.clean_cases}`, rt.regex_on_the_same_cases.hard_negative_false_alarms, pc(rt.regex_on_the_same_cases.precision_pct)]]} />
          <How>{rt.answered_by_model} of {rt.cases} cases answered by the hosted model ({rt.from_cache} from cache, {rt.fresh_requests} fresh requests); {rt.fell_back_or_timed_out} fell back to regex and are excluded.</How>
        </>
      ) : (
        <div className="notice warn"><Alert width={14} height={14} style={{ verticalAlign: -2 }} /> The hosted-model run on these cases has not completed yet (free-tier quota). The local-model numbers above stand; no hosted-model number is claimed.</div>
      )}
      <div className="panel"><div className="panel-title">Evidence is really in the reply</div>
        <p className="big">{pc(gr.grounded_phrases_pct)}</p>
        <p className="muted">of {gr.phrases} flagged phrases in {gr.cases_with_phrases} cases appear verbatim in the reply they came from.</p></div>
      <How>The response cases were written by the project author, and the v2 prompt shares ideas with some of them, so this is not a held-out test.</How>
    </div>
  );
}

function Behaviour() {
  const b = E.behaviour_stats;
  const j = E.judge;
  return (
    <div className="stack-lg flush">
      <h3 className="sub">Statistics alone (no model)</h3>
      <div className="stat-row four">
        <Tile value={`${b.series_with_a_false_alarm}/${b.clean_series}`} label="Clean series with a false alarm" tone="ok" />
        <Tile value={pc(b.changes.length_x3.detection_rate_pct)} label="Tripled response length caught" />
        <Tile value={pc(b.changes.new_key.detection_rate_pct)} label="New field caught" />
        <Tile value={pc(b.changes.same_length_different_content.detection_rate_pct)} label="Same-length content swap caught" tone="bad" />
      </div>
      <Tbl head={["Change after 10 quiet calls", "Detected", "Rate", "95% interval", "Calls after the change (median)"]}
        rows={Object.entries(b.changes).map(([k, v]) => [k.replaceAll("_", " "), `${v.detected}/${v.series}`, pc(v.detection_rate_pct), (v.ci95 || []).join(" to ") + "%", v.calls_after_change_p50 ?? "never"])} />
      <How>Simulated series of {b.calls_per_series} calls, seed 0. The statistics see size and new fields. A modest growth or a swap at the same length is invisible to them, which is what the runtime inspector and the judge are for.</How>

      <h3 className="sub">ADK judge (hosted model)</h3>
      <div className="stat-row four">
        <Tile value={`${j.true_pos}/${j.true_pos + j.false_neg}`} label="Judged rug pulls caught" tone="ok" />
        <Tile value={`${j.false_pos}/${j.false_pos + j.true_neg}`} label="Benign drifts wrongly escalated" tone="ok" />
        <Tile value={j.stats_did_not_flag} label="Never reached the judge (statistics missed them)" tone="bad" />
        <Tile value={j.judge_no_answer} label="No answer (provider error)" />
      </div>
      <p className="muted" style={{ margin: 0 }}>{j.judged} of {j.cases} hand-written cases were judged. {j.caveat}.</p>
      <details className="under-hood"><summary>All {j.cases} cases</summary>
        <div><Tbl small head={["Case", "Rug pull?", "Result"]} rows={j.rows.map((x) => [x.case, x.is_rug_pull ? "yes" : "no", x.status === "judged" ? (x.escalated ? "escalated" : "not escalated") : x.status])} /></div></details>
    </div>
  );
}

function A2A() {
  const a = E.a2a;
  const p = E.policy;
  const f = E.a2a_failure;
  return (
    <div className="stack-lg flush">
      <div className="stat-row four">
        <Tile value={`${p.combinations - p.disagreements}/${p.combinations}`} label="Policy combinations matching the rules" tone="ok" />
        <Tile value={pc(Math.round(a.fidelity * 100))} label={`A2A messages intact (${a.messages})`} tone="ok" />
        <Tile value={`${a.round_trip_ms_p50} ms`} label="Round trip, median" />
        <Tile value={`${a.round_trip_ms_p95} ms`} label="Round trip, p95" />
      </div>
      <Tbl head={["Check", "Result"]} rows={[
        ["Case manager's decision equals the policy", `${pc(Math.round(a.decision_matches_policy * 100))} of ${a.messages} messages, including tools that need a sensitive scope`],
        ["Policy (`combine_verdicts`) against the written rules", `${p.disagreements} disagreements in ${p.combinations} combinations (a regression guard, not an independent test)`],
        ["A2A server down", `the hop reports "${f.a2a_hop_status}", the run still completes with decision ${f.final_decision}; the case manager is advisory`],
      ]} />
      <div className="notice"><Check width={14} height={14} style={{ verticalAlign: -2 }} /> <b>A bug this found, now fixed.</b> {a.finding_fixed}. The message now carries the scope.</div>
      <How>The messages go over a real A2A HTTP hop to the ADK case manager. Every field is compared after the case is stored. No model is involved.</How>
    </div>
  );
}

function Pipeline() {
  const t = E.trajectory;
  const d = E.dvmcp;
  return (
    <div className="stack-lg flush">
      <h3 className="sub">Trajectory: did the right stages run, in order, with the right decision?</h3>
      <div className="stat-row four">
        <Tile value={pct(t.exact_match, 0)} label="Exact stage match" tone="ok" />
        <Tile value={pct(t.in_order_match, 0)} label="In-order match" tone="ok" />
        <Tile value={pct(t.decision_correct, 0)} label="Correct decision" tone="ok" />
        <Tile value={pct(t.server_call_correct, 0)} label="Server called only when it should be" tone="ok" />
      </div>
      <Tbl small head={["Scenario", "Stages", "Decision", "Server called"]} rows={t.scenarios.map((x) => [x.scenario, x.exact ? "exact" : "differs", <>{x.decision ?? "refused, no decision"} <Verdict ok={x.decision_ok}>{x.decision_ok ? "ok" : "wrong"}</Verdict></>, <>{String(x.server_called)} <Verdict ok={x.server_call_ok}>{x.server_call_ok ? "ok" : "wrong"}</Verdict></>])} />
      <How>The ADK trajectory criteria (exact, in-order, any-order, precision, recall) applied to the pipeline's stages, with no model involved. My first run scored 72.7% exact; the three misses were wrong expectations of mine, corrected after reading the events, not pipeline faults.</How>

      <h3 className="sub">End to end on the ten DVMCP challenges</h3>
      <p className="muted" style={{ margin: 0 }}>Hosted model, human approval auto-denied so nothing dangerous runs. Without Guardian every challenge's content would reach the agent. With it, content was delivered in <b>{d.attack_content_delivered}</b> of {d.all_inspection_by_model} challenges that ran on the model (challenge {(d.excluded_regex_fallback || []).join(", ")} excluded: regex fallback).</p>
      <Tbl small head={["#", "What it is", "Decision", "Description check", "Reply check"]} rows={d.rows.map((x) => [x.challenge, x.note, <b>{x.decision || x.status}</b>, x.static || "-", x.runtime || "-"])} />
    </div>
  );
}

function Cost({ health }) {
  const s = E.stage_latency;
  const url = health?.tracing?.dashboard_url;
  const exp = health?.tracing?.langfuse;
  const refCost = (a) => ((a.tokens_in_mean / 1e6) * 0.3 + (a.tokens_out_mean / 1e6) * 1.2);
  const agentRows = Object.entries(s.agents).filter(([k]) => ["static_inspector", "runtime_inspector", "behaviour_judge"].includes(k));
  return (
    <div className="stack-lg flush">
      <div className="panel langfuse">
        <div>
          <div className="panel-title">Traces, cost and scores</div>
          <p style={{ margin: "0 0 10px" }}>Every run is one trace in Langfuse: each agent, each model call with its prompt, reply, tokens and cost, each MCP tool call, and a set of security scores.</p>
          {url ? <a className="btn primary lg" href={url} target="_blank" rel="noreferrer">Open traces in Langfuse <Arrow /></a>
            : <p className="muted" style={{ margin: 0 }}>{exp ? "Traces are exported to Langfuse. The link to the project is hidden on this deployment." : "Langfuse is not configured on this server. Set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY to export traces."}</p>}
        </div>
      </div>
      <div className="stat-row four">
        <Tile value="$0.00" label="Provider cost (free-tier models)" tone="ok" />
        <Tile value={num(s.traced_runs)} label="Traced runs on this machine" />
        <Tile value={E.budget.provider_requests + E.budget.judge_requests} label="Model requests in the evaluations" />
        <Tile value="masked" label="Credentials in traces" tone="ok" />
      </div>
      <h3 className="sub">Cost and tokens per agent</h3>
      <Tbl head={["Agent", "Model calls traced", "Mean tokens in", "Mean tokens out", "Reference cost per call", "Provider cost"]}
        rows={agentRows.map(([k, v]) => [k.replaceAll("_", " "), v.model_calls, v.tokens_in_mean, v.tokens_out_mean, `$${refCost(v).toFixed(5)}`, "$0.00"])} />
      <How>The reference cost is an estimate: the same tokens priced at $0.30 in / $1.20 out per million tokens, to show what a paid model would cost. The provider cost is what the provider reported, which is $0 for free-tier models. They are never mixed.</How>
      <h3 className="sub">Time per stage</h3>
      <Tbl small head={["Stage", "Runs", "Median ms", "p95 ms"]} rows={Object.entries(s.stage_ms).map(([k, v]) => [k.replaceAll("_", " "), v.n, v.p50, v.p95])} />
      <How>From {num(s.traced_runs)} traced runs on this machine, including regex-only test runs (so the median is low) and verification runs. The slow stages are the ones that call a model.</How>
    </div>
  );
}

/* ------------------------------------------------------------------ page */

export default function EvalsPage({ health }) {
  const [tab, setTab] = useState("overview");
  const url = health?.tracing?.dashboard_url;
  const panel = { overview: <Overview goto={setTab} />, static: <Static />, runtime: <Runtime />, behaviour: <Behaviour />, a2a: <A2A />, pipeline: <Pipeline />, cost: <Cost health={health} /> }[tab];
  return (
    <main className="site">
      <section className="page-hero">
        <div className="wrap">
          <div className="eyebrow">Evaluations</div>
          <h1>Every agent, measured.</h1>
          <p className="lead sm">How each agent performs on its own, how they work together, and what a run costs. Every number comes from a saved evaluation run, with the counts behind it.</p>
          <div className="toolbar">
            {url && <a className="btn primary" href={url} target="_blank" rel="noreferrer">Open traces in Langfuse <Arrow /></a>}
            <button type="button" className="btn" onClick={() => setTab("cost")}>Cost and traces</button>
          </div>
        </div>
      </section>
      <div className="wrap" style={{ paddingBottom: 96 }}>
        <div className="eval-tabs" role="tablist" aria-label="Agents">
          {TABS.map(([id, label]) => (
            <button key={id} type="button" role="tab" aria-selected={tab === id} className={`eval-tab${tab === id ? " on" : ""}`} onClick={() => setTab(id)}>{label}</button>
          ))}
        </div>
        <div role="tabpanel" className="eval-panel">{panel}</div>
      </div>
    </main>
  );
}
