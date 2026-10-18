import { useEffect, useState } from "react";

const reduced = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/**
 * The live status line of an active stage: the backend's message is typed out and ends
 * in pulsing dots, so a slow model call reads as "working", not "frozen". Screen readers
 * get the full sentence once (the animated copy is aria-hidden).
 */
export default function TypingText({ text, speed = 16 }) {
  const [n, setN] = useState(() => (reduced() ? text.length : 0));

  useEffect(() => {
    if (reduced()) {
      setN(text.length);
      return undefined;
    }
    setN(0);
    const id = setInterval(() => {
      setN((v) => {
        if (v >= text.length) {
          clearInterval(id);
          return v;
        }
        return v + 1;
      });
    }, speed);
    return () => clearInterval(id);
  }, [text, speed]);

  // The backend messages already end in "…"; show animated dots instead.
  const shown = text.replace(/…$/, "").slice(0, n);
  const done = n >= text.length;
  return (
    <span className="typing">
      <span className="sr-only">{text}</span>
      <span aria-hidden="true">
        {shown}
        {done ? (
          <span className="dots">
            <span>.</span>
            <span>.</span>
            <span>.</span>
          </span>
        ) : (
          <span className="caret" />
        )}
      </span>
    </span>
  );
}
