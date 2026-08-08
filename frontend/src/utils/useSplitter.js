/**
 * Drag a divider to resize a pane. Reusable, and remembers where you left it.
 *
 * Generalised from LitGraph's panel grip, which already worked and taught the
 * important trick: the drag writes a CSS custom property straight onto the
 * container and never touches React state. A `setState` per pointermove is a
 * re-render per pixel -- on a canvas or a live LaTeX preview that is visibly
 * choppy, and the layout is CSS's job anyway. React hears about it once, at the
 * end, when the value is persisted.
 *
 * The width is a layout preference like the sidebar and the theme, so it
 * survives a restart. Someone who widens the PDF preview to read it wants it
 * wide tomorrow as well.
 *
 * @param {object}  opts
 * @param {string}  opts.varName   CSS custom property to write, e.g. '--pv-w'
 * @param {string}  opts.storageKey where to remember it
 * @param {number}  opts.initial   px, used the first time
 * @param {number}  opts.min       px, floor
 * @param {number}  opts.max       px, ceiling (or a function of window width)
 * @param {boolean} opts.fromRight measure from the right edge instead of the left
 * @param {number|function} opts.reserve px that must remain for everything the
 *                                 divider is NOT resizing. A three-column layout
 *                                 needs more than a two-column one, and the hook
 *                                 cannot see the other columns -- so the caller
 *                                 states it rather than a constant guessing. A
 *                                 function is called at clamp time, for the case
 *                                 where a sibling pane is itself resizable and
 *                                 the figure is only knowable during the drag.
 * @param {object}  opts.ref       an existing ref to the container. Two dividers
 *                                 resizing columns of the SAME grid must both
 *                                 measure and write to that one element, so the
 *                                 second is given the first's ref rather than
 *                                 creating its own.
 */
import { useCallback, useEffect, useRef } from 'react';

/**
 * Where a divider is allowed to stop. Pure, exported and tested separately,
 * because this is the whole behaviour of the thing and every bug in it so far
 * has been arithmetic rather than DOM.
 *
 * The floor wins ties. When the window is too narrow to satisfy both `min` and
 * `reserve`, something has to give, and it is better to overflow than to
 * collapse a pane to a sliver that cannot be dragged back.
 */
export function clampWidth(px, { min, max, reserve, viewportW }) {
  const ceiling = typeof max === 'function' ? max(viewportW) : max;
  const keep = typeof reserve === 'function' ? reserve() : reserve;
  const hardMax = Math.min(ceiling, Math.max(min, viewportW - keep));
  return Math.round(Math.min(hardMax, Math.max(min, px)));
}

export default function useSplitter({
  varName,
  storageKey,
  initial = 240,
  min = 140,
  max = 720,
  fromRight = false,
  reserve = 320,
  ref = null,
}) {
  const ownRef = useRef(null);
  const containerRef = ref || ownRef;

  const clamp = useCallback(
    (px) => clampWidth(px, { min, max, reserve, viewportW: window.innerWidth }),
    [min, max, reserve],
  );

  // apply the remembered width before first paint, so the pane does not
  // visibly jump from its default to the stored value
  useEffect(() => {
    let stored = null;
    try {
      stored = localStorage.getItem(storageKey);
    } catch { /* private mode: fall through to the default */ }
    const px = clamp(parseInt(stored ?? '', 10) || initial);
    containerRef.current?.style.setProperty(varName, `${px}px`);
  }, [varName, storageKey, initial, clamp]);

  const onPointerDown = useCallback((e) => {
    e.preventDefault();
    const grip = e.currentTarget;
    const container = containerRef.current;
    if (!container) return;

    grip.classList.add('is-dragging');
    grip.setPointerCapture?.(e.pointerId);
    // a text cursor mid-drag, or a half-selected paragraph, both read as a bug
    const prevCursor = document.body.style.cursor;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const move = (ev) => {
      const box = container.getBoundingClientRect();
      const px = fromRight ? box.right - ev.clientX : ev.clientX - box.left;
      container.style.setProperty(varName, `${clamp(px)}px`);
    };

    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      window.removeEventListener('pointercancel', up);
      grip.classList.remove('is-dragging');
      document.body.style.cursor = prevCursor;
      document.body.style.userSelect = '';
      try {
        const v = container.style.getPropertyValue(varName);
        if (v) localStorage.setItem(storageKey, parseInt(v, 10));
      } catch { /* nothing to persist to */ }
    };

    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
    // a cancelled pointer (a drag off the window, a touch interrupted) must
    // still tear the listeners down, or the next click keeps resizing
    window.addEventListener('pointercancel', up);
  }, [varName, storageKey, clamp, fromRight]);

  /** keyboard resize, so this is not mouse-only. */
  const onKeyDown = useCallback((e) => {
    const container = containerRef.current;
    if (!container) return;
    const step = e.shiftKey ? 40 : 12;
    const current = parseInt(container.style.getPropertyValue(varName), 10) || initial;
    let next = null;
    if (e.key === 'ArrowLeft') next = current + (fromRight ? step : -step);
    if (e.key === 'ArrowRight') next = current + (fromRight ? -step : step);
    if (next === null) return;
    e.preventDefault();
    const px = clamp(next);
    container.style.setProperty(varName, `${px}px`);
    try {
      localStorage.setItem(storageKey, px);
    } catch { /* nothing to persist to */ }
  }, [varName, storageKey, initial, clamp, fromRight]);

  return { containerRef, onPointerDown, onKeyDown };
}
