import { useEffect, useRef, useCallback, useMemo } from 'react';
import {
  FORCE_DEFAULTS, ALPHA_DECAY, ALPHA_MIN, anchorFor,
  seed as seedForces, link as linkForces, step as stepForces,
} from './forces';
import { localGraph } from './panel';

/**
 * The LitGraph canvas engine.
 *
 * Deliberately imperative. The graph is a few hundred SVG nodes that re-render
 * on every hover, pan and zoom; driving that through React's reconciler would
 * mean rebuilding the element tree at 60fps for no benefit, since none of these
 * nodes are composed with other React components. So this hook owns one <svg>
 * via a ref and mutates it directly, and the React layer above deals only with
 * what the user actually selected.
 *
 * Ported from docs/litgraph-demo.html (rev 3). The rules the visual language
 * depends on, kept from the prototype:
 *
 *   position  encodes meaning   (embedding space, projected by the backend)
 *   territory encodes category  (theme hulls)
 *   hue       encodes state     (what you are doing right now, never category)
 */

const NS = 'http://www.w3.org/2000/svg';
const el = (t, a = {}) => {
  const n = document.createElementNS(NS, t);
  for (const k in a) n.setAttribute(k, a[k]);
  return n;
};

// world box. node coordinates arrive normalised to 0..1 and are scaled to this,
// so the layout is resolution-independent and the camera math has fixed bounds.
const W = 1100;
const H = 760;

const REDUCED =
  typeof window !== 'undefined' &&
  window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;

/**
 * Camera tween.
 *
 * A hand-rolled rAF loop rather than framer-motion: this animates a plain
 * object (not a DOM node) and must be cancellable mid-flight when the user
 * grabs the canvas. Twelve lines beats reaching for an animation library's
 * object-target semantics for the one place timing is load-bearing.
 */
function tween(from, to, ms, onUpdate) {
  if (REDUCED || ms === 0) {
    Object.assign(from, to);
    onUpdate();
    return () => {};
  }
  const start = performance.now();
  const a = { ...from };
  let raf = 0;
  const step = (now) => {
    const t = Math.min(1, (now - start) / ms);
    const e = 1 - Math.pow(1 - t, 4); // outQuart
    for (const k in to) from[k] = a[k] + (to[k] - a[k]) * e;
    onUpdate();
    if (t < 1) raf = requestAnimationFrame(step);
  };
  raf = requestAnimationFrame(step);
  return () => cancelAnimationFrame(raf);
}

/** convex-ish hull around a set of points, as a closed path. */
function hullPath(pts) {
  if (!pts.length) return '';
  const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
  const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
  const R = Math.max(...pts.map((p) => Math.hypot(p.x - cx, p.y - cy))) + 46;
  let d = '';
  for (let a = 0; a < 360; a += 24) {
    const rad = (a * Math.PI) / 180;
    const rr = R * (0.92 + 0.08 * Math.sin(rad * 3 + pts.length));
    d +=
      (a ? ' L' : 'M') +
      (cx + Math.cos(rad) * rr).toFixed(1) +
      ' ' +
      (cy + Math.sin(rad) * rr * 0.82).toFixed(1);
  }
  return d + ' Z';
}

/** ray-cast point-in-polygon, for the lasso. */
function inside(pt, poly) {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const a = poly[i];
    const b = poly[j];
    if (
      a.y > pt.y !== b.y > pt.y &&
      pt.x < ((b.x - a.x) * (pt.y - a.y)) / (b.y - a.y) + a.x
    )
      hit = !hit;
  }
  return hit;
}

/**
 * One place decides node opacity, so the state rules cannot drift apart.
 * Exported for its test; restyle() uses it verbatim.
 */
export function makeAlpha(matches, focus, neighbours) {
  const searching = matches.size > 0;
  return (id) => {
    if (searching) return matches.has(id) ? 1 : 0.15;
    if (!focus) return 1;
    if (id === focus) return 1;
    return neighbours.has(id) ? 0.6 : 0.32;
  };
}

/**
 * The papers a focused gap rests on, or null when the focus is not a gap.
 *
 * A gap is a node no edge touches -- edges join papers, and a gap is a claim
 * about several of them at once. So its neighbourhood cannot be read off the
 * edge list the way a paper's can; it is written on the gap itself.
 */
export function citedBy(model, focus) {
  const gap = focus && (model?.gaps || []).find((g) => g.gap_id === focus);
  return gap ? new Set(gap.doc_ids) : null;
}

/**
 * Whether an edge belongs to what is currently selected.
 *
 * For a paper that is the edges it sits on. For a gap it is the edges *between*
 * the papers it cites -- which is the whole claim the marker is making, and
 * what was invisible while selecting a gap dimmed every edge on the map.
 */
export function edgeLit(e, focus, cited) {
  if (e.a === focus || e.b === focus) return true;
  return !!cited && cited.has(e.a) && cited.has(e.b);
}

/**
 * Whether a new lasso point is far enough from the last to be worth keeping.
 * `k` is the zoom, so the threshold stays 4 screen pixels at any scale.
 */
/**
 * How big the target is, given how big the dot is.
 *
 * D-18: two testers on different operating systems reported, without
 * prompting, that selecting a node takes more precision than it should. They
 * were describing the geometry. A paper is drawn at 4.5 to 8.5 units on an
 * 1100x760 canvas and the listener sits on the group, so the target WAS the
 * drawing -- about four pixels across once the plate is zoomed out to fit.
 *
 * The drawing does not change: discs turned the plate into a bubble chart, and
 * that is why they are points of light. What changes is that the target stops
 * being the drawing. An invisible circle carries the events instead.
 *
 * Bounded on both sides. At least 14 so the smallest paper is reachable, and
 * small enough that two adjacent targets cannot touch: graph_builder keeps
 * nodes MIN_SEP = 0.055 apart, which is about 60 units here, and overlapping
 * targets in a dense cluster would be a worse bug than a small one.
 */
export const hitRadius = (r) => Math.max(14, r + 10);

/**
 * The same target, held at a constant size on SCREEN.
 *
 * Zooming out to fit 22 papers puts the plate at about 0.66, which shrank a
 * 28-unit target to 19 pixels. Raising the zoom floor instead would have
 * cropped the map on open, and the map's whole value is seeing the structure
 * at once -- so the target is counter-scaled rather than the view.
 *
 * `min` is 28 CSS pixels: the WCAG 2.2 minimum is 24, and a plate you drag
 * around deserves more than the minimum. Capped at half of MIN_SEP (about 60
 * units) so two targets can never touch however far out you are.
 */
export const hitRadiusAt = (r, k, min = 28) =>
  Math.min(29, Math.max(hitRadius(r), min / 2 / Math.max(k, 0.05)));

export const lassoFar = (a, b, k) => Math.hypot(b.x - a.x, b.y - a.y) >= 4 / k;

/**
 * How far apart two gap markers have to be to read as two.
 *
 * The outer ring is 31, so 84 leaves a clear gap between two of them rather
 * than letting the rings kiss. Measured on the plate, not derived: at 76 the
 * five gaps of a nine-paper library still touched.
 */
const GAP_SEP = 84;

/**
 * Where a hand-arranged map is kept.
 *
 * Same convention as lg-panel-w and lg-has-picked in LitGraph.jsx: a namespaced
 * key, written directly. A pinned paper is the user's own statement about where
 * something belongs and it outranks both the projection and the simulation, so
 * it has to survive a reload -- otherwise tidying the map is something you do
 * once per session and lose.
 */
const PINS_KEY = 'lg-pins';

/**
 * Read the pins back, keeping only papers that are still in the library.
 *
 * The prune is the point: a pin is a coordinate against a doc_id, and a doc_id
 * that has been deleted (or a store written by an older build) would otherwise
 * sit in localStorage forever and, worse, hold a position for a paper that no
 * longer exists. Any parse failure is treated as "no pins" rather than thrown:
 * a corrupt preference must not take the map down with it.
 */
