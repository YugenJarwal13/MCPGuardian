import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE = 'a[href],button:not(:disabled),textarea,input,select,[tabindex]:not([tabindex="-1"])';

/**
 * Contextual dialog: one clear title, a short explanation, one primary action and (usually) a secondary one.
 * Closes on Escape and on a backdrop click when `onClose` is given; keeps focus inside while open and returns it
 * afterwards. `footer` holds the buttons so every dialog lays them out the same way.
 */
export default function Modal({ open, eyebrow, title, onClose, children, footer, wide = false }) {
  const box = useRef(null);
  const returnTo = useRef(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    if (!open) return undefined;
    returnTo.current = document.activeElement;
    document.body.classList.add("modal-open");
    const first = box.current?.querySelector("[data-autofocus]") || box.current?.querySelector(FOCUSABLE) || box.current;
    first?.focus();
    const onKey = (e) => {
      if (e.key === "Escape" && closeRef.current) {
        e.stopPropagation();
        closeRef.current();
      } else if (e.key === "Tab" && box.current) {
        const items = [...box.current.querySelectorAll(FOCUSABLE)];
        if (!items.length) return;
        const a = items[0];
        const z = items[items.length - 1];
        if (e.shiftKey && document.activeElement === a) { e.preventDefault(); z.focus(); }
        else if (!e.shiftKey && document.activeElement === z) { e.preventDefault(); a.focus(); }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.classList.remove("modal-open");
      returnTo.current?.focus?.();
    };
  }, [open]);

  if (!open) return null;
  return createPortal(
    <div className="modal-backdrop" onMouseDown={(e) => { if (e.target === e.currentTarget && closeRef.current) closeRef.current(); }}>
      <div ref={box} className={`modal${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1}>
        <header className="modal-head">
          {eyebrow && <div className="modal-eyebrow">{eyebrow}</div>}
          <h2>{title}</h2>
        </header>
        <div className="modal-body">{children}</div>
        {footer && <footer className="modal-foot">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}
