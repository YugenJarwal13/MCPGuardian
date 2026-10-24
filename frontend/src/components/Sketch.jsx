// Hand-drawn style illustrations shared by the landing animation and the live pipeline scene.
// Every shape is plain SVG: strokes use currentColor-like tokens, and a displacement filter gives
// the lines a slightly wobbly, pencil-on-paper feel. Coordinates are centred on (0, 0).

/** Mount once near the root: defines the wobble filter the sketches reference. */
export function SketchDefs() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden="true" focusable="false">
      <defs>
        <filter id="rough" x="-5%" y="-5%" width="110%" height="110%">
          <feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="2" seed="4" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="2.4" />
        </filter>
        <filter id="rough-soft" x="-5%" y="-5%" width="110%" height="110%">
          <feTurbulence type="fractalNoise" baseFrequency="0.05" numOctaves="1" seed="9" result="n" />
          <feDisplacementMap in="SourceGraphic" in2="n" scale="1.4" />
        </filter>
      </defs>
    </svg>
  );
}

export function Agent({ mood = "happy", x = 0, y = 0, scale = 1 }) {
  const tricked = mood === "tricked";
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`}>
    <g className={`sk-agent mood-${mood}`} filter="url(#rough)">
      <path className="sk" d="M0 -52 V-64" />
      <circle className="sk sk-fill antenna" cx="0" cy="-68" r="4" />
      <rect className="sk sk-fill" x="-28" y="-52" width="56" height="46" rx="14" />
      {mood === "happy" && (
        <>
          <path className="sk" d="M-15 -32 q5 -6 10 0 M5 -32 q5 -6 10 0" />
          <path className="sk" d="M-9 -19 q9 8 18 0" />
        </>
      )}
      {mood === "alert" && (
        <>
          <circle className="sk" cx="-10" cy="-31" r="4" />
          <circle className="sk" cx="10" cy="-31" r="4" />
          <path className="sk" d="M-8 -17 h16" />
        </>
      )}
      {tricked && (
        <>
          <path className="sk bad" d="M-15 -37 l9 9 M-6 -37 l-9 9 M6 -37 l9 9 M15 -37 l-9 9" />
          <path className="sk bad" d="M-9 -15 q4 -7 9 0 q4 7 9 0" />
        </>
      )}
      <rect className="sk sk-fill" x="-23" y="0" width="46" height="46" rx="12" />
      <path className="sk" d="M-23 12 l-15 22 M23 12 l15 22" />
      <path className="sk" d="M-11 22 h22" />
    </g>
    </g>
  );
}

export function Person({ x = 0, y = 0, scale = 1 }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} filter="url(#rough)">
      <circle className="sk sk-fill" cx="0" cy="-34" r="20" />
      <path className="sk" d="M-9 -36 h.1 M9 -36 h.1" strokeWidth="4" />
      <path className="sk" d="M-8 -26 q8 6 16 0" />
      <path className="sk sk-fill" d="M-38 46 q0 -50 38 -50 q38 0 38 50 z" />
    </g>
  );
}

export function Hacker({ x = 0, y = 0, scale = 1 }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} filter="url(#rough)">
      <path className="sk sk-fill" d="M-34 44 q-4 -78 34 -88 q38 10 34 88 z" />
      <path className="sk bad-fill" d="M-17 -18 q17 -14 34 0 v22 q-17 12 -34 0 z" />
      <path className="sk bad" d="M-9 -5 l6 3 M9 -5 l-6 3" />
      <path className="sk bad" d="M-7 11 q7 5 14 0" />
    </g>
  );
}

export function ServerBox({ x = 0, y = 0, scale = 1, danger = false }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} className={danger ? "sk-server danger" : "sk-server"} filter="url(#rough)">
      {[-46, -12, 22].map((yy, i) => (
        <g key={yy}>
          <rect className="sk sk-fill" x="-38" y={yy} width="76" height="28" rx="8" />
          <circle className={`sk led ${danger && i === 0 ? "bad-fill" : ""}`} cx="-24" cy={yy + 14} r="3" />
          <path className="sk" d={`M-10 ${yy + 14} h34`} />
        </g>
      ))}
      <path className="sk" d="M-14 50 h28 M0 46 v4" />
      {danger && <path className="sk bad" d="M-30 -50 l8 -14 l8 14 M14 -50 l8 -14 l8 14" />}
    </g>
  );
}

export function ShieldIcon({ x = 0, y = 0, scale = 1, mark = "check", glow = false }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} className={`sk-shield${glow ? " glow" : ""}`} filter="url(#rough)">
      <path className="sk acc-fill" d="M0 -52 L40 -38 V4 q0 34 -40 52 q-40 -18 -40 -52 V-38 z" />
      {mark === "check" && <path className="sk white" d="M-17 2 l12 13 l24 -28" />}
      {mark === "cross" && <path className="sk white" d="M-14 -12 l28 28 M14 -12 l-28 28" />}
      {mark === "none" && <circle className="sk white" cx="0" cy="2" r="9" />}
    </g>
  );
}

export function Scroll({ x = 0, y = 0, scale = 1, bad = false }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} filter="url(#rough-soft)">
      <path className={`sk sk-fill${bad ? " bad-stroke" : ""}`} d="M-22 -28 h32 l14 14 v42 h-46 z" />
      <path className={`sk${bad ? " bad-stroke" : ""}`} d="M10 -28 v14 h14" />
      <path className={`sk${bad ? " bad-stroke" : ""}`} d="M-14 -6 h26 M-14 4 h26 M-14 14 h16" />
    </g>
  );
}

export function Envelope({ x = 0, y = 0, scale = 1, bad = false }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} filter="url(#rough-soft)">
      <rect className={`sk sk-fill${bad ? " bad-stroke" : ""}`} x="-24" y="-16" width="48" height="32" rx="5" />
      <path className={`sk${bad ? " bad-stroke" : ""}`} d="M-24 -14 l24 18 l24 -18" />
    </g>
  );
}

export function Magnifier({ x = 0, y = 0, scale = 1 }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} filter="url(#rough-soft)">
      <circle className="sk" cx="-4" cy="-4" r="15" />
      <path className="sk" d="M7 7 l15 15" strokeWidth="4" />
      <path className="sk" d="M-12 -10 q4 -6 10 -6" />
    </g>
  );
}

export function Gate({ x = 0, y = 0, open = false, scale = 1 }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} filter="url(#rough-soft)">
      <rect className="sk sk-fill" x="-20" y="-6" width="12" height="34" rx="3" />
      <g className="gate-arm" style={{ transformOrigin: "-8px 4px", transform: open ? "rotate(-68deg)" : "rotate(0deg)" }}>
        <path className="sk" d="M-8 4 h42" strokeWidth="4" />
        <path className="sk" d="M4 4 v-0.1 M16 4 v-0.1 M28 4 v-0.1" strokeWidth="6" />
      </g>
    </g>
  );
}

export function Scanner({ x = 0, y = 0, scale = 1 }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} filter="url(#rough-soft)">
      <path className="sk sk-fill" d="M-20 -22 h30 l12 12 v34 h-42 z" />
      <path className="sk" d="M-12 -4 h24 M-12 6 h24 M-12 16 h14" />
      <path className="sk scan-line" d="M-26 0 h52" />
    </g>
  );
}

export function Pulse({ x = 0, y = 0, scale = 1 }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} filter="url(#rough-soft)">
      <circle className="sk sk-fill" cx="0" cy="0" r="24" />
      <path className="sk ecg" d="M-18 2 h8 l4 -12 l8 24 l5 -16 l3 4 h10" />
    </g>
  );
}

export function Folder({ x = 0, y = 0, scale = 1 }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} filter="url(#rough-soft)">
      <path className="sk sk-fill" d="M-24 -14 h16 l6 6 h26 v28 h-48 z" />
      <path className="sk" d="M-16 4 h32" />
    </g>
  );
}

export function Human({ x = 0, y = 0, scale = 1 }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`} filter="url(#rough-soft)">
      <circle className="sk sk-fill" cx="0" cy="-12" r="9" />
      <path className="sk sk-fill" d="M-17 22 q0 -24 17 -24 q17 0 17 24 z" />
    </g>
  );
}