function savePins(pins) {
  try {
    if (typeof localStorage !== 'undefined') localStorage.setItem(PINS_KEY, JSON.stringify(pins));
  } catch {
    // A full or blocked store is not a reason to lose the drag on screen.
  }
}

export function loadPins(raw, ids) {
  let saved;
  try {
    saved = JSON.parse(raw || '{}');
  } catch {
    return {};
  }
  if (!saved || typeof saved !== 'object') return {};
  const live = new Set(ids);
  const out = {};
  Object.entries(saved).forEach(([id, at]) => {
    if (!live.has(id)) return;
    if (!at || !Number.isFinite(at.x) || !Number.isFinite(at.y)) return;
    out[id] = { x: at.x, y: at.y };
  });
  return out;
}

/**
 * A paper's radius, in one place.
 *
 * `length` is what the map has always drawn -- a longer paper is a bigger dot.
 * `links` is Obsidian's answer and often the better one here, where a paper
 * everything argues with matters more than a long paper. Shared with the
 * collision, which has to reserve the space the dot is going to want.
 */
function radiusOf(n, model, display) {
  if (display.size === 'uniform') return 6;
  if (display.size === 'links') {
    const deg = model.edges.reduce(
      (s, e) => s + (e.source === n.doc_id || e.target === n.doc_id ? 1 : 0), 0,
    );
    return 4 + Math.min(deg, 8) * 0.62;
  }
  return 4.5 + Math.min(n.chunks, 200) / 50;
}

/**
 * Which gesture a pointerdown starts.
 *
 * Drag pans; the lasso is behind shift. It was briefly the other way round --
 * drag-to-select, space-to-pan -- and a trackpad made the case against it:
 * every two-finger navigation drag became a selection, so the map could not
 * be moved at all. Panning is the gesture a canvas cannot lose; selection is
 * the one that can afford a modifier (and the help popover now names it).
 *
 * A press that lands on a node is neither: the node has its own click
 * listener, and starting a one-point lasso under it only flashes the lasso
 * path before discarding it.
 *
 * Exported for its test; `down` below uses it verbatim.
 */
export function gestureFor(e) {
  if (e.target?.closest?.('.lg-node')) return 'node';
  if (e.shiftKey) return 'lasso';
  if (e.button === 0 || e.button === 1) return 'pan';
  return 'none';
}

/** Do two label boxes touch? Boxes that only share an edge do not. */
export const boxesHit = (a, b) =>
  a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/**
 * Decide which labels can be shown without landing on one already placed.
 *
 * The server spaces the NODES; it cannot know that a 26-character title is
 * ~160px wide. Boxes are estimated from the text length rather than measured
 * with getBBox(), which would force a layout pass per label -- an estimate is
 * the right precision for a show/hide decision.
 *
 * Earlier entries win, so callers pass them in priority order. World units, so
 * the answer holds at every zoom: labels scale with the viewport.
 */
export function placeLabels(entries, obstacles = []) {
  // Seeded with the things that were already on the plate before any label
  // was. A title is several times the width of the dot it belongs to, so on a
  // relaxed layout the labels cleared each other and then landed squarely
  // across the papers and the edges -- which is most of what "jumbled" meant.
  const placed = [...obstacles];
  return entries.map(({ text, x, y, anchor = 'middle' }) => {
    const w = text.length * 6.2;
    const box = {
      x: anchor === 'middle' ? x - w / 2 : x,
      y: y - 10,
      w,
      h: 13,
    };
    if (placed.some((p) => boxesHit(box, p))) return false;
    placed.push(box);
    return true;
  });
}

/**
 * Which level of detail a zoom is at.
 *
 * A map of two hundred papers cannot draw two hundred titles and stay a map.
 * Zoomed out it is a map of TERRITORIES -- the hulls and their names, papers as
 * points; coming in resolves the biggest papers, then all of them. Named bands
 * rather than a continuous curve so the label placement can be cached per band
 * and not recomputed on every frame of a pan.
 *
 * Exported for its test.
 */
export const LOD_FAR = 0.55;
export const LOD_NEAR = 1.1;
export function lodBand(k) {
  if (k < LOD_FAR) return 0;      // territories only
  if (k < LOD_NEAR) return 1;     // the most-linked papers name themselves
  return 2;                       // everything
}

