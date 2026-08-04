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

/**
 * The papers this one is linked to, strongest first.
 *
 * `weight` is the cosine similarity between document embedding centroids;
 * the server keeps each node's top 4 above 0.35 (graph_builder._edges). An
 * edge is undirected, so it has to be read from whichever end this paper
 * happens to sit on.
 */
export function neighbours(id, edges) {
  return (edges || [])
    .filter((e) => e.source === id || e.target === id)
    .map((e) => ({ id: e.source === id ? e.target : e.source, weight: e.weight }))
    .sort((a, b) => b.weight - a.weight);
}

/**
 * The closest and most distant paper in the projection.
 *
 * Node positions are a PCA over the embedding centroids, computed server-side
 * and sent normalised to 0..1. That makes the layout meaningful but not
 * legible -- "closest to X, furthest from Y" is the smallest thing that turns
 * a position into a statement. Returns null when there is no second paper,
 * because a one-paper projection explains nothing.
 *
 * `far` is null when the library holds exactly one other paper: it is then
 * the same paper as `near`, and "closest to X, furthest from X" is nonsense.
 */
export function nearestFurthest(node, nodes) {
  const by = (nodes || [])
    .filter((n) => n.doc_id !== node.doc_id)
    .map((n) => ({ n, d: Math.hypot(n.x - node.x, n.y - node.y) }))
    .sort((a, b) => a.d - b.d);
  if (!by.length) return null;
  return { near: by[0].n, far: by.length > 1 ? by[by.length - 1].n : null };
}
