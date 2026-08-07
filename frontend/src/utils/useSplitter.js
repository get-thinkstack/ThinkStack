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
 * @param {object}  opts.ref       an existing ref to the container. Two dividers
 *                                 resizing columns of the SAME grid must both
 *                                 measure and write to that one element, so the
 *                                 second is given the first's ref rather than
 *                                 creating its own.
 */
import { useCallback, useEffect, useRef } from 'react';

export default function useSplitter({
  varName,
  storageKey,
  initial = 240,
  min = 140,
  max = 720,
  fromRight = false,
  ref = null,
}) {
  const ownRef = useRef(null);
  const containerRef = ref || ownRef;

  const clamp = useCallback((px) => {
    const ceiling = typeof max === 'function' ? max(window.innerWidth) : max;
    // never let a pane eat the window: whatever the stored value, something
    // has to be left for everything else
    const hardMax = Math.min(ceiling, Math.max(min, window.innerWidth - 320));
    return Math.round(Math.min(hardMax, Math.max(min, px)));
  }, [min, max]);

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
