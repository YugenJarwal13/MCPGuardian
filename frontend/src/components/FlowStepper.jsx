import { Check } from "./Icons.jsx";

/**
 * Where the visitor is in a multi-step flow. `current` is the index of the active step; earlier ones show as
 * done. A step listed in `skipped` (for example "Authenticate" on a public server) is shown as not needed.
 */
export default function FlowStepper({ steps, current, skipped = [], label }) {
  return (
    <ol className="stepper" aria-label={label}>
      {steps.map((s, i) => {
        const state = skipped.includes(i) && i < current ? "skip" : i < current ? "done" : i === current ? "on" : "";
        return (
          <li key={s} className={`stepper-item ${state}`} aria-current={i === current ? "step" : undefined}>
            <span className="n">{state === "done" ? <Check width={13} height={13} /> : i + 1}</span>
            <span className="t">{s}</span>
          </li>
        );
      })}
    </ol>
  );
}
