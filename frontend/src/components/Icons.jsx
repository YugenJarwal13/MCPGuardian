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

export const Arrow = (p) => (<svg {...base} {...p}><path d="M5 12h14M13 6l6 6-6 6" /></svg>);
export const Link = (p) => (<svg {...base} {...p}><path d="M10 14a4 4 0 005.7 0l3-3a4 4 0 00-5.7-5.7l-1 1M14 10a4 4 0 00-5.7 0l-3 3A4 4 0 0011 18.7l1-1" /></svg>);
export const Eye = (p) => (<svg {...base} {...p}><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="3" /></svg>);
export const Layers = (p) => (<svg {...base} {...p}><path d="M12 3l9 5-9 5-9-5 9-5zM3 13l9 5 9-5M3 17.5l9 5 9-5" /></svg>);
export const Cpu = (p) => (<svg {...base} {...p}><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3" /></svg>);
export const Info = (p) => (<svg {...base} {...p}><circle cx="12" cy="12" r="9" /><path d="M12 11v5" /><circle cx="12" cy="7.8" r="0.6" fill="currentColor" /></svg>);
export const Database = (p) => (<svg {...base} {...p}><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></svg>);
export const Bug = (p) => (<svg {...base} {...p}><rect x="8" y="8" width="8" height="11" rx="4" /><path d="M9 8a3 3 0 016 0M4 13h4M16 13h4M5 7l3 2M19 7l-3 2M5 20l3-3M19 20l-3-3" /></svg>);
export const Search = (p) => (<svg {...base} {...p}><circle cx="11" cy="11" r="6.5" /><path d="M16 16l5 5" /></svg>);
export const Github = (p) => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" {...p}>
    <path d="M12 .5a11.5 11.5 0 00-3.64 22.41c.58.1.79-.25.79-.56v-2c-3.2.7-3.88-1.36-3.88-1.36-.52-1.33-1.28-1.69-1.28-1.69-1.04-.71.08-.7.08-.7 1.15.08 1.76 1.18 1.76 1.18 1.03 1.76 2.7 1.25 3.36.96.1-.75.4-1.25.73-1.54-2.55-.29-5.24-1.28-5.24-5.69 0-1.26.45-2.28 1.18-3.09-.12-.29-.51-1.46.11-3.05 0 0 .97-.31 3.17 1.18a11 11 0 015.77 0c2.2-1.49 3.17-1.18 3.17-1.18.62 1.59.23 2.76.11 3.05.74.81 1.18 1.83 1.18 3.09 0 4.42-2.69 5.39-5.25 5.68.41.36.78 1.06.78 2.14v3.17c0 .31.21.67.8.56A11.5 11.5 0 0012 .5z" />
  </svg>
);
