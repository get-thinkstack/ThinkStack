/**
 * Pure logic behind the LitGraph side panel.
 *
 * Kept out of the components for the same reason makeAlpha and lassoFar are
 * kept out of useCanvas: these are the parts with a branch worth asserting,
 * and none of them need a DOM to run.
 */

const MIN_W = 280;      // narrower than this and the reader stops being one

/**
 * How wide the panel may actually be, given where the grip was dropped.
 *
 * The order matters: the ceiling is applied last, so on a window narrower
 * than twice MIN_W the panel gives way rather than overflowing the window
 * it sits in.
 */
export const clampPanel = (px, viewportW) =>
  Math.round(Math.min(viewportW / 2, Math.max(MIN_W, px)));
