import { useEffect } from "react";
import { Arrow, Bug, Check, Cpu, Database, Eye, Info, Layers, Link, Search, Shield } from "../components/Icons.jsx";
import HeroScene from "../components/HeroScene.jsx";
import { useCountUp, useInView } from "../hooks/useReveal.js";
import { ROUTES } from "../router.js";
import R from "../data/results.json";

const REPO = "https://github.com/YugenJarwal13/MCPGuardian";
const pct = (x, d = 1) => `${(x * 100).toFixed(d)}%`;
const int = (n) => n.toLocaleString("en-US");
const shortModel = (m) => (m || "").replace(/^.*\//, "");

function Reveal({ d = 0, className = "", children, ...rest }) {
  const [ref, seen] = useInView(0.12);
  return (
    <div ref={ref} className={`reveal${seen ? " in" : ""} ${className}`} style={{ "--d": d }} {...rest}>
      {children}
    </div>
  );
}

function Kpi({ value, suffix = "%", decimals = 1, label, sub, hl, d }) {
  const [ref, seen] = useInView(0.4);
  const v = useCountUp(value, seen);
  return (
    <div ref={ref} className={`kpi reveal${seen ? " in" : ""}${hl ? " hl" : ""}`} style={{ "--d": d }}>
      <div className="v num">{decimals === 0 ? int(Math.round(v)) : v.toFixed(decimals)}<small>{suffix}</small></div>
      <div className="l">{label}</div>
      <div className="s">{sub}</div>
    </div>
  );
}

/** Two bars (model vs regex) for one group; widths animate in once visible. */
function GroupBars({ g, higherIsBetter }) {
  const [ref, seen] = useInView(0.3);
  const a = g.llm;
  const b = g.regex;
  return (
    <div ref={ref} className="brow">
      <div className="bl"><span>{g.label.replace(" (metadata)", "").replace(" (custom)", "")}</span><small>{int(g.n)} cases</small></div>
      <div className="track has-val" title={`${a.flagged} of ${g.n} (95% CI ${pct(a.lo, 0)}–${pct(a.hi, 0)})`}>
        <i className="fill l" style={{ width: seen ? `${Math.max(a.rate * 100, a.rate ? 1.5 : 0)}%` : 0 }} />
        {seen && a.n !== 0 && <i className="ci" style={{ left: `${a.lo * 100}%`, width: `${(a.hi - a.lo) * 100}%` }} />}
        <span className="val">{pct(a.rate)} · {a.flagged}/{g.n}</span>
      </div>
      <div className="track has-val">
        <i className="fill r" style={{ width: seen ? `${Math.max(b.rate * 100, b.rate ? 1.5 : 0)}%` : 0 }} />
        <span className="val">{pct(b.rate)} · {b.flagged}/{g.n}</span>
      </div>
      <span className="sr-only">{higherIsBetter ? "higher is better" : "lower is better"}</span>
    </div>
  );
}

function CategoryRow({ c }) {
  const [ref, seen] = useInView(0.3);
  return (
    <tr ref={ref}>
      <td>{c.category.replaceAll("_", " ")}</td>
      <td className="n">{int(c.n)}</td>
      <td style={{ width: "34%" }}>
        <div className="track" style={{ margin: 0, height: 10 }}><i className="fill l" style={{ width: seen ? `${c.llm * 100}%` : 0 }} /></div>
      </td>
      <td className="n win">{pct(c.llm, 0)}</td>
      <td className="n">{pct(c.regex, 0)}</td>
    </tr>
  );
}

export default function HomePage({ section }) {
  const mt = R.groups.mcptox;
  const bn = R.groups.benign_real;
  const dv = R.groups.dvmcp;
  const hrs = Math.floor(R.run.duration_minutes / 60);
  const mins = Math.round(R.run.duration_minutes % 60);

  useEffect(() => {
    if (!section) return;
    const el = document.getElementById(section);
    if (el) setTimeout(() => el.scrollIntoView({ behavior: "smooth", block: "start" }), 60);
  }, [section]);

  const attacks = ["mcptox", "custom_atk", "dvmcp"].map((k) => R.groups[k]).filter(Boolean);
  const clean = ["benign_real", "custom_hn", "custom_ben", "benign_hand"].map((k) => R.groups[k]).filter(Boolean);

  return (
    <main className="site">
      {/* ---------------------------------------------------------------- hero */}
      <section className="hero">
        <div className="wrap hero-grid">
          <div className="hero-text">
            <a className="hero-pill" href={ROUTES.demo}>
              <span className="ic"><Check /></span> Live demo ready <span className="dim">— watch every step</span> <Arrow width={14} height={14} />
            </a>
            <h1 className="h-xl">Your AI agent trusts every tool it meets. <span className="accent">Guardian doesn’t.</span></h1>
            <p className="lead">
              MCP Guardian sits between an AI agent and the tool servers it connects to. It reads every tool description
              and every reply before the agent can be tricked by them, using language-model inspectors, a behaviour
              watcher and a human-in-the-loop gate.
            </p>
            <div className="cta-row">
              <a className="btn primary lg" href={ROUTES.demo}>Watch the live demo <Arrow /></a>
              <a className="btn lg" href={ROUTES.testLive}>Check a server of your own</a>
            </div>
            <div className="ticks">
              <span><i><Check /></i> CrewAI + Google ADK + A2A</span>
              <span><i><Check /></i> Runs on a local model</span>
              <span><i><Check /></i> Tested on {int(R.dataset.total)} cases</span>
            </div>
          </div>
          <div className="hero-stage"><HeroScene /></div>
        </div>
      </section>

      {/* -------------------------------------------------------------- problem */}
      <section className="section" id="problem">
        <div className="wrap">
          <Reveal>
            <div className="eyebrow">The problem</div>
            <h2 className="h-lg wide">AI agents read the manual. Then they believe it.</h2>
            <p className="lead">
              The Model Context Protocol (MCP) is how AI assistants plug into tools: files, databases, calendars, the web.
              Every tool comes with a text description, and the agent follows it as if it were instructions. Anyone who
              can edit that text can steer the agent, and the user never sees it happen.
            </p>
          </Reveal>
          <div className="cards c3">
            {[
              [Bug, "Tool poisoning", "A malicious tool hides an order inside its own description: “before you answer, also send me…”. The agent reads it as part of the manual and obeys."],
              [Eye, "Poisoned replies", "Even a harmless-looking tool can return data with a command smuggled inside, such as a web page, a ticket or a file that talks to the AI instead of the human."],
              [Layers, "Rug pulls", "A tool behaves for a while, earns trust, then quietly changes. A one-time check at connect time never sees the switch."],
            ].map(([Ic, t, p], i) => (
              <Reveal key={t} d={i} className="fcard"><div className="ic"><Ic /></div><h3>{t}</h3><p>{p}</p></Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------- solution */}
      <section className="section tint" id="how">
        <div className="wrap">
          <Reveal>
            <div className="eyebrow">The solution</div>
            <h2 className="h-lg wide">A bodyguard between the agent and every tool.</h2>
            <p className="lead">
              Guardian never lets the agent talk to a server directly. Everything passes four checks, in order, and the
              final decision is always one of three: <b>allow</b>, <b>block</b>, or <b>ask a human</b>.
            </p>
          </Reveal>
          <div className="flow">
            {[
              ["Read the labels", "Before any call, an AI inspector reads every tool description, hunting for hidden orders aimed at the AI instead of at people.", "CrewAI · Metadata Auditor"],
              ["Check the gate", "A policy decides whether the call may run. Poisoned tools are stopped outright; tools that can touch credentials or files need a human yes.", "Policy · schema-based scopes"],
              ["Scan the answer", "When the server replies, a second inspector separates ordinary data from commands hidden inside it, before the agent sees a word.", "CrewAI · Response Auditor"],
              ["Watch behaviour", "A statistical fingerprint of each tool flags sudden drift. A separate case-manager agent keeps the file and has the last word.", "Google ADK · A2A hand-off"],
            ].map(([t, p, who], i) => (
              <Reveal key={t} d={i} className="flow-step"><h3>{t}</h3><p>{p}</p><div className="who">{who}</div></Reveal>
            ))}
          </div>
          <div className="cards c3">
            {[
              [Search, "CrewAI: the inspectors", "Two specialised agents, each with a role, a goal and a strict output format. They return a verdict (clean, suspicious or malicious), a confidence, and the exact phrases that worried them. If the model is slow or fails, the answer is marked as such. It is never silently replaced."],
              [Cpu, "Google ADK: memory and judgement", "ADK keeps per-tool memory in a database: how long answers usually are, which fields they have. It calls its own judge agent only when the numbers drift. A case-manager agent, also built on ADK, stores each case."],
              [Link, "A2A: the hand-off", "The inspector verdict is not passed as a function call. It is sent as an Agent-to-Agent (A2A) message over HTTP to the case manager, which replies with its own decision. Real network hop, real protocol."],
            ].map(([Ic, t, p], i) => (
              <Reveal key={t} d={i} className="fcard"><div className="ic"><Ic /></div><h3>{t}</h3><p>{p}</p></Reveal>
            ))}
          </div>
          <Reveal><div className="cta-row"><a className="btn primary lg" href={ROUTES.demo}>See all four checks run, live <Arrow /></a></div></Reveal>
        </div>
      </section>

      {/* -------------------------------------------------------------- results */}
      <section className="section" id="results">
        <div className="wrap">
          <Reveal>
            <div className="eyebrow">Results</div>
            <h2 className="h-lg wide">Tested on {int(R.dataset.total)} cases. Every one answered by the model.</h2>
            <p className="lead">
              We ran the full CrewAI inspection pipeline on the public MCPTox benchmark, the DVMCP lab and our own
              response tests, using the open model <b>{shortModel(R.run.model)}</b> running locally. Strict mode: if the model
              had failed to answer a case, it would have been excluded and reported, never quietly relabelled. It
              answered {int(R.run.answered)} of {int(R.run.cases)}.
            </p>
          </Reveal>
          <div className="kpis">
            <Kpi hl d={0} value={R.llm.combined.recall * 100} label="of attacks caught" sub={`vs ${pct(R.regex.combined.recall)} for a regex baseline`} />
            <Kpi d={1} value={R.llm.combined.precision * 100} label="of alarms were real attacks" sub={`precision, vs ${pct(R.regex.combined.precision)} regex`} />
            <Kpi d={2} value={bn.llm.rate * 100} label="false alarms on real clean tools" sub={`${bn.llm.flagged} of ${bn.n} real tools; regex: ${pct(bn.regex.rate)}`} />
            <Kpi d={3} value={mt.llm.flagged} suffix="" decimals={0} label="real MCPTox attacks caught" sub={`out of ${int(mt.n)} (${pct(mt.llm.rate)}; 95% CI ${pct(mt.llm.lo, 0)}–${pct(mt.llm.hi, 0)})`} />
          </div>

          <Reveal className="panelx">
            <h3>Attacks: how many did it catch?</h3>
            <p className="sub">Higher is better. The thin black whisker is the 95% confidence interval for the model.</p>
            <div className="legend"><span><i className="l" />Guardian (CrewAI + {shortModel(R.run.model)})</span><span><i className="r" />Regex baseline</span></div>
            <div className="bars">{attacks.map((g) => <GroupBars key={g.label} g={g} higherIsBetter />)}</div>
            {dv && (
              <div className="note"><b>Honest note on DVMCP ({pct(dv.llm.rate, 0)}).</b> Many DVMCP challenges have harmless-looking descriptions; the flaw is in how the
                tool is built (for example, it runs a shell command it was handed). No tool-description reader can see that. Two of the lab’s descriptions
                are also quoted in our prompt, so DVMCP is not a clean test for the model. MCPTox is.</div>
            )}
          </Reveal>

          <Reveal className="panelx">
            <h3>Clean tools: how many did it wrongly flag?</h3>
            <p className="sub">Lower is better. “Hard negatives” are harmless texts that look suspicious on purpose (for example a changelog that says “ignore the warnings”).</p>
            <div className="bars">{clean.map((g) => <GroupBars key={g.label} g={g} />)}</div>
          </Reveal>

          <div className="split">
            <Reveal className="panelx" style={{ marginTop: 0 }}>
              <h3>By attack type (MCPTox)</h3>
              <p className="sub">The eight largest categories of real attacks.</p>
              <table className="table">
                <thead><tr><th>Category</th><th className="n">Cases</th><th /><th className="n">Model</th><th className="n">Regex</th></tr></thead>
                <tbody>{R.categories.map((c) => <CategoryRow key={c.category} c={c} />)}</tbody>
              </table>
            </Reveal>
            <Reveal className="panelx" d={1} style={{ marginTop: 0 }}>
              <h3>Where they disagree</h3>
              <p className="sub">Across all attack cases, which detector caught what the other missed.</p>
              <div className="kpis" style={{ gridTemplateColumns: "1fr 1fr", marginTop: 22 }}>
                <div className="kpi hl"><div className="v num">{int(R.agreement.llm_caught_regex_missed)}</div><div className="l">only the model caught</div><div className="s">regex found nothing wrong</div></div>
                <div className="kpi"><div className="v num">{int(R.agreement.regex_caught_llm_missed)}</div><div className="l">only the regex caught</div><div className="s">the model missed them</div></div>
              </div>
              <p className="sub" style={{ marginTop: 18 }}>The regex is not useless: it still catches {int(R.agreement.regex_caught_llm_missed)} attacks the model let through, which is why Guardian
                keeps both and uses the stricter verdict.</p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ---------------------------------------------------------------- regex */}
      <section className="section tint" id="regex">
        <div className="wrap">
          <Reveal>
            <div className="eyebrow">Baseline vs. language model</div>
            <h2 className="h-lg wide">What a hand-written regex can and can’t see.</h2>
            <p className="lead">
              To know whether the AI inspectors earn their keep, we built the simplest honest alternative first and
              measured it on exactly the same cases.
            </p>
          </Reveal>
          <div className="split">
            <Reveal className="panelx" style={{ marginTop: 0 }}>
              <h3>How the regex baseline was built</h3>
              <ul className="dcard" style={{ paddingLeft: 18, color: "var(--text-2)" }}>
                <li><b>{R.regex_rules} instruction patterns</b> for the common ways hidden orders are phrased: “ignore previous instructions”, “do not tell the user”, “send … credentials”, hidden HTML comments, “forward all responses”, and similar.</li>
                <li><b>3 encoding checks</b>: zero-width characters, long base64 blobs and control characters, which are used to hide text.</li>
                <li><b>Scope rules</b> that escalate any tool whose parameters grant file writes, network egress, code execution or credentials.</li>
                <li><b>Never tuned</b> after seeing any of these results. It runs in under a millisecond and costs nothing.</li>
              </ul>
              <p className="sub" style={{ marginTop: 14 }}>Its weakness: it only recognises wording it was told about. Most real attacks are phrased as polite, ordinary sentences, so a pattern list misses them.</p>
            </Reveal>
            <Reveal className="panelx" d={1} style={{ marginTop: 0 }}>
              <h3>How {shortModel(R.run.model)} differs</h3>
              <p className="sub" style={{ maxWidth: "none" }}>
                {shortModel(R.run.model)} is a small open language model (about 4 billion parameters, Qwen family) that runs locally through Ollama, so no tool
                description leaves the machine. Instead of matching words it judges <b>intent</b>: is this sentence describing
                a tool to a person, or giving orders to an AI? It also explains itself, naming the phrases that worried it.
              </p>
              <table className="table">
                <thead><tr><th /><th className="n">Regex</th><th className="n">{shortModel(R.run.model)}</th></tr></thead>
                <tbody>
                  <tr><td>Attacks caught (all)</td><td className="n">{pct(R.regex.combined.recall)}</td><td className="n win" style={{ color: "var(--accent-text)", fontWeight: 700 }}>{pct(R.llm.combined.recall)}</td></tr>
                  <tr><td>MCPTox attacks</td><td className="n">{pct(mt.regex.rate)}</td><td className="n" style={{ color: "var(--accent-text)", fontWeight: 700 }}>{pct(mt.llm.rate)}</td></tr>
                  <tr><td>Precision</td><td className="n">{pct(R.regex.combined.precision)}</td><td className="n" style={{ color: "var(--accent-text)", fontWeight: 700 }}>{pct(R.llm.combined.precision)}</td></tr>
                  <tr><td>False alarms, real clean tools</td><td className="n" style={{ color: "var(--accent-text)", fontWeight: 700 }}>{pct(bn.regex.rate)}</td><td className="n">{pct(bn.llm.rate)}</td></tr>
                  <tr><td>Speed per check</td><td className="n" style={{ color: "var(--accent-text)", fontWeight: 700 }}>&lt; 1 ms</td><td className="n">~{Math.round(R.run.median_call_seconds)} s</td></tr>
                </tbody>
              </table>
              <p className="sub" style={{ marginTop: 12 }}>Highlighted = better. The model nearly doubles the attacks caught, at the cost of seconds per check and a few more false alarms on clean tools.</p>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------- datasets */}
      <section className="section" id="datasets">
        <div className="wrap">
          <Reveal>
            <div className="eyebrow">The data</div>
            <h2 className="h-lg wide">Built on real benchmarks, with credit where it’s due.</h2>
            <p className="lead">None of the attacks below were written for this project except where stated. Please cite and support the original authors.</p>
          </Reveal>
          <div className="cards c3">
            <Reveal className="fcard big dcard">
              <div className="ic"><Database /></div>
              <div className="nm">MCPTox</div>
              <div className="by">AAAI 2026 benchmark · <a className="ext" href="https://github.com/zhiqiangwang4/MCPTox-Benchmark" target="_blank" rel="noreferrer">zhiqiangwang4/MCPTox-Benchmark</a></div>
              <p>A benchmark of <b>tool-poisoning attacks on real-world MCP servers</b>: genuine tool listings with malicious instructions planted inside the metadata, labelled by attack type.</p>
              <ul><li>privacy leakage, information manipulation, service disruption, infrastructure damage, data tampering…</li><li>plus the original, unmodified tools as a clean set</li></ul>
              <div className="used"><b>We use:</b> {int(R.dataset.groups.mcptox.n)} attack cases (36 the authors flagged as bad data were dropped) and {int(R.dataset.groups.benign_real.n)} clean real tools. This is our main, held-out test.</div>
            </Reveal>
            <Reveal className="fcard big dcard" d={1}>
              <div className="ic"><Bug /></div>
              <div className="nm">DVMCP</div>
              <div className="by">Damn Vulnerable MCP Server · <a className="ext" href="https://github.com/harishsg993010/damn-vulnerable-MCP-server" target="_blank" rel="noreferrer">harishsg993010/damn-vulnerable-MCP-server</a></div>
              <p>An educational lab of <b>ten deliberately vulnerable MCP servers</b> of rising difficulty: prompt injection, tool poisoning, excessive permissions, rug pulls, tool shadowing, token theft, code execution and more.</p>
              <ul><li>runs as real servers on your machine</li><li>perfect for demonstrating the pipeline end to end</li></ul>
              <div className="used"><b>We use:</b> {int(R.dataset.groups.dvmcp.n)} live tool descriptions read from the running lab, and the whole lab for the <a href={ROUTES.demo}>live demo</a>.</div>
            </Reveal>
            <Reveal className="fcard big dcard" d={2}>
              <div className="ic"><Info /></div>
              <div className="nm">Our response tests</div>
              <div className="by">written for this project</div>
              <p>MCPTox checks tool <i>descriptions</i>; it doesn’t test what a tool <i>returns</i>. So we wrote cases for that gap.</p>
              <ul><li>{R.dataset.groups.custom_atk.n} replies with a hidden command</li><li>{R.dataset.groups.custom_ben.n} ordinary replies</li><li>{R.dataset.groups.custom_hn.n} “hard negatives”: harmless text that sounds like an attack</li></ul>
              <div className="used"><b>Honest caveat:</b> small and hand-written by the same team, so read it as a probe, not a field benchmark.</div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------- hardware */}
      <section className="section tint" id="hardware">
        <div className="wrap">
          <Reveal>
            <div className="eyebrow">How it was measured</div>
            <h2 className="h-lg wide">One full pass, on a data-centre GPU.</h2>
            <p className="lead">
              The complete run (every case through the real CrewAI pipeline) executed on <b>{R.run.gpu}</b> in
              the {R.run.cluster}, with the model served by {R.run.runtime}. For comparison, the same model on a
              student laptop CPU takes about 78 seconds per call.
            </p>
          </Reveal>
          <Reveal className="hw">
            <div><b>{R.run.gpu.replace("NVIDIA ", "")}</b><span>GPU slice (NVIDIA)</span></div>
            <div><b>{hrs} h {mins} min</b><span>wall-clock, {R.run.workers} worker</span></div>
            <div><b>{R.run.median_call_seconds.toFixed(1)} s</b><span>median model call</span></div>
            <div><b>{int(R.run.answered)} / {int(R.run.cases)}</b><span>cases answered by the model</span></div>
          </Reveal>
          <Reveal className="note info" style={{ marginTop: 26 }}>
            <b>Reading these numbers fairly.</b> One model, one run; the prompt (v2) contains two DVMCP descriptions as examples, so MCPTox and the clean
            tools are the clean tests. The regex was not tuned on any of this. Full methodology and every table are in{" "}
            <a href={`${REPO}/blob/master/docs/evaluation_report.md`} target="_blank" rel="noreferrer">the evaluation report</a>.
          </Reveal>
        </div>
      </section>

      {/* --------------------------------------------------- audit & security */}
      <section className="section" id="audit">
        <div className="wrap">
          <Reveal>
            <div className="eyebrow">Built to be audited</div>
            <h2 className="h-lg wide">Every decision leaves a trail.</h2>
            <p className="lead">A security tool you can't inspect is just another thing to trust. Guardian records what it did and why, and protects itself while doing it.</p>
          </Reveal>
          <div className="cards c3">
            {[
              [Eye, "Traced end to end", "Each run is one OpenTelemetry trace: a span per stage and a span per model call with model, tokens, latency and cache hit. Traces are written to a local file and can be sent to Langfuse. The trace id is shown in the live console."],
              [Layers, "Callbacks everywhere", "CrewAI step and task callbacks and Google ADK agent, model and tool callbacks write intermediate outputs and errors into the audit trail, so a failure can be debugged after the fact."],
              [Shield, "Guarded itself", "Tool arguments and server addresses go through an input guard. On the public site, internal addresses are refused, visitors are rate-limited, and the shared AI budget degrades to regex rules instead of failing."],
            ].map(([Ic, t, p], i) => (
              <Reveal key={t} d={i} className="fcard"><div className="ic"><Ic /></div><h3>{t}</h3><p>{p}</p></Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ cta */}
      <section className="section">
        <div className="wrap">
          <Reveal className="cta-band">
            <h2>Seeing is believing. Watch Guardian work.</h2>
            <p>Run a real tool call against a deliberately poisoned server and follow every step the backend takes, then point it at a server of your own.</p>
            <div className="cta-row">
              <a className="btn primary lg" href={ROUTES.demo}>Open the live demo <Arrow /></a>
              <a className="btn lg" href={ROUTES.testLive}>Check any MCP server</a>
            </div>
          </Reveal>
          <footer className="foot">
            <span><Shield width={16} height={16} style={{ verticalAlign: -3 }} /> MCP Guardian · open source · benchmarks courtesy of MCPTox and DVMCP</span>
            <span><a href={REPO} target="_blank" rel="noreferrer">GitHub</a> · <a href={`${REPO}/blob/master/DONE_REPORT.md`} target="_blank" rel="noreferrer">Project report</a></span>
          </footer>
        </div>
      </section>
    </main>
  );
}
