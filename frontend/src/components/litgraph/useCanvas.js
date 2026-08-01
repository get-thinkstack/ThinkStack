import { useEffect, useRef, useCallback, useMemo } from 'react';

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

export default function useCanvas({
  svgRef,
  graph,
  colors,
  matches,
  focus,
  expanded,
  onSelect,
  onLasso,
}) {
  const state = useRef({
    cam: { x: 0, y: 0, k: 1 },
    pos: {},
    layers: { themes: true, gaps: true },
    cancelTween: () => {},
  }).current;

  // ---- derived lookups, rebuilt whenever the graph payload changes ----
  const model = useRef({ nodes: [], edges: [], themes: [], gaps: [] }).current;

  useEffect(() => {
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
    // Gaps have no embedding of their own, so they are placed at the centroid
    // of the papers they cite. That is also what makes them *look* like a
    // property of a region rather than a separate kind of object floating free.
    model.gaps.forEach((g) => {
      const pts = g.doc_ids.map((d) => state.pos[d]).filter(Boolean);
      if (!pts.length) return;
      state.pos[g.gap_id] = {
        x: pts.reduce((s, p) => s + p.x, 0) / pts.length,
        y: pts.reduce((s, p) => s + p.y, 0) / pts.length - 70,
      };
    });
  }, [graph, model, state]);

  const applyCam = useCallback(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const vp = svg.querySelector('#lg-viewport');
    if (!vp) return;
    const { x, y, k } = state.cam;
    vp.setAttribute('transform', `translate(${x},${y}) scale(${k})`);
    // semantic zoom: hulls are a macro read and only add noise once you are
    // inside a cluster.
    const hulls = svg.querySelector('#lg-hulls');
    if (hulls)
      hulls.style.opacity = state.layers.themes
        ? k < 1.6
          ? 1
          : Math.max(0, 1 - (k - 1.6))
        : 0;
    svg.querySelectorAll('.lg-label').forEach((t) => {
      t.style.opacity = k < 0.5 ? 0 : Math.min(1, (k - 0.5) * 3);
    });
  }, [svgRef, state]);

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

  // ---- render ----
  const render = useCallback(() => {
    const svg = svgRef.current;
    if (!svg || !colors.accent) return;

    const L = {
      hulls: svg.querySelector('#lg-hulls'),
      edges: svg.querySelector('#lg-edges'),
      nodes: svg.querySelector('#lg-nodes'),
    };
    if (!L.nodes) return;
    Object.values(L).forEach((g) => {
      while (g.firstChild) g.removeChild(g.firstChild);
    });

    const searching = matches.size > 0;
    const neighbours = new Set();
    if (focus)
      model.edges.forEach((e) => {
        if (e.source === focus) neighbours.add(e.target);
        if (e.target === focus) neighbours.add(e.source);
      });

    // One place decides opacity, so the state rules cannot drift apart.
    const alpha = (id) => {
      if (searching) return matches.has(id) ? 1 : 0.15;
      if (!focus) return 1;
      if (id === focus) return 1;
      return neighbours.has(id) ? 0.6 : 0.32;
    };

    // theme hulls
    if (state.layers.themes) {
      model.themes.forEach((t) => {
        const pts = t.doc_ids.map((d) => state.pos[d]).filter(Boolean);
        if (!pts.length) return;
        L.hulls.appendChild(
          el('path', {
            d: hullPath(pts),
            fill: colors.accent,
            'fill-opacity': 0.05,
            stroke: colors.accent,
            'stroke-opacity': 0.22,
            'stroke-width': 1,
            'stroke-dasharray': '5 5',
          }),
        );
        const cx = pts.reduce((s, p) => s + p.x, 0) / pts.length;
        const cy = pts.reduce((s, p) => s + p.y, 0) / pts.length;
        const R = Math.max(...pts.map((p) => Math.hypot(p.x - cx, p.y - cy))) + 46;
        const lb = el('text', {
          x: cx,
          y: cy + R * 0.82 + 18,
          'text-anchor': 'middle',
          class: 'lg-hull-label',
          fill: colors.accent,
        });
        lb.textContent = t.label;
        L.hulls.appendChild(lb);
      });
    }

    // similarity edges
    model.edges.forEach((e) => {
      const a = state.pos[e.source];
      const b = state.pos[e.target];
      if (!a || !b) return;
      const both = matches.has(e.source) && matches.has(e.target);
      const line = el('line', {
        x1: a.x, y1: a.y, x2: b.x, y2: b.y,
        stroke: colors.accent,
        'stroke-width': (e.weight * 3.4).toFixed(1),
      });
      line.style.strokeOpacity = searching
        ? both ? 0.55 : 0.05
        : !focus
          ? e.weight * 0.5
          : e.source === focus || e.target === focus ? 0.7 : 0.08;
      line.dataset.a = e.source;
      line.dataset.b = e.target;
      L.edges.appendChild(line);
    });

    // gap evidence edges
    if (state.layers.gaps) {
      model.gaps.forEach((g) => {
        const gp = state.pos[g.gap_id];
        if (!gp) return;
        g.doc_ids.forEach((d) => {
          const p = state.pos[d];
          if (!p) return;
          const line = el('line', {
            x1: gp.x, y1: gp.y, x2: p.x, y2: p.y,
            stroke: colors.warning,
            'stroke-dasharray': '3 3',
          });
          line.style.strokeOpacity = searching ? 0.08 : 0.46;
          L.edges.appendChild(line);
        });
      });
    }

    // paper nodes. geometry carries the data; colour never does.
    model.nodes.forEach((n) => {
      const p = state.pos[n.doc_id];
      if (!p) return;
      const r = 11 + Math.min(n.chunks, 200) / 14;
      const m = matches.get(n.doc_id);
      // outer <g> positions, inner <g> is what any animation may touch --
      // writing `transform` on the positioned group erases the translate.
      const outer = el('g', { transform: `translate(${p.x},${p.y})` });
      const g = el('g', { class: 'lg-node' });
      g.dataset.id = n.doc_id;
      g.style.opacity = alpha(n.doc_id);

      g.appendChild(
        el('circle', {
          r,
          fill: n.doc_id === focus ? colors.accent : colors.surface,
          stroke: m ? colors['accent-2'] || colors.accent : colors.accent,
          'stroke-width': 1.6 + Math.min((n.claims?.length || 0), 8) * 0.34,
        }),
      );

      // relevance arc. A lasso selection carries no score, so it draws no arc:
      // a full ring on every lassoed node would read as "perfect match".
      if (m && m.score != null) {
        g.appendChild(
          el('circle', {
            r: r + 6,
            fill: 'none',
            stroke: colors['accent-2'] || colors.accent,
            'stroke-width': 2.6,
            'stroke-linecap': 'round',
            pathLength: 100,
            'stroke-dasharray': `${Math.round(Math.min(1, m.score) * 100)} 100`,
            transform: 'rotate(-90)',
            'transform-origin': 'center',
          }),
        );
      }
      if (expanded === n.doc_id)
        g.appendChild(
          el('circle', {
            r: r + 7, fill: 'none', stroke: colors.accent,
            'stroke-opacity': 0.32, 'stroke-dasharray': '2 3',
          }),
        );

      const t = el('text', { class: 'lg-label', y: r + 13, 'text-anchor': 'middle' });
      t.textContent = n.title.length > 26 ? n.title.slice(0, 25) + '…' : n.title;
      t.style.fill = m ? colors['accent-2'] || colors.accent : colors['text-2'];
      g.appendChild(t);
      outer.appendChild(g);
      L.nodes.appendChild(outer);
    });

    // gap nodes -- amber, the only contrast colour on the canvas
    if (state.layers.gaps) {
      model.gaps.forEach((gp) => {
        const p = state.pos[gp.gap_id];
        if (!p) return;
        const s = gp.severity === 'high' ? 13 : 10;
        const outer = el('g', { transform: `translate(${p.x},${p.y})` });
        const g = el('g', { class: 'lg-node' });
        g.dataset.id = gp.gap_id;
        g.dataset.gap = '1';
        g.style.opacity = searching ? 0.12 : focus && focus !== gp.gap_id && !gp.doc_ids.includes(focus) ? 0.35 : 1;
        g.appendChild(
          el('path', {
            d: `M0 ${-s} L${s} ${s * 0.8} L${-s} ${s * 0.8} Z`,
            fill: focus === gp.gap_id ? colors.warning : 'transparent',
            'fill-opacity': focus === gp.gap_id ? 0.5 : 0.16,
            stroke: colors.warning,
            'stroke-width': 2,
            'stroke-linejoin': 'round',
          }),
        );
        const t = el('text', { class: 'lg-label', y: s + 15, 'text-anchor': 'middle' });
        t.textContent = 'gap';
        t.style.fill = colors.warning;
        g.appendChild(t);
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
            el('line', {
              x1: o.x, y1: o.y, x2: x, y2: y,
              stroke: colors.accent, 'stroke-opacity': 0.4,
              'stroke-width': 1, 'stroke-dasharray': '2 3',
            }),
          );
          const outer = el('g', { transform: `translate(${x},${y})` });
          const g = el('g', { class: 'lg-node' });
          g.dataset.claim = String(i);
          g.dataset.id = expanded;
          g.appendChild(
            el('circle', {
              r: 7, fill: colors.surface, stroke: colors.accent,
              'stroke-width': 1.2, 'stroke-opacity': 0.8,
            }),
          );
          const t = el('text', { class: 'lg-label lg-sub', y: 18, 'text-anchor': 'middle' });
          t.textContent = (cl.type || cl.claim_type || 'claim').replace(/_/g, ' ');
          t.style.fill = colors['text-3'];
          g.appendChild(t);
          outer.appendChild(g);
          L.nodes.appendChild(outer);
        });
      }
    }

    // hover: dim everything non-adjacent. the single biggest legibility win.
    L.nodes.querySelectorAll('.lg-node').forEach((g) => {
      const id = g.dataset.id;
      g.addEventListener('mouseenter', () => {
        if (!id || matches.size) return;
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
      });
      g.addEventListener('mouseleave', () => {
        // ponytail: full re-render on hover-out. Fine at this node count; a
        // dim-only path is the upgrade if libraries get into the thousands.
        if (!matches.size) render();
      });
      g.addEventListener('click', (ev) => {
        ev.stopPropagation();
        onSelect(id, g.dataset.claim ? Number(g.dataset.claim) : null, !!g.dataset.gap);
      });
    });

    applyCam();
  }, [svgRef, colors, matches, focus, expanded, model, state, onSelect, applyCam]);

  useEffect(() => { render(); }, [render]);

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
      if (e.shiftKey) {
        loop = [toWorld(e)];
        if (lassoEl) { lassoEl.style.display = ''; lassoEl.setAttribute('d', ''); }
      } else {
        drag = { x: e.clientX, y: e.clientY, cx: state.cam.x, cy: state.cam.y };
        svg.style.cursor = 'grabbing';
      }
      svg.setPointerCapture(e.pointerId);
    };
    const move = (e) => {
      if (loop) {
        loop.push(toWorld(e));
        lassoEl?.setAttribute(
          'd',
          loop.map((p, i) => (i ? 'L' : 'M') + p.x.toFixed(1) + ' ' + p.y.toFixed(1)).join(' ') + ' Z',
        );
        return;
      }
      if (!drag) return;
      state.cam.x = drag.cx + (e.clientX - drag.x);
      state.cam.y = drag.cy + (e.clientY - drag.y);
      applyCam();
    };
    const up = () => {
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

    svg.addEventListener('pointerdown', down);
    svg.addEventListener('pointermove', move);
    svg.addEventListener('pointerup', up);
    svg.addEventListener('wheel', wheel, { passive: false });
    return () => {
      svg.removeEventListener('pointerdown', down);
      svg.removeEventListener('pointermove', move);
      svg.removeEventListener('pointerup', up);
      svg.removeEventListener('wheel', wheel);
    };
  }, [svgRef, state, model, applyCam, onLasso, graph]);

  // `render` is rebuilt whenever matches/focus/expanded change. Closing over it
  // directly would make setLayer — and therefore the whole returned handle —
  // change on every selection, re-triggering callers' effects. Go through a ref
  // so the callback identity is stable but the behaviour is always current.
  const renderRef = useRef(render);
  useEffect(() => { renderRef.current = render; }, [render]);

  const setLayer = useCallback(
    (name, on) => { state.layers[name] = on; renderRef.current(); },
    [state],
  );

  /**
   * Stable handle. This MUST be memoised: callers put it in effect dependency
   * lists, and a fresh object each render made the search effect re-run every
   * time — which called setMatches(new Map()) and silently wiped any lasso
   * selection the moment it was made. Every member here is itself stable
   * (useCallback, or a ref object mutated in place).
   */
  return useMemo(
    () => ({ fit, flyTo, fitTo, pos: state.pos, setLayer, W, H }),
    [fit, flyTo, fitTo, setLayer, state],
  );
}