export default function useCanvas({
  svgRef,
  graph,
  colors,
  matches,
  focus,
  expanded,
  onSelect,
  onLasso,
  // How far the focused paper's neighbourhood reaches, from the panel's depth
  // control. 1 is what the map has always dimmed to -- the papers this one is
  // directly linked to -- so the default changes nothing.
  depth = 1,
}) {
  // eslint-disable-next-line react-hooks/refs -- see the note above `model`
  const state = useRef({
    cam: { x: 0, y: 0, k: 1 },
    pos: {},
    layers: { themes: true, gaps: true },
    // ---- the layout dial ----
    // Not two modes: one number. 0 is the projection the backend computed and
    // the state the map opens in, and no simulation runs at all. Above 0 the
    // same papers relax, each held by a spring back to its own projected home
    // -- which is what stops the library collapsing into a knot. Either way it
    // writes to `state.pos`, so everything downstream -- the lasso, the
    // minimap, fitTo, the click targets -- is free and never learns about it.
    blend: 0,
    forces: { ...FORCE_DEFAULTS },
    // doc_id -> {x, y} the user put it at. Survives the dial, a reload and an
    // ingest; loaded and pruned in rebuildModel.
    pins: {},
    // Which LOD band the label placement was resolved for, so panning inside
    // one band costs nothing.
    band: -1,
    // Three states the map has always had and never shown. A paper with no
    // edge above EDGE_THRESHOLD is on the plate saying nothing; a paper that
    // was ingested but never analysed looks exactly like one that was; an
    // encrypted paper is a title and nothing else. All three default to
    // visible, because hiding something by default is how you lose it.
    filters: { orphans: true, unanalysed: true, encrypted: true },
    // `size` picks what a dot's radius means; `fade` is the zoom at which
    // titles come in; `thickness` scales the similarity strokes.
    display: { size: 'length', fade: 0.5, thickness: 0.5 },
    sim: null,
    simLinks: null,
    simRaf: 0,
    alpha: 0,
    cancelTween: () => {},
    // What restyle() writes to, collected once while the scene is built. Every
    // entry holds the elements themselves, so restyling is a loop over arrays
    // rather than a querySelectorAll per pass.
    paint: { nodes: [], edges: [], gapEdges: [], gapNodes: [], labels: [] },
    camRaf: 0,
  }).current;

  // ---- derived lookups, rebuilt whenever the graph payload changes ----
  //
  // `state` and `model` are containers whose *identity* must never change:
  // they are mutated in place, they appear in dependency lists, and `state.pos`
  // is handed out in the returned handle. react-hooks/refs objects to reading
  // .current at the top of a hook, and it is right about the usual case; here
  // useMemo would be wrong, because React is permitted to discard a memo, and
  // discarding this one silently resets the camera and every node position.
  // eslint-disable-next-line react-hooks/refs -- deliberate; see above
  const model = useRef({ nodes: [], edges: [], themes: [], gaps: [] }).current;

  /**
   * Gaps have no embedding of their own, so they are placed at the centroid of
   * the papers they cite. That is also what makes them *look* like a property
   * of a region rather than a separate kind of object floating free.
   *
   * Its own function because the force layout has to redo it on every tick: a
   * gap that stayed put while the papers under it moved would stop being about
   * them, which is the one thing a gap marker has to be.
   */
  const placeGaps = useCallback(() => {
    const placed = [];
    model.gaps.forEach((g) => {
      const pts = g.doc_ids.map((d) => state.pos[d]).filter(Boolean);
      if (!pts.length) return;
      const at = {
        x: pts.reduce((s, p) => s + p.x, 0) / pts.length,
        y: pts.reduce((s, p) => s + p.y, 0) / pts.length - 70,
      };
      state.pos[g.gap_id] = at;
      placed.push(at);
    });

    // Gaps cited by overlapping sets of papers share most of a centroid and
    // would stack into one bullseye (a relaxed layout makes that certain), so
    // they get a few passes of the same separation the papers get.
    // GAP_SEP is the outer ring (31) plus a little, so two markers read as two.
    for (let pass = 0; pass < 12; pass++) {
      for (let i = 0; i < placed.length; i++) {
        for (let j = i + 1; j < placed.length; j++) {
          const a = placed[i];
          const b = placed[j];
          let dx = b.x - a.x;
          let dy = b.y - a.y;
          let d = Math.hypot(dx, dy);
          if (d >= GAP_SEP) continue;
          if (d < 1e-6) { dx = (i % 2 ? 1 : -1); dy = (j % 2 ? 1 : -1); d = Math.hypot(dx, dy); }
          const push = ((GAP_SEP - d) / 2) * 0.9;
          a.x -= (dx / d) * push; a.y -= (dy / d) * push;
          b.x += (dx / d) * push; b.y += (dy / d) * push;
        }
      }
    }
  }, [model, state]);

  /**
   * What a paper takes up on the plate, for the collision.
   *
   * Not the dot -- the dot plus the TITLE under it. A 26-character label is
   * about 150 world units wide and the dot is nine, so separating dots and
   * hoping is what put titles across the edges. Wide and short, hence an
   * ellipse. The title is what render() will actually draw, truncated the same
   * way, so the reservation matches the thing that turns up.
   */
  const footprints = useCallback(() => {
    const out = {};
    model.nodes.forEach((n) => {
      const r = radiusOf(n, model, state.display);
      const shown = n.title.length > 26 ? 26 : n.title.length;
      out[n.doc_id] = {
        rx: Math.max(r + 6, (shown * 6.2) / 2),
        ry: r + 16,
      };
    });
    return out;
  }, [model, state]);

  /**
   * Positions every node and gap from the graph payload. Called at the top of
   * render, NOT from its own effect: `model` and `state` are mutated in place,
   * so their identity never changes and no dependency list would notice a new
   * graph (the canvas would keep drawing the previous library).
   */
  const rebuildModel = useCallback(() => {
    model.nodes = graph?.nodes || [];
    model.edges = graph?.edges || [];
    model.themes = graph?.themes || [];
    model.gaps = graph?.gaps || [];

    // cleared in place, never reassigned: the object identity is part of the
    // handle this hook returns, and swapping it would make that handle change
    // on every graph refresh.
    Object.keys(state.pos).forEach((k) => delete state.pos[k]);
    model.nodes.forEach((n) => {
      state.pos[n.doc_id] = { x: n.x * W, y: n.y * H };
    });

    // Pins outrank the projection at every point on the dial. Read once per
    // payload, pruned against it, so a deleted paper cannot hold a coordinate.
    state.pins = loadPins(
      typeof localStorage === 'undefined' ? '{}' : localStorage.getItem(PINS_KEY),
      model.nodes.map((n) => n.doc_id),
    );
    Object.entries(state.pins).forEach(([id, at]) => {
      if (state.pos[id]) { state.pos[id].x = at.x; state.pos[id].y = at.y; }
    });

    // The projection is the baseline; above blend 0 the simulation's own
    // coordinates are then written over it, so a structural re-render mid-relax
    // redraws where things ARE rather than snapping the scene back to PCA. A
    // simulation that no longer covers the payload (a paper arrived, one was
    // deleted) is dropped and reseeded on next start.
    if (state.blend > 0 && state.sim) {
      if (state.sim.length === model.nodes.length) {
        state.sim.forEach((p) => {
          if (state.pos[p.id]) { state.pos[p.id].x = p.x; state.pos[p.id].y = p.y; }
        });
      } else {
        state.sim = null;
        state.simLinks = null;
      }
    }
    placeGaps();
  }, [graph, model, state, placeGaps]);

  /**
   * Write `state.pos` back onto the scene, without rebuilding it.
   *
   * The structural render is expensive by design -- it creates every element,
   * attaches every listener and resolves the label collisions -- and the force
   * layout needs new coordinates sixty times a second. So the simulation moves
   * what is already on screen and nothing else: the same discipline restyle()
   * uses for hover, applied to geometry instead of colour.
   *
   * Labels are deliberately NOT re-placed here. The collision pass is a
   * whole-scene decision and re-running it per frame would make titles blink in
   * and out while the graph is moving; the settle calls render() once, which
   * resolves them properly against where everything ended up.
   */
  const reposition = useCallback(() => {
    const paint = state.paint;
    paint.nodes.forEach(({ id, g }) => {
      const p = state.pos[id];
      if (p && g.parentNode) g.parentNode.setAttribute('transform', `translate(${p.x},${p.y})`);
    });
    paint.gapNodes.forEach(({ id, g }) => {
      const p = state.pos[id];
      if (p && g.parentNode) g.parentNode.setAttribute('transform', `translate(${p.x},${p.y})`);
    });
    paint.edges.forEach(({ line, a, b }) => {
      const pa = state.pos[a];
      const pb = state.pos[b];
      if (!pa || !pb) return;
      line.setAttribute('x1', pa.x); line.setAttribute('y1', pa.y);
      line.setAttribute('x2', pb.x); line.setAttribute('y2', pb.y);
    });
    paint.gapEdges.forEach((line) => {
      const pg = state.pos[line.dataset.gap];
      const pd = state.pos[line.dataset.doc];
      if (!pg || !pd) return;
      line.setAttribute('x1', pg.x); line.setAttribute('y1', pg.y);
      line.setAttribute('x2', pd.x); line.setAttribute('y2', pd.y);
    });
    (paint.hulls || []).forEach(({ path, label, doc_ids }) => {
      const pts = doc_ids.map((d) => state.pos[d]).filter(Boolean);
      if (!pts.length) return;
      path.setAttribute('d', hullPath(pts));
      const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
      const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
      const R = Math.max(...pts.map((p) => Math.hypot(p.x - cx, p.y - cy))) + 46;
      label.setAttribute('x', cx);
      label.setAttribute('y', cy + R * 0.82 + 18);
    });
  }, [state]);

  /**
   * One camera paint. Never call this directly from an input handler --
   * `applyCam` below coalesces those into a frame.
   */
  const paintCam = useCallback(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const vp = svg.querySelector('#lg-viewport');
    if (!vp) return;
    const { x, y, k } = state.cam;
    vp.setAttribute('transform', `translate(${x},${y}) scale(${k})`);
    // Hold the click targets at a constant size on screen. Without this the
    // plate zoomed out to fit turns a 28-unit target into 19 pixels, which is
    // the complaint two testers raised independently (D-18).
    svg.querySelectorAll('.lg-hit').forEach((h) => {
      h.setAttribute('r', hitRadiusAt(Number(h.dataset.baseR) || 4.5, k));
    });
    // semantic zoom: hulls are a macro read and only add noise once you are
    // inside a cluster.
    const hulls = svg.querySelector('#lg-hulls');
    if (hulls)
      hulls.style.opacity = state.layers.themes
        ? k < 1.6
          ? 1
          : Math.max(0, 1 - (k - 1.6))
        : 0;
    // ---- level of detail ----
    //
    // Two hundred papers cannot draw two hundred titles and stay a map. Far
    // out this is a map of TERRITORIES: hulls, their names, papers as points.
    // Coming in resolves the most-linked papers, then all of them.
    //
    // The placement pass is O(n^2) over candidates and must never run on a
    // pan, so it runs only when the BAND changes. Everything else here is a
    // per-frame attribute write, which is what paintCam is for.
    const band = lodBand(k);
    if (band !== state.band) {
      state.band = band;
      const slots = state.paint.slots || [];

      // The dots, so a title can no longer be placed on top of a paper. This
      // was the omission that let labels land across the plate.
      const obstacles = slots.filter((sl) => sl.box).map((sl) => sl.box);

      // Which titles are even offered. Hulls always; papers by band, in
      // descending link count so the ones that carry the structure win.
      const ranked = slots
        .filter((sl) => sl.kind === 'node')
        .sort((a, b) => b.rank - a.rank);
      const budget = band === 0 ? 0 : band === 1 ? Math.ceil(ranked.length * 0.25) : ranked.length;
      const offered = new Set(ranked.slice(0, budget));

      const candidates = slots.filter(
        (sl) => sl.kind !== 'node' || offered.has(sl),
      );
      const ok = placeLabels(candidates, obstacles);
      const verdict = new Map(candidates.map((sl, i) => [sl, ok[i]]));
      slots.forEach((sl) => {
        sl.el.style.display = verdict.get(sl) ? '' : 'none';
      });

      // Papers shrink to points when nothing is named: at that distance the
      // dot is a position, not an object, and full-size dots read as a bubble
      // chart of nothing.
      state.paint.nodes.forEach((n) => {
        n.circle.setAttribute('r', band === 0 ? 2 : n.baseR);
      });
    }

    // Obsidian calls this the text fade threshold. It was the constant 0.5,
    // which is still where the slider sits by default, so nothing moves until
    // somebody reaches for it. It rides on top of the band decision: the band
    // says which titles exist, this says how strongly they come in.
    const t = state.display.fade;
    const o = k < t ? 0 : Math.min(1, (k - t) * 3);
    state.paint.labels.forEach((lb) => {
      lb.style.opacity = o;
    });

    // The HUD readouts join this paint rather than React state: a pan would
    // otherwise re-render the whole panel sixty times a second to move a
    // rectangle. Both elements are looked up once, when the scene is built.
    const { zoomEl, mmVp } = state.paint;
    if (zoomEl) zoomEl.textContent = `${k.toFixed(2)}×`;
    if (mmVp) {
      // What the window currently shows, in world units.
      const r = svg.getBoundingClientRect();
      mmVp.setAttribute('x', (-x / k).toFixed(1));
      mmVp.setAttribute('y', (-y / k).toFixed(1));
      mmVp.setAttribute('width', (r.width / k).toFixed(1));
      mmVp.setAttribute('height', (r.height / k).toFixed(1));
    }
  }, [svgRef, state]);

  /**
   * Pan and wheel fire far faster than the screen refreshes, and each event
   * used to write the transform and every label opacity. At most one paint per
   * frame; the camera is read at paint time, so the last event still wins.
   */
  const applyCam = useCallback(() => {
    if (state.camRaf) return;
    state.camRaf = requestAnimationFrame(() => {
      state.camRaf = 0;
      paintCam();
    });
  }, [state, paintCam]);

  const flyTo = useCallback(
    (wx, wy, k, dur = 520) => {
      const svg = svgRef.current;
      if (!svg) return;
      const r = svg.getBoundingClientRect();
      state.cancelTween();
      state.cancelTween = tween(
        state.cam,
        { x: r.width / 2 - wx * k, y: r.height / 2 - wy * k, k },
        dur,
        applyCam,
      );
    },
    [svgRef, state, applyCam],
  );

  const fitTo = useCallback(
    (ids, pad = 150, dur = 560, maxK = 2.4) => {
      const svg = svgRef.current;
      if (!svg) return;
      const r = svg.getBoundingClientRect();
      const pts = ids.map((i) => state.pos[i]).filter(Boolean);
      if (!pts.length) return;
      const x0 = Math.min(...pts.map((p) => p.x)) - pad;
      const x1 = Math.max(...pts.map((p) => p.x)) + pad;
      const y0 = Math.min(...pts.map((p) => p.y)) - pad;
      const y1 = Math.max(...pts.map((p) => p.y)) + pad;
      const k = Math.min(
        maxK,
        Math.max(0.15, Math.min(r.width / (x1 - x0), r.height / (y1 - y0))),
      );
      flyTo((x0 + x1) / 2, (y0 + y1) / 2, k, dur);
    },
    [svgRef, state, flyTo],
  );

  const fit = useCallback(() => {
    const ids = model.nodes.map((n) => n.doc_id);
    if (ids.length) fitTo(ids, 130, 620);
  }, [model, fitTo]);

  /** Zoom about the middle of the window, the way the buttons imply. */
  const zoomBy = useCallback(
    (f) => {
      const svg = svgRef.current;
      if (!svg) return;
      const r = svg.getBoundingClientRect();
      const k = Math.min(6, Math.max(0.15, state.cam.k * f));
      // the world point currently under the centre of the window
      const wx = (r.width / 2 - state.cam.x) / state.cam.k;
      const wy = (r.height / 2 - state.cam.y) / state.cam.k;
      flyTo(wx, wy, k, 220);
    },
    [svgRef, state, flyTo],
  );

  /**
   * Everything a selection changes, written onto the scene that already exists.
   *
   * Hover, selection and search come here, never to render: rebuilding every
   * hull, edge, node and label (and their listeners) on each one made a
   * three-paper canvas lag. Nothing here touches DOM structure.
   */
  const restyle = useCallback(() => {
    const { nodes, edges, gapEdges, gapNodes } = state.paint;
    const searching = matches.size > 0;
    // The hover handlers read this rather than closing over `matches`.
    state.searching = searching;
    // A gap names its neighbourhood; a paper's has to be read off the edges.
    const cited = citedBy(model, focus);
    const neighbours = new Set(cited || []);
    if (focus && !cited)
      localGraph(focus, model.edges, depth).forEach((hop, id) => {
        if (hop > 0) neighbours.add(id);
      });

    const alpha = makeAlpha(matches, focus, neighbours);
    // The red pen marks what the reader must act on, and a live selection is
    // exactly that. It is the only red on the plate apart from the gaps.
    const hit = colors.mark || colors.accent;
    // Territory ink, resolved during render. Before the first render there is
    // none, so fall back to plain ink rather than drawing nothing.
    const inkOf = state.paint.inkOf || (() => colors['ink-3'] || colors['text-3']);

    nodes.forEach((n) => {
      const m = matches.get(n.id);
      const pigment = inkOf(n.id);
      n.g.style.opacity = alpha(n.id);
      // A point of light: filled in its territory's pencil. Focus and match
      // take the red pen; everything else stays the colour of its theme.
      n.circle.setAttribute('fill', n.id === focus || m ? hit : pigment);
      n.circle.setAttribute('stroke', 'none');
      // relevance arc. A lasso selection carries no score, so it draws no arc:
      // a full ring on every lassoed node would read as "perfect match". Hidden
      // rather than absent -- a zero-length dash with a round cap is a dot.
      if (m && m.score != null) {
        n.arc.style.display = '';
        n.arc.setAttribute('stroke', hit);
        n.arc.setAttribute('stroke-dasharray', `${Math.round(Math.min(1, m.score) * 100)} 100`);
      } else {
        n.arc.style.display = 'none';
      }
      // Every paper is labelled, so the map is read rather than decoded, and
      // the label is set in the same pencil as the territory it sits in.
      n.label.style.fill = m ? hit : pigment;
    });

    edges.forEach((e) => {
      e.line.style.strokeOpacity = searching
        ? matches.has(e.a) && matches.has(e.b) ? 0.55 : 0.05
        : !focus
          ? e.weight * 0.5
          : edgeLit(e, focus, cited) ? 0.7 : 0.08;
    });

    gapEdges.forEach((line) => {
      line.style.strokeOpacity = searching ? 0.08 : 0.46;
    });

    gapNodes.forEach((gp) => {
      const on = focus === gp.id;
      gp.g.style.opacity = searching
        ? 0.12
        : focus && !on && !gp.doc_ids.includes(focus) ? 0.35 : 1;
      gp.path.setAttribute('fill', on ? (colors.mark || colors.accent) : 'transparent');
      gp.path.setAttribute('fill-opacity', on ? 0.5 : 0.16);
    });
  }, [state, model, matches, focus, colors, depth]);

  // ---- render ----
  const render = useCallback(() => {
    const svg = svgRef.current;
    if (!svg || !colors.accent) return;

    rebuildModel();

    const L = {
      hulls: svg.querySelector('#lg-hulls'),
      edges: svg.querySelector('#lg-edges'),
      nodes: svg.querySelector('#lg-nodes'),
    };
    if (!L.nodes) return;
    Object.values(L).forEach((g) => {
      while (g.firstChild) g.removeChild(g.firstChild);
    });

    // Collected as the scene is built; restyle() and paintCam() write to these
    // instead of searching the document.
    const paint = state.paint;
    paint.nodes = [];
    paint.edges = [];
    paint.gapEdges = [];
    paint.gapNodes = [];
    paint.labels = [];
    // Only the force layout reads this one: a territory has to be re-drawn
    // around its papers as they move, or the outline is describing where they
    // used to be.
    paint.hulls = [];
    paint.zoomEl = document.getElementById('lg-zoom-readout');
    paint.mmVp = document.getElementById('lg-mm-vp');

    // Every label, in world coordinates, in the order it is drawn -- which is
    // also the order it gets to claim its space. Resolved in one pass at the
    // end, because a label cannot know what will be drawn after it.
    const slots = [];

    // ---- what the filters leave out ----
    // Computed once here rather than tested per draw, because the edge pass,
    // the hull pass and the gap pass all need the same answer and an edge to a
    // hidden paper has to go with it.
    const linked = new Set();
    model.edges.forEach((e) => { linked.add(e.source); linked.add(e.target); });
    const hidden = new Set();
    model.nodes.forEach((n) => {
      const orphan = !linked.has(n.doc_id);
      const bare = !n.summary && !n.claims?.length;
      if (orphan && !state.filters.orphans) hidden.add(n.doc_id);
      else if (bare && !state.filters.unanalysed) hidden.add(n.doc_id);
      else if (n.is_encrypted && !state.filters.encrypted) hidden.add(n.doc_id);
    });
    state.paint.hidden = hidden;

    // ---- territories ----
    // The map is a plate gone over with coloured pencil: hue names a theme and
    // nothing else. Three washed pigments cycle across the clusters, and red is
    // never one of them -- it is withheld for the gaps, which is the whole
    // reason it carries when one appears. A paper in no cluster is plain ink.
    const TERRITORY = [colors.slate, colors.moss, colors.ochre].filter(Boolean);
    const territory = {};
    model.themes.forEach((t, i) => {
      const pigment = TERRITORY.length ? TERRITORY[i % TERRITORY.length] : colors['ink-2'];
      t.doc_ids.forEach((d) => { territory[d] = pigment; });
    });
    const inkOf = (id) => territory[id] || colors['ink-3'] || colors['text-3'];
    state.paint.territory = territory;
    state.paint.inkOf = inkOf;

    // theme territories: washed, not filled, and outlined with a solid hairline
    if (state.layers.themes) {
      model.themes.forEach((t, i) => {
        const pts = t.doc_ids.filter((d) => !hidden.has(d)).map((d) => state.pos[d]).filter(Boolean);
        if (!pts.length) return;
        const pigment = TERRITORY.length ? TERRITORY[i % TERRITORY.length] : colors['ink-2'];
        const hull = el('path', {
          d: hullPath(pts),
          fill: pigment,
          'fill-opacity': 0.05,
          stroke: pigment,
          'stroke-opacity': 0.34,
          'stroke-width': 1,
        });
        L.hulls.appendChild(hull);
        const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
        const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
        const R = Math.max(...pts.map((p) => Math.hypot(p.x - cx, p.y - cy))) + 46;
        const lb = el('text', {
          x: cx,
          y: cy + R * 0.82 + 18,
          'text-anchor': 'middle',
          class: 'lg-hull-label',
          fill: pigment,
        });
        lb.textContent = t.label;
        // first in the list: a theme is the macro read, and losing its label
        // costs more than losing one paper title.
        slots.push({ el: lb, text: t.label, x: cx, y: cy + R * 0.82 + 18, kind: 'hull' });
        L.hulls.appendChild(lb);
        paint.hulls.push({
          path: hull, label: lb, doc_ids: t.doc_ids.filter((d) => !hidden.has(d)),
        });
      });
    }

    // similarity edges: fine strokes, drawn in the territory they belong to.
    // An edge inside one theme is that theme's pencil; an edge BETWEEN themes
    // is plain graphite, because it belongs to neither.
    model.edges.forEach((e) => {
      const a = state.pos[e.source];
      const b = state.pos[e.target];
      if (!a || !b) return;
      if (hidden.has(e.source) || hidden.has(e.target)) return;
      const ta = territory[e.source];
      const same = ta && ta === territory[e.target];
      const line = el('line', {
        x1: a.x, y1: a.y, x2: b.x, y2: b.y,
        stroke: same ? ta : (colors['ink-3'] || colors['text-3']),
        // Scaled by the Link thickness control, which centres on 1 so the
        // shipped weights are what the slider's middle draws.
        'stroke-width': (
          (same ? 0.9 + e.weight * 1.4 : 0.8) * (0.3 + state.display.thickness * 1.4)
        ).toFixed(2),
        'stroke-opacity': same ? (0.3 + e.weight * 0.34).toFixed(2) : '0.3',
      });
      line.dataset.a = e.source;
      line.dataset.b = e.target;
      paint.edges.push({ line, a: e.source, b: e.target, weight: e.weight });
      L.edges.appendChild(line);
    });

    // gap evidence edges
    if (state.layers.gaps) {
      model.gaps.forEach((g) => {
        const gp = state.pos[g.gap_id];
        if (!gp) return;
        g.doc_ids.forEach((d) => {
          const p = state.pos[d];
          if (!p || hidden.has(d)) return;
          const line = el('line', {
            x1: gp.x, y1: gp.y, x2: p.x, y2: p.y,
            stroke: colors.mark || colors.accent,
            'stroke-dasharray': '3 3',
          });
          // Tagged rather than stored as a pair: restyle() walks this array
          // expecting bare <line>s, and the force layout only needs to know
          // which two positions each one joins.
          line.dataset.gap = g.gap_id;
          line.dataset.doc = d;
          paint.gapEdges.push(line);
          L.edges.appendChild(line);
        });
      });
    }

    // Paper nodes: points of light, not bubbles. The radius was 11 + chunks/14,
    // which put a 25px disc on a long paper and turned the plate into a bubble
    // chart -- so the labels had to dodge the discs rather than the positions.
    // Size still tracks length, over a much narrower range.
    model.nodes.forEach((n) => {
      const p = state.pos[n.doc_id];
      if (!p) return;
      if (hidden.has(n.doc_id)) return;
      const r = radiusOf(n, model, state.display);
      // outer <g> positions, inner <g> is what any animation may touch --
      // writing `transform` on the positioned group erases the translate.
      const outer = el('g', { transform: `translate(${p.x},${p.y})` });
      const g = el('g', { class: 'lg-node' });
      g.dataset.id = n.doc_id;

      // The target, first so it sits under everything and paints nothing.
      // `fill: transparent` and not `none`: none is not hit-tested.
      // Tagged with the dot's radius so paintCam can hold it at a constant
      // size on screen as the plate zooms.
      const target = el('circle', { r: hitRadius(r), fill: 'transparent' });
      target.dataset.baseR = String(r);
      target.classList.add('lg-hit');
      g.appendChild(target);

      const circle = el('circle', {
        r,
        'stroke-width': 1.6 + Math.min((n.claims?.length || 0), 8) * 0.34,
      });
      g.appendChild(circle);

      // The arc exists for every node and restyle() decides whether it shows.
      // Creating it on match made a search a structural change to the scene.
      const arc = el('circle', {
        r: r + 6,
        fill: 'none',
        'stroke-width': 2.6,
        'stroke-linecap': 'round',
        pathLength: 100,
        transform: 'rotate(-90)',
        'transform-origin': 'center',
      });
      arc.style.display = 'none';
      g.appendChild(arc);

      if (expanded === n.doc_id)
        g.appendChild(
          el('circle', {
            r: r + 7, fill: 'none', stroke: colors.accent,
            'stroke-opacity': 0.32, 'stroke-dasharray': '2 3',
          }),
        );

      // Pinned: put here by hand. A hairline ring in plain ink -- NOT the red
      // pen, which means gap or live selection and would make a tidied map look
      // like a map full of findings.
      if (state.pins[n.doc_id])
        g.appendChild(
          el('circle', {
            r: r + 5, fill: 'none', stroke: colors['ink-3'] || colors['text-3'],
            'stroke-width': 1, 'stroke-opacity': 0.65,
          }),
        );

      const t = el('text', { class: 'lg-label', y: r + 13, 'text-anchor': 'middle' });
      t.textContent = n.title.length > 26 ? n.title.slice(0, 25) + '…' : n.title;
      g.appendChild(t);
      paint.labels.push(t);
      slots.push({
        el: t, text: t.textContent, x: p.x, y: p.y + r + 13,
        kind: 'node', rank: n.deg ?? 0, box: { x: p.x - r, y: p.y - r, w: r * 2, h: r * 2 },
      });
      paint.nodes.push({ id: n.doc_id, g, circle, arc, label: t, baseR: r });
      outer.appendChild(g);
      L.nodes.appendChild(outer);
    });

    // gap nodes -- amber, the only contrast colour on the canvas
    if (state.layers.gaps) {
      model.gaps.forEach((gp) => {
        const p = state.pos[gp.gap_id];
        if (!p) return;
        // A gap is not a warning triangle. It is the reader circling a spot on
        // the plate: a point with two rings drawn round it, so it reads as
        // "look here" rather than as an error the app is reporting.
        const red = colors.mark || colors.accent;
        const s = gp.severity === 'high' ? 1.15 : 1;
        const outer = el('g', { transform: `translate(${p.x},${p.y})` });
        const g = el('g', { class: 'lg-node' });
        g.dataset.id = gp.gap_id;
        g.dataset.gap = '1';
        // `tri` keeps its name because restyle() fills it to show focus; it is
        // the centre point now rather than a triangle.
        const tri = el('circle', { r: 5 * s, stroke: red, 'stroke-width': 1.3 });
        // The rings are stroke-only, so without this the inside of a gap --
        // the part that most obviously reads as "the gap" -- is not clickable.
        const gapTarget = el('circle', { r: 17 * s, fill: 'transparent' });
        gapTarget.dataset.baseR = String(7 * s);
        gapTarget.classList.add('lg-hit');
        g.appendChild(gapTarget);
        g.appendChild(el('circle', {
          r: 17 * s, fill: 'none', stroke: red, 'stroke-width': 1.3, 'stroke-opacity': 0.8,
        }));
        g.appendChild(el('circle', {
          r: 31 * s, fill: 'none', stroke: red, 'stroke-width': 1, 'stroke-opacity': 0.4,
        }));
        g.appendChild(tri);
        const t = el('text', { class: 'lg-label lg-gap-label', y: 31 * s + 15, 'text-anchor': 'middle' });
        t.textContent = 'gap';
        t.style.fill = red;
        g.appendChild(t);
        paint.labels.push(t);
        slots.push({
          el: t, text: 'gap', x: p.x, y: p.y + 31 * s + 15, kind: 'gap',
          box: { x: p.x - 31 * s, y: p.y - 31 * s, w: 62 * s, h: 62 * s },
        });
        paint.gapNodes.push({ id: gp.gap_id, g, path: tri, doc_ids: gp.doc_ids });
        outer.appendChild(g);
        L.nodes.appendChild(outer);
      });
    }

    // claim sub-nodes, fanned away from the parent's neighbours
    if (expanded) {
      const n = model.nodes.find((x) => x.doc_id === expanded);
      const o = state.pos[expanded];
      if (n && o && n.claims?.length) {
        const claims = n.claims.slice(0, 8);
        let ax = 0;
        let ay = 0;
        model.edges.forEach((e) => {
          if (e.source === expanded && state.pos[e.target]) {
            ax += state.pos[e.target].x - o.x; ay += state.pos[e.target].y - o.y;
          }
          if (e.target === expanded && state.pos[e.source]) {
            ax += state.pos[e.source].x - o.x; ay += state.pos[e.source].y - o.y;
          }
        });
        const away = Math.atan2(-ay, -ax) || 0;
        const R = 78 + claims.length * 7;
        const spread = Math.min(Math.PI * 1.5, claims.length * 0.42);
        claims.forEach((cl, i) => {
          const a =
            away - spread / 2 +
            (claims.length === 1 ? spread / 2 : (spread * i) / (claims.length - 1));
          const x = o.x + Math.cos(a) * R;
          const y = o.y + Math.sin(a) * R;
          L.edges.appendChild(
            // A claim is content, not something to act on, so it is drawn in
            // graphite. Only the gaps and the live selection get the red pen.
            el('line', {
              x1: o.x, y1: o.y, x2: x, y2: y,
              stroke: colors['ink-3'] || colors['text-3'], 'stroke-opacity': 0.4,
              'stroke-width': 1, 'stroke-dasharray': '2 3',
            }),
          );
          const outer = el('g', { transform: `translate(${x},${y})` });
          const g = el('g', { class: 'lg-node' });
          g.dataset.claim = String(i);
          g.dataset.id = expanded;
          g.appendChild(
            el('circle', {
              r: 5, fill: colors.sheet || colors.surface,
              stroke: colors['ink-3'] || colors['text-3'],
              'stroke-width': 1.2, 'stroke-opacity': 0.8,
            }),
          );
          const t = el('text', { class: 'lg-label lg-sub', y: 18, 'text-anchor': 'middle' });
          t.textContent = (cl.type || cl.claim_type || 'claim').replace(/_/g, ' ');
          t.style.fill = colors['text-3'];
          g.appendChild(t);
          paint.labels.push(t);
          slots.push({ el: t, text: t.textContent, x, y: y + 18, kind: 'claim' });
          outer.appendChild(g);
          L.nodes.appendChild(outer);
        });
      }
    }

    // hover: dim everything non-adjacent. the single biggest legibility win.
    L.nodes.querySelectorAll('.lg-node').forEach((g) => {
      const id = g.dataset.id;
      g.addEventListener('mouseenter', () => {
        // Read through `state`, not the closure: these listeners are attached
        // once per structural render, and a selection no longer rebuilds the
        // scene, so a captured `matches` would be the one from build time.
        if (!id || state.searching) return;
        const near = new Set([id]);
        model.edges.forEach((e) => {
          if (e.source === id) near.add(e.target);
          if (e.target === id) near.add(e.source);
        });
        model.gaps.forEach((gp) => {
          if (gp.gap_id === id) gp.doc_ids.forEach((d) => near.add(d));
          if (gp.doc_ids.includes(id)) near.add(gp.gap_id);
        });
        L.nodes.querySelectorAll('.lg-node').forEach((o) => {
          o.style.opacity = !o.dataset.id || near.has(o.dataset.id) ? 1 : 0.22;
        });
        // The edges too, and by the same rule the click path uses -- hovering a
        // gap that brightened its papers while leaving the lines between them
        // dark showed the members and hid the relation.
        const cited = citedBy(model, id);
        state.paint.edges.forEach((e) => {
          e.line.style.strokeOpacity = edgeLit(e, id, cited) ? 0.7 : 0.08;
        });
      });
      g.addEventListener('mouseleave', () => {
        if (!state.searching) state.restyle();
      });
      g.addEventListener('click', (ev) => {
        ev.stopPropagation();
        onSelect(id, g.dataset.claim ? Number(g.dataset.claim) : null, !!g.dataset.gap);
      });
    });

    // Hide any label that would land on one already placed. The server spaces
    // the nodes (graph_builder.MIN_SEP); it cannot know how wide a title is.
    state.paint.slots = slots;
    state.band = -1;               // force a placement pass for the current zoom

    // The scene is built unstyled; this is what colours and dims it.
    state.restyle();
    paintCam();
  }, [svgRef, colors, expanded, model, state, onSelect, rebuildModel, paintCam]);

  // Assigned before the render effect below, because render() calls it on the
  // scene it has just built.
  useEffect(() => { state.restyle = restyle; }, [restyle, state]);

  // Structural: the scene is rebuilt only when the graph, the expanded node or
  // the theme changes. Selecting a node no longer lands here.
  useEffect(() => { render(); }, [render]);

  useEffect(() => { restyle(); }, [restyle]);

  // ---- the force layout ----
  //
  // Everything here is off unless `state.blend > 0`. At the Meaning end the
  // dial costs one branch and never starts a frame loop.

  const stopSim = useCallback(() => {
    if (state.simRaf) cancelAnimationFrame(state.simRaf);
    state.simRaf = 0;
  }, [state]);

  /**
   * Run until the heat is gone, then stop and re-render once.
   *
   * The final render is not cosmetic: reposition() deliberately leaves the
   * label collision pass alone while things are moving, so the scene that has
   * just settled is still wearing the label decisions from where the papers
   * used to be. One structural rebuild resolves them against the new layout.
   */
  const startSim = useCallback(() => {
    if (state.simRaf || state.blend <= 0) return;
    if (!state.sim) {
      // Seeded from the projection and carrying it as `home`, so the anchor
      // has somewhere to pull back to. Footprints go in with it: the collision
      // reserves the title's width, not the dot's.
      state.sim = seedForces(model.nodes.map((n) => n.doc_id), state.pos, footprints());
      state.simLinks = linkForces(state.sim, model.edges);
      // A pin placed before the simulation existed still holds.
      state.sim.forEach((p) => {
        const at = state.pins[p.id];
        if (at) { p.x = at.x; p.y = at.y; p.fx = at.x; p.fy = at.y; }
      });
    }
    if (!state.sim.length) return;

    const frame = () => {
      state.alpha *= ALPHA_DECAY;
      stepForces(
        state.sim,
        state.simLinks,
        { ...state.forces, anchor: anchorFor(state.blend) },
        state.alpha,
      );
      state.sim.forEach((p) => {
        const at = state.pos[p.id];
        if (at) { at.x = p.x; at.y = p.y; }
      });
      placeGaps();
      reposition();
      if (state.alpha > ALPHA_MIN && state.blend > 0) {
        state.simRaf = requestAnimationFrame(frame);
      } else {
        state.simRaf = 0;
        render();
        // The relaxed layout is a different SIZE, not just a different shape:
        // the springs pull to `distance` and a small library settles into a
        // knot a fraction of the plate. Without this the switch reads as
        // "everything ran away into the corner". Once only, on the first
        // settle after the switch -- refitting after every drag would yank the
        // camera out from under the hand doing the dragging.
        if (state.fitOnSettle) {
          state.fitOnSettle = false;
          fit();
        }
      }
    };
    state.simRaf = requestAnimationFrame(frame);
  }, [state, model, placeGaps, reposition, render, fit, footprints]);

  /** Put heat back in. Any change to the forces, and every node grab. */
  const reheat = useCallback(
    (to = 1) => {
      state.alpha = Math.max(state.alpha, to);
      startSim();
    },
    [state, startSim],
  );

  // Nothing may outlive the component. A rAF holding a closure over `model`
  // after unmount is the classic way a canvas keeps a whole graph payload alive.
  useEffect(() => stopSim, [stopSim]);

  // ---- pan / zoom / lasso ----
  //
  // `graph` is in the dep list for a reason that is not obvious: LitGraph
  // early-returns a loading state, so on the first render there is no <svg>
  // yet and svgRef.current is null. Every other dep here is a stable ref, so
  // without `graph` this effect would run exactly once -- against nothing --
  // and pan/zoom/lasso would be dead for the life of the component.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    let drag = null;
    let loop = null;
    let pin = null;
    let pinId = null;
    let armed = null;
    const lassoEl = svg.querySelector('#lg-lasso');

    const toWorld = (e) => {
      const r = svg.getBoundingClientRect();
      return {
        x: (e.clientX - r.left - state.cam.x) / state.cam.k,
        y: (e.clientY - r.top - state.cam.y) / state.cam.k,
      };
    };

    const down = (e) => {
      state.cancelTween();
      const g = gestureFor(e);
      // A press on a paper is a CANDIDATE drag, and nothing more until the
      // pointer has actually moved. A click and a drag begin with identical
      // events, so committing on pointerdown made every click a zero-distance
      // drag: it pinned the paper where it already was, and the pin's own
      // re-render then replaced the element between pointerup and click, so
      // the selection click had nothing left to land on and papers stopped
      // being selectable. `armed` is the candidate; `pin` is the commitment.
      //
      // Gaps and claim sub-nodes are excluded: both are placed FROM the papers
      // they belong to, so dragging one would be dragging a derived value.
      if (g === 'node') {
        const hit = e.target.closest('.lg-node');
        if (!hit || hit.dataset.gap || hit.dataset.claim) return;
        const id = hit.dataset.id;
        if (!id || !state.pos[id]) return;
        armed = { id, at: toWorld(e), pointerId: e.pointerId };
        return;
      }
      if (g === 'none') return;
      if (g === 'pan') {
        drag = { x: e.clientX, y: e.clientY, cx: state.cam.x, cy: state.cam.y };
        svg.style.cursor = 'grabbing';
      } else {
        loop = [toWorld(e)];
        if (lassoEl) { lassoEl.style.display = ''; lassoEl.setAttribute('d', ''); }
      }
      svg.setPointerCapture(e.pointerId);
    };
    const move = (e) => {
      // Far enough to mean it? Same threshold the lasso uses to decide a point
      // is worth keeping: four screen pixels, at any zoom.
      if (armed && !pinId) {
        const w = toWorld(e);
        if (!lassoFar(armed.at, w, state.cam.k)) return;
        pinId = armed.id;
        pin = state.sim?.find((p) => p.id === pinId) || null;
        svg.setPointerCapture(armed.pointerId);
        armed = null;
      }
      if (pinId) {
        const w = toWorld(e);
        if (pin) { pin.fx = w.x; pin.fy = w.y; }
        state.pins[pinId] = { x: w.x, y: w.y };
        if (state.blend > 0) reheat(0.3);
        else {
          // Nothing is running to move the scene, so move it here.
          const at = state.pos[pinId];
          if (at) { at.x = w.x; at.y = w.y; }
          placeGaps();
          reposition();
        }
        return;
      }
      if (loop) {
        const p = toWorld(e);
        // A slow drag fires hundreds of moves a second. Without this the path
        // grows unbounded and the whole `d` string is rebuilt on every one of
        // them; 4px costs nothing visible at any zoom the lasso is used at.
        if (!lassoFar(loop[loop.length - 1], p, state.cam.k)) return;
        loop.push(p);
        lassoEl?.setAttribute(
          'd',
          loop.map((q, i) => (i ? 'L' : 'M') + q.x.toFixed(1) + ' ' + q.y.toFixed(1)).join(' ') + ' Z',
        );
        return;
      }
      if (!drag) return;
      state.cam.x = drag.cx + (e.clientX - drag.x);
      state.cam.y = drag.cy + (e.clientY - drag.y);
      applyCam();
    };
    const up = () => {
      // A press that never moved: not a drag, so nothing was pinned and nothing
      // is saved. The node's own click listener does the selecting, exactly as
      // it always did.
      armed = null;
      if (pinId) {
        // Dropped, and it STAYS. Obsidian releases on drop; here a paper you
        // have moved is your arrangement of the map, and an arrangement that
        // springs back the moment you let go is not one. It is marked pinned on
        // the plate and written to localStorage, so it survives the dial, a
        // reload and the next ingest. Double-click, or Unpin all, undoes it.
        savePins(state.pins);
        pin = null;
        pinId = null;
        renderRef.current();
        if (state.blend > 0) reheat(0.25);
        return;
      }
      if (loop) {
        const poly = loop;
        loop = null;
        if (lassoEl) lassoEl.style.display = 'none';
        if (poly.length >= 4) {
          const picked = model.nodes
            .map((n) => n.doc_id)
            .filter((id) => state.pos[id] && inside(state.pos[id], poly));
          onLasso(picked);
        }
      }
      drag = null;
      svg.style.cursor = 'grab';
    };
    const wheel = (e) => {
      e.preventDefault();
      state.cancelTween();
      const r = svg.getBoundingClientRect();
      const mx = e.clientX - r.left;
      const my = e.clientY - r.top;
      const k2 = Math.min(6, Math.max(0.15, state.cam.k * (e.deltaY < 0 ? 1.12 : 1 / 1.12)));
      state.cam.x = mx - (mx - state.cam.x) * (k2 / state.cam.k);
      state.cam.y = my - (my - state.cam.y) * (k2 / state.cam.k);
      state.cam.k = k2;
      applyCam();
    };

    // Keep the view centred on the same content when the canvas resizes.
    //
    // The camera is in SCREEN space: cam.x/y is where world (0,0) sits on
    // the window. Nothing recomputed it when the container changed size, so
    // the graph drifted off-centre on any window resize -- and once the
    // sidebar can collapse, on every toggle. Pointer maths never suffered,
    // because each event re-reads the rect, which is why this went unseen.
    //
    // Holding the centre world point fixed means shifting cam by half the
    // size delta:  (w/2 - cam.x)/k  is invariant when cam.x += (w1-w0)/2.
    let lastRect = svg.getBoundingClientRect();
    const ro = new ResizeObserver(() => {
      const r = svg.getBoundingClientRect();
      if (!r.width || !r.height) return;            // hidden: nothing to do
      if (r.width === lastRect.width && r.height === lastRect.height) return;
      state.cancelTween();
      state.cam.x += (r.width - lastRect.width) / 2;
      state.cam.y += (r.height - lastRect.height) / 2;
      lastRect = r;
      applyCam();
    });
    ro.observe(svg);
    
    // Double-click releases a pinned paper. The pin is the only thing on this
    // map you can put somewhere by hand, so it needs an undo that is not a trip
    // to the settings panel.
    const dbl = (e) => {
      const hit = e.target.closest?.('.lg-node');
      const id = hit?.dataset.id;
      if (!id || !state.pins[id]) return;
      delete state.pins[id];
      const p = state.sim?.find((q) => q.id === id);
      if (p) { p.fx = null; p.fy = null; }
      savePins(state.pins);
      if (state.blend > 0) reheat(0.4);
      else { rebuildModel(); renderRef.current(); }
    };

    svg.addEventListener('dblclick', dbl);
    svg.addEventListener('pointerdown', down);
    svg.addEventListener('pointermove', move);
    svg.addEventListener('pointerup', up);
    svg.addEventListener('wheel', wheel, { passive: false });
    return () => {
      ro.disconnect();
      svg.removeEventListener('dblclick', dbl);
      svg.removeEventListener('pointerdown', down);
      svg.removeEventListener('pointermove', move);
      svg.removeEventListener('pointerup', up);
      svg.removeEventListener('wheel', wheel);
      if (state.camRaf) cancelAnimationFrame(state.camRaf);
      state.camRaf = 0;
    };
    // state and model are the in-place containers documented at the top.
    // eslint-disable-next-line react-hooks/refs
  }, [svgRef, state, model, applyCam, onLasso, graph, reheat, placeGaps, reposition, rebuildModel]);

  // `render` is rebuilt when the graph, the expanded node or the theme colours
  // change. Closing over it directly would make setLayer — and therefore the
  // whole returned handle — change with it, re-triggering callers' effects. Go
  // through a ref so the callback identity is stable but the behaviour is
  // always current.
  const renderRef = useRef(render);
  useEffect(() => { renderRef.current = render; }, [render]);

  const setLayer = useCallback(
    (name, on) => { state.layers[name] = on; renderRef.current(); },
    [state],
  );

  /**
   * Move the dial.
   *
   * At 0 the simulation is not merely idle, it is not the source of the
   * positions at all: rebuildModel writes the projection back and the map is
   * exactly what the backend computed, which is the state it has to be
   * possible to return to exactly. Above 0 the anchor is recomputed from the
   * dial on every tick, so dragging the slider re-relaxes live.
   *
   * The camera refits once when leaving 0 and once on arriving back, because
   * the relaxed layout is a different SIZE and not just a different shape --
   * without it the switch reads as "everything ran away".
   */
  const setBlend = useCallback(
    (value) => {
      const next = Math.min(Math.max(value, 0), 1);
      const wasOff = state.blend <= 0;
      state.blend = next;

      if (next <= 0) {
        stopSim();
        state.alpha = 0;
        state.sim = null;
        state.simLinks = null;
        renderRef.current();
        fit();
        return;
      }
      if (wasOff) state.fitOnSettle = true;
      // Re-heat rather than restart: sliding the dial should nudge the layout
      // it already has, not throw it in the air and settle it again.
      state.alpha = Math.max(state.alpha, wasOff ? 1 : 0.5);
      startSim();
    },
    [state, stopSim, startSim, fit],
  );

  /** Let a paper go, and forget where it was put. */
  const unpin = useCallback(
    (id) => {
      delete state.pins[id];
      const p = state.sim?.find((q) => q.id === id);
      if (p) { p.fx = null; p.fy = null; }
      savePins(state.pins);
      if (state.blend > 0) reheat(0.4);
      else renderRef.current();
    },
    [state, reheat],
  );

  /** Put the whole hand-arranged map back in the simulation's hands. */
  const unpinAll = useCallback(() => {
    state.pins = {};
    state.sim?.forEach((p) => { p.fx = null; p.fy = null; });
    savePins(state.pins);
    if (state.blend > 0) reheat(0.7);
    else { renderRef.current(); fit(); }
  }, [state, reheat, fit]);

  /** One force slider moved. Anything that changes the field puts heat back in. */
  const setForce = useCallback(
    (name, value) => {
      state.forces[name] = value;
      if (state.blend > 0) reheat(0.6);
    },
    [state, reheat],
  );

  /** A filter changed which papers are on the plate. Structural: rebuild. */
  const setFilter = useCallback(
    (name, on) => { state.filters[name] = on; renderRef.current(); },
    [state],
  );

  /**
   * A display control changed. Label fade is the one that is NOT structural --
   * it is a property of the camera paint, so moving that slider must not tear
   * down and rebuild a scene of several hundred elements per pointer event.
   */
  const setDisplay = useCallback(
    (name, value) => {
      state.display[name] = value;
      if (name === 'fade') paintCam();
      else renderRef.current();
    },
    [state, paintCam],
  );

  /**
   * Stable handle. This MUST be memoised: callers put it in effect dependency
   * lists, and a fresh object each render made the search effect re-run every
   * time — which called setMatches(new Map()) and silently wiped any lasso
   * selection the moment it was made. Every member here is itself stable
   * (useCallback, or a ref object mutated in place).
   */
  /* eslint-disable react-hooks/refs -- state is the in-place container
     documented at the top of the hook; its identity never changes */
  return useMemo(
    () => ({
      fit, flyTo, fitTo, zoomBy, pos: state.pos, setLayer,
      setBlend, setForce, setFilter, setDisplay, unpin, unpinAll,
      forces: state.forces, filters: state.filters, display: state.display,
      pins: state.pins,
      W, H,
    }),
    [
      fit, flyTo, fitTo, zoomBy, setLayer, setBlend, setForce, setFilter, setDisplay,
      unpin, unpinAll, state,
    ],
  );
  /* eslint-enable react-hooks/refs */
}
