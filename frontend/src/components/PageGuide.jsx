/**
 * The "i" in the bottom-left corner: what this page is, on demand.
 *
 * Promoted out of LitGraph, where it already existed and worked. The canvas
 * used to carry a permanent line of instructions across its bottom edge --
 * read once on the first visit, then noise on every visit afterwards. Behind an
 * "i" the same words stay reachable and stop competing with the page.
 *
 * Every screen now gets that treatment, which is what let the subtitle under
 * each page title go. A sentence explaining the page is worth reading once;
 * it is not worth the vertical strip it occupied forever, and Scribe needs that
 * strip for the editor and the preview to have half the height each.
 *
 * The panel floats rather than pushing: opening it must not reflow an editor
 * you are typing in, and closed it costs no height at all.
 */

import { useEffect, useRef, useState } from 'react';

/**
 * Rendered once by the shell, from the active feature's `guide` in features.js.
 * No page wires this up, and no page can forget to.
 *
 * It sits OUTSIDE `.main-content` on purpose. The shell collapses the sidebar
 * on any interaction with the page, and reading the guide is not working on the
 * page -- having it fold the layout away would be an odd answer to "what is
 * this screen?".
 *
 * @param {string}    label    what this guide describes, for screen readers
 * @param {ReactNode} children the guide itself
 */
export default function PageGuide({ label = 'About this page', children }) {
  const [open, setOpen] = useState(false);
  const wrap = useRef(null);

  // Dismiss on a click anywhere else, and on Escape.
  //
  // Listening in the CAPTURE phase, because much of what surrounds this stops
  // propagation -- the canvas swallows pointer events, and a bubbling listener
  // would leave the guide stuck open over exactly the page it describes.
  useEffect(() => {
    if (!open) return undefined;

    const onPointerDown = (e) => {
      if (!wrap.current?.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };

    document.addEventListener('pointerdown', onPointerDown, true);
    document.addEventListener('keydown', onKey, true);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('keydown', onKey, true);
    };
  }, [open]);

  return (
    <div ref={wrap} className="page-guide">
      {open && (
        <div className="page-guide-panel" role="dialog" aria-label={label}>
          {children}
        </div>
      )}
      <button
        type="button"
        className={`page-guide-btn ${open ? 'on' : ''}`}
        onClick={() => setOpen((v) => !v)}
        aria-label={label}
        aria-expanded={open}
      >
        i
      </button>
    </div>
  );
}
