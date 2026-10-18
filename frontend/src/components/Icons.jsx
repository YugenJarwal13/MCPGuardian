// Small inline SVG icon set (stroke icons, currentColor). No icon library.
const base = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor",
  strokeWidth: 2.2, strokeLinecap: "round", strokeLinejoin: "round", "aria-hidden": true };

export const Check = (p) => (
  <svg {...base} {...p}><path className="draw" d="M5 12.5l4.5 4.5L19 7.5" /></svg>
);
export const Alert = (p) => (
  <svg {...base} {...p}><path className="draw" d="M12 7v6" /><circle cx="12" cy="17.2" r="0.6" fill="currentColor" /></svg>
);
export const Cross = (p) => (
  <svg {...base} {...p}><path className="draw" d="M6.5 6.5l11 11M17.5 6.5l-11 11" /></svg>
);
export const Question = (p) => (
  <svg {...base} {...p}><path d="M9.5 9.2a2.6 2.6 0 115 .8c0 1.6-2.5 2-2.5 3.6" /><circle cx="12" cy="17.6" r="0.6" fill="currentColor" /></svg>
);
export const Dot = (p) => (<svg {...base} {...p}><circle cx="12" cy="12" r="2.2" fill="currentColor" stroke="none" /></svg>);
export const Chevron = (p) => (<svg {...base} width={14} height={14} {...p}><path d="M9 6l6 6-6 6" /></svg>);
export const Sun = (p) => (
  <svg {...base} {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2.5v2.2M12 19.3v2.2M4.6 4.6l1.6 1.6M17.8 17.8l1.6 1.6M2.5 12h2.2M19.3 12h2.2M4.6 19.4l1.6-1.6M17.8 6.2l1.6-1.6" /></svg>
);
export const Moon = (p) => (<svg {...base} {...p}><path d="M20.5 14.2A8.5 8.5 0 119.8 3.5a6.7 6.7 0 0010.7 10.7z" /></svg>);
export const Shield = (p) => (
  <svg {...base} width={22} height={22} {...p}><path d="M12 3l7.5 2.8v5.6c0 4.4-3 8-7.5 9.6-4.5-1.6-7.5-5.2-7.5-9.6V5.8L12 3z" /><path d="M8.8 12l2.4 2.4 4-4.4" /></svg>
);
export const Play = (p) => (<svg {...base} {...p}><path d="M7 4.8l12 7.2-12 7.2V4.8z" fill="currentColor" /></svg>);
