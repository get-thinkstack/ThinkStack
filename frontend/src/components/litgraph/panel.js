/**
 * Pure logic behind the LitGraph side panel.
 *
 * Kept out of the components for the same reason makeAlpha and lassoFar are
 * kept out of useCanvas: these are the parts with a branch worth asserting,
 * and none of them need a DOM to run.
 */

import { locateQuote, bestSentence } from './highlight';

const MIN_W = 280;        // narrower than this and the reader stops being one
const MIN_CANVAS = 360;   // narrower than this and the map stops being one

/**
 * How wide the panel may actually be, given where the grip was dropped.
 *
 * The ceiling is "whatever leaves the map still a map", not half the window:
 * the panel holds a PDF reader, which wants width, and a grip that stops
 * mid-drag reads as broken. Both panes
 * remain resizable in both directions; neither can erase the other.
 *
 * The order matters: the ceiling is applied last, so on a narrow window the
 * panel gives way rather than overflowing the window it sits in.
 */
export const clampPanel = (px, viewportW) =>
  Math.round(Math.min(Math.max(viewportW - MIN_CANVAS, MIN_W), Math.max(MIN_W, px)));

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
 * The neighbourhood of a paper, out to `depth` hops.
 *
 * Obsidian's local graph, on this map's edge list: depth 1 is the papers this
 * one is linked to, depth 2 adds what THEY are linked to, and so on. Returns a
 * Map of doc_id to the hop it was first reached at, so a caller can draw the
 * rings differently -- which is the whole value of the walk, since "linked"
 * and "linked to something linked" are not the same claim.
 *
 * Breadth-first, so first-reached is genuinely the shortest path and a paper
 * reachable at both 1 and 3 is recorded as 1. The root is in the map at 0.
 *
 * Depth is capped by the caller (the panel offers 1-3): the edge set is at most
 * 4 per node, so depth 4 on a dense library is most of the library, which is
 * the whole map with extra steps.
 */
export function localGraph(rootId, edges, depth) {
  const adj = new Map();
  (edges || []).forEach((e) => {
    if (!adj.has(e.source)) adj.set(e.source, []);
    if (!adj.has(e.target)) adj.set(e.target, []);
    adj.get(e.source).push(e.target);
    adj.get(e.target).push(e.source);
  });

  const hop = new Map([[rootId, 0]]);
  let frontier = [rootId];
  for (let d = 1; d <= depth && frontier.length; d++) {
    const next = [];
    frontier.forEach((id) => {
      (adj.get(id) || []).forEach((to) => {
        if (hop.has(to)) return;
        hop.set(to, d);
        next.push(to);
      });
    });
    frontier = next;
  }
  return hop;
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

/**
 * A gap's evidence, located in each paper it cites.
 *
 * For each paper a gap cites, the passage the gap rests on, or null when it
 * cannot be found.
 *
 * `passage: null` is a real answer and has to be shown as one. The evidence is
 * a model's paraphrase and may not locate; a paper's text may not have arrived
 * yet. Both deserve saying so rather than a link that goes nowhere.
 *
 * @param texts Map<doc_id, chunks[]> -- absent means "not loaded", not "empty"
 * @returns [{ docId, passage: { chunkId, quote, text } | null }]
 */
export function gapPassages(gap, texts) {
  return (gap?.doc_ids || []).map((docId) => {
    const chunks = texts?.get(docId);
    let passage = null;

    // Every phrase, not just the first: a gap's two phrases usually belong to
    // different papers, which is what makes it a gap between them.
    for (const quote of gap.evidence || []) {
      const at = chunks && locateQuote(chunks, quote);
      if (!at) continue;
      const chunk = chunks.find((c) => c.chunk_id === at);
      passage = { chunkId: at, quote, text: bestSentence(chunk.text, quote) || chunk.text };
      break;
    }
    return { docId, passage };
  });
}
