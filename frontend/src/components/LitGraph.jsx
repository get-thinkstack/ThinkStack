import { useState, useEffect, useCallback, useRef, useMemo, lazy, Suspense } from 'react';
import {
  Search as SearchIcon, Brain, Lightbulb, Layers, Target, Clock, X,
  Lock, Eye, EyeOff, Maximize2, Plus, Minus, BookOpen, Settings2, Waypoints, Scan,
} from 'lucide-react';
import {
  documentsApi, searchApi, graphApi, analysisApi, gapsApi, useLlmBusy, useJobs,
} from '../utils/api';
import PageHeader from './PageHeader';
import useThemeColors from './charts/useThemeColors';
import useCanvas from './litgraph/useCanvas';
import { clampPanel, gapPassages } from './litgraph/panel';
import { fetchPaper } from './litgraph/paperText';
import PaperPanel from './litgraph/PaperPanel';
import GraphSettings from './litgraph/GraphSettings';
import { earn, EARNED_BY } from '../utils/pigments';
import './litgraph/litgraph.css';

/**
 * LitGraph -- one canvas for the whole middle of the workflow.
 *
 * This replaces three pages (Search, Analysis, Gap Finder). They were three
 * views onto one question: what is in this collection, and what is missing
 * from it. Splitting that across three routes meant the user held the
 * connections in their own head -- which paper a claim came from, which papers
 * a gap was about, whether a theme and a cluster were the same thing.
 *
 * Here the graph *is* the selector. Lasso a region or run a search, and the
 * resulting set is what the analysis actions operate on, so choosing papers
 * and seeing why you chose them are the same gesture.
 */

const RUN_LABELS = { summarize: 'Summary', claims: 'Claims', themes: 'Themes' };
const PANEL_W_KEY = 'lg-panel-w';
const PICKED_KEY = 'lg-has-picked';

// How long an error stays up on its own. Long enough to read a sentence twice;
// short enough that a failure from five minutes ago is not still on the map.
const ERROR_MS = 9000;
let errorSeq = 0;

// Recharts is 300 kB and this chart only appears inside the runs drawer when
// a gap scan has actually produced gaps. Importing it at the top pulled all
// of Recharts into the first paint of the map, which draws its own graph.
const GapSeverityChart = lazy(() => import('./charts/GapSeverityChart'));

export default function LitGraph() {
  const svgRef = useRef(null);
  const colors = useThemeColors();
  const { busy } = useLlmBusy();
  const jobs = useJobs();

  const [graph, setGraph] = useState(null);
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);

  /* Errors are a queue, not a slot.
     It was `useState('')`: the next failure overwrote the previous one before
     it could be read, and the only way out was the × -- so a gap scan that
     failed four ways showed you the fourth. A queue stacks them, drops
     duplicates (a retry loop must not build a wall of the same sentence), and
     lets each one time out on its own while the × still works. */
  const [errors, setErrors] = useState([]);
  const pushError = useCallback((text) => {
    if (!text) return;
    const id = ++errorSeq;
    setErrors((q) => (q.some((e) => e.text === text) ? q : [...q, { id, text }]));
    setTimeout(() => setErrors((q) => q.filter((e) => e.id !== id)), ERROR_MS);
  }, []);
  const dismissError = useCallback(
    (id) => setErrors((q) => q.filter((e) => e.id !== id)), [],
  );

  // canvas state
  const [matches, setMatches] = useState(new Map());
  const [focus, setFocus] = useState(null);
  const [expanded, setExpanded] = useState(null);
  const [panel, setPanel] = useState(null);

  // search
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);

  // runs
  const [runsOpen, setRunsOpen] = useState(false);
  // Where the layout dial sits, and whether the cog is open. The canvas owns
  // the layout; this mirror is only so the dial and the Forces group can render
  // their own state. 0 is the projection, which is what the map opens on.
  const [blend, setBlendState] = useState(0);
  const [cogOpen, setCogOpen] = useState(false);
  // How many papers have been placed by hand. Read off the canvas after any
  // gesture that can change it, so the Unpin all control knows to exist.
  const [pinCount, setPinCount] = useState(0);
  // How far the focused paper's neighbourhood reaches. Lives here rather than
  // in the panel because both the panel's little map and the big canvas read
  // it. 1 is what the map has always dimmed to, so the default is a no-op.
  const [depth, setDepth] = useState(1);
  const [analysisRuns, setAnalysisRuns] = useState([]);
  const [gapRuns, setGapRuns] = useState([]);
  const [openRun, setOpenRun] = useState(null);
  const [running, setRunning] = useState('');

  // encryption gate
  const [pwPrompt, setPwPrompt] = useState(null); // {action}
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);

  const selection = useMemo(() => [...matches.keys()], [matches]);

  // How much of the library the model has actually been through. Papers are
  // analysed at ingest, so on a fresh library this is what says "still working"
  // rather than "there is nothing here".
  const analysed = useMemo(
    () => (graph?.nodes || []).filter((n) => n.summary || n.claims?.length).length,
    [graph],
  );

  const loadGraph = useCallback(async () => {
    try {
      const [g, docs] = await Promise.all([graphApi.get(), documentsApi.list()]);
      const files = docs.documents || [];

      /* A paper whose PDF yielded no title metadata comes back from the API
         titled with its own doc_id (`graph_builder.py`: `meta.get("title") or
         doc_id`), so the canvas labelled it `08688c057d03` -- a hex string, on
         a map whose entire job is to be read at a glance.

         Repaired here rather than at the nine places a title is displayed:
         the canvas label, the search row, the panel heading, the neighbour
         list, the "closest to / furthest from" line and the gap evidence all
         read `node.title`, so fixing the payload once fixes every one of them
         and none of them has to know this can happen. The filename is not on
         the graph node -- chunk metadata does not carry it -- which is why it
         comes from the document list fetched alongside. */
      const name = new Map(files.map((d) => [d.doc_id, d.filename]));
      if (g?.nodes) {
        g.nodes = g.nodes.map((n) =>
          n.title === n.doc_id ? { ...n, title: name.get(n.doc_id) || n.doc_id } : n,
        );
      }

      setGraph(g);
      setDocuments(files);
      // Slate is retrieval, and the map IS retrieval made visible -- but only
      // once there is something on it. An empty map has nothing to colour.
      if (g?.nodes?.length) earn(EARNED_BY.graphOpened);
    } catch (err) {
      pushError(err.message);
    }
    setLoading(false);
  }, [pushError]);

  const loadRuns = useCallback(async () => {
    try {
      const [a, g] = await Promise.all([analysisApi.history(), gapsApi.history()]);
      setAnalysisRuns(a.runs || []);
      setGapRuns(g.runs || []);
    } catch (err) {
      console.error('failed to load run history:', err);
    }
  }, []);

  useEffect(() => { loadGraph(); loadRuns(); }, [loadGraph, loadRuns]);

  // Read the graph through a ref, not the closure.
  //
  // The canvas attaches its click listeners once per STRUCTURAL render, so a
  // handler that closes over `graph` keeps whichever value was current when the
  // scene was built. setFocus(id) needs no graph and therefore always worked --
  // the node ringed and the camera moved -- while the very next line looked the
  // node up in a stale graph, found nothing, and silently opened no panel. The
  // hover handler above already avoids this by reading through `state`; this is
  // the same hazard one function down.
  const graphRef = useRef(graph);
  useEffect(() => { graphRef.current = graph; }, [graph]);

  /* Background analysis keeps landing while the user reads the map. Do NOT
     redraw on it: positions are PCA over the whole library, so one new paper
     moves every node. Instead `stale` counts papers landed since the last
     draw and raises a "rebuild" chip. An empty map draws at once (nothing to
     disturb). The run history is a list, so it refreshes itself. */
  const [stale, setStale] = useState(0);
  const wasBusy = useRef(false);
  const batch = useRef(0);
  useEffect(() => {
    if (jobs.active) batch.current = Math.max(batch.current, jobs.total || 1);
    if (wasBusy.current && !jobs.active) {
      const n = batch.current || 1;
      batch.current = 0;
      loadRuns();
      // An empty map has no place to hold and nothing to disturb, so the first
      // papers of a fresh library draw themselves rather than asking.
      if (!graphRef.current?.nodes?.length) loadGraph();
      else setStale((s) => s + n);
    }
    wasBusy.current = jobs.active;
  }, [jobs.active, jobs.total, loadGraph, loadRuns]);

  const rebuild = useCallback(async () => {
    setStale(0);
    await loadGraph();
  }, [loadGraph]);

  /* Has this install ever selected anything? One flag, one key -- if it has,
     the user knows how, and the first-open picker below never appears again. */
  const [showPicker, setShowPicker] = useState(() => {
    try { return !localStorage.getItem(PICKED_KEY); } catch { return true; }
  });
  const dismissPicker = useCallback(() => {
    setShowPicker(false);
    try { localStorage.setItem(PICKED_KEY, '1'); } catch { /* private mode */ }
  }, []);

  const toggleDoc = useCallback((id) => {
    dismissPicker();
    setMatches((m) => {
      const next = new Map(m);
      // score null, exactly as the lasso does it: a pick is a selection, not a
      // ranking, so the node gets no relevance arc
      if (next.has(id)) next.delete(id); else next.set(id, { doc_id: id, score: null });
      return next;
    });
  }, [dismissPicker]);

  const selectAllPapers = useCallback(() => {
    dismissPicker();
    setMatches(new Map(
      (graphRef.current?.nodes || []).map((n) => [n.doc_id, { doc_id: n.doc_id, score: null }]),
    ));
  }, [dismissPicker]);

  const onSelect = useCallback((id, claimIndex, isGap, seek) => {
    if (!id) return;
    const graph = graphRef.current;
    setFocus(id);
    if (claimIndex != null) {
      const node = graph?.nodes.find((n) => n.doc_id === id);
      const claim = node?.claims?.[claimIndex];
      if (claim) setPanel({ kind: 'claim', claim, node });
      return;
    }
    if (isGap) {
      const gap = graph?.gaps.find((g) => g.gap_id === id);
      if (gap) setPanel({ kind: 'gap', gap });
      return;
    }
    const node = graph?.nodes.find((n) => n.doc_id === id);
    if (!node) return;
    // Arriving with a passage to land on means the reader, opened at it. That
    // is how a gap is followed into the papers it cites.
    if (seek) { setPanel({ kind: 'paper', node, tab: 'read', seek }); return; }
    // Otherwise keep whichever tab is open: following a connection out of the
    // reader is still reading.
    setPanel((p) => ({ kind: 'paper', node, tab: p?.kind === 'paper' ? p.tab : 'about' }));
  }, []);

  const onLasso = useCallback((picked) => {
    // Reuses the same `matches` map search fills, with score null -- a lasso is
    // a selection, not a ranking, so the nodes get no relevance arc.
    setMatches(new Map(picked.map((id) => [id, { doc_id: id, score: null }])));
    setResults([]);
    setPanel(null);
  }, []);

  const canvas = useCanvas({
    svgRef, graph, colors, matches, focus, expanded, onSelect, onLasso, depth,
  });

  /**
   * Flip the layout.
   *
   * The canvas owns the mode; this only mirrors it into React so the switch
   * can ink the live word and the Forces group can disable itself. Kept here
   * rather than inside the switch's onClick because the settings panel offers
   * the same move from its Forces group.
   */
  const slideBlend = useCallback(
    (value) => { setBlendState(value); canvas.setBlend(value); },
    [canvas],
  );

  // The pin count lives on the canvas: it is written by a pointer gesture and
  // read back from localStorage, neither of which goes through React. Pulled
  // across on the gestures that can change it -- a drop, a double-click, and
  // opening the panel that shows it -- rather than mirrored on every drag
  // frame or synchronised in an effect that would cascade a render per load.
  const syncPins = useCallback(
    () => setPinCount(Object.keys(canvas.pins || {}).length),
    [canvas],
  );

  // Clicking a paper frames it WITH the papers it is linked to.
  //
  // The click already selected the node and opened the panel, but the camera
  // never moved, so on a dense graph the only feedback was a panel appearing
  // off to the side -- which reads as "nothing happened". flyTo and fitTo
  // already existed here; the click simply never called them.
  //
  // Fitting the neighbourhood rather than the node alone is the point: this is
  // a graph, and a paper on its own says nothing the Library list does not
  // already say. What is worth zooming to is the cluster it sits in. A paper
  // with no edges still gets framed, just tighter.
  //
  // Keyed on `focus` rather than done inside onSelect, because `canvas` is
  // created below and onSelect is passed INTO it -- calling it from there
  // would be a circular reference.
  const framed = useRef(null);
  useEffect(() => {
    if (!focus || !graph?.nodes?.length) return;
    if (framed.current === focus) return;      // don't re-fit on every re-render
    framed.current = focus;
    const linked = (graph.edges || [])
      .filter((e) => e.source === focus || e.target === focus)
      .map((e) => (e.source === focus ? e.target : e.source));
    // de-duplicated: a pair can be joined by more than one edge
    const ids = [...new Set([focus, ...linked])];
    requestAnimationFrame(() => canvas.fitTo(ids, 180, 520));
  }, [focus, graph, canvas]);

  // fit once the graph first lands
  const fitted = useRef(false);
  useEffect(() => {
    if (graph?.nodes?.length && !fitted.current) {
      fitted.current = true;
      requestAnimationFrame(() => canvas.fit());
    }
  }, [graph, canvas]);

  // ---- search ----
  useEffect(() => {
    if (!query.trim()) { setResults([]); setMatches(new Map()); return; }
    const t = setTimeout(async () => {
      setSearching(true);
      try {
        const data = await searchApi.papers(query, 20);
        const rows = data.results || [];
        setResults(rows);
        setMatches(new Map(rows.map((r) => [r.doc_id, r])));
        if (rows.length) canvas.fitTo(rows.slice(0, 5).map((r) => r.doc_id), 170, 600, 2.4);
      } catch (err) {
        pushError(err.message);
      }
      setSearching(false);
    }, 250);
    return () => clearTimeout(t);
  }, [query, canvas, pushError]);

  // ---- panel width ----
  //
  // The drag writes the CSS variable straight onto the root and never touches
  // React state: the canvas is a few hundred imperative SVG nodes, and putting
  // a pointermove through the reconciler to move one grid track would rebuild
  // the tree at 60fps to do it. The camera takes care of itself -- the
  // ResizeObserver in useCanvas already re-centres on a container resize.
  // A callback ref, not an effect: the loading and empty states return before
  // .lg-root exists, so an effect keyed on mount would run while the ref is
  // still null and the saved width would be dropped on every cold load.
  const rootRef = useRef(null);
  const setRoot = useCallback((el) => {
    rootRef.current = el;
    const saved = el && localStorage.getItem(PANEL_W_KEY);
    if (saved) el.style.setProperty('--lg-panel-w', saved);
  }, []);

  const onGrip = (e) => {
    e.preventDefault();
    const grip = e.currentTarget;
    grip.classList.add('is-dragging');
    const move = (ev) => {
      const w = clampPanel(window.innerWidth - ev.clientX, window.innerWidth);
      rootRef.current?.style.setProperty('--lg-panel-w', `${w}px`);
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      grip.classList.remove('is-dragging');
      const w = rootRef.current?.style.getPropertyValue('--lg-panel-w');
      if (w) localStorage.setItem(PANEL_W_KEY, w);
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const clearSelection = () => {
    setQuery(''); setResults([]); setMatches(new Map());
    setFocus(null); setExpanded(null); setPanel(null);
  };

  // ---- runs ----
  const encryptedInSelection = documents.filter(
    (d) => selection.includes(d.doc_id) &&
      (d.metadata?.is_encrypted === 'true' || d.metadata?.is_encrypted === true),
  );

  const doRun = async (action, pw = '') => {
    setRunning(action);
    try {
      let data;
      if (action === 'gaps') data = await gapsApi.analyze(selection, pw);
      else if (action === 'summarize') data = await analysisApi.summarize(selection, pw);
      else if (action === 'claims') data = await analysisApi.extractClaims(selection, pw);
      else if (action === 'themes') data = await analysisApi.clusterThemes(selection, pw);
      setOpenRun({ type: action, result: data, ...data });
      setRunsOpen(true);
      // Moss is evidence: the model has been through the papers and come back
      // with something. Any of the three analyses counts.
      if (action !== 'gaps') earn(EARNED_BY.analysisRun);
      // The red pen is the last thing the app earns, and it is earned only by
      // a scan that FOUND something. A gap scan that comes back empty is a
      // scan that found no gaps -- there is nothing for a red pen to mark.
      if (action === 'gaps' && (data?.gaps?.length ?? 0) > 0) earn(EARNED_BY.gapFound);
      await loadRuns();
      await loadGraph();   // themes/gaps/claims change what the canvas draws
    } catch (err) {
      pushError(err.message);
    }
    setRunning('');
    setPassword('');
    setPwPrompt(null);
  };

  const startRun = (action) => {
    if (action === 'gaps' && selection.length < 2) {
      pushError('Gap analysis needs at least 2 papers selected.');
      return;
    }
    if (!selection.length) return;
    // a locked paper must not be sent to the model without its password
    if (encryptedInSelection.length) { setPwPrompt({ action }); return; }
    doRun(action);
  };

  const deleteRun = async (kind, runId) => {
    try {
      if (kind === 'gaps') await gapsApi.deleteRun(runId);
      else await analysisApi.deleteRun(runId);
      if (openRun?.run_id === runId) setOpenRun(null);
      await loadRuns();
    } catch (err) { pushError(err.message); }
  };

  const fmtDate = (iso) => {
    if (!iso) return 'run';
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? 'run'
      : d.toLocaleString([], { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
  };

  const nodeCount = graph?.nodes?.length || 0;

  // ---- empty states -------------------------------------------------------
  if (loading) {
    return (
      <div className="lg-page">
      <PageHeader
      />
        <div className="lg-empty"><div className="spinner spinner-lg" /><p>Building the map…</p></div>
      </div>
    );
  }
  if (!nodeCount) {
    return (
      <div className="lg-page">
      <PageHeader
      />
        <div className="lg-empty">
        <BookOpen size={44} />
        <h3>Nothing to map yet</h3>
        <p>LitGraph draws your collection in embedding space — papers that argue
          about the same things sit together. Upload a few papers in Library
          and the map builds itself.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="lg-page">
      <PageHeader
      />
      <div ref={setRoot} className={`lg-root ${panel ? 'lg-has-panel' : ''}`}>
      {/* ---------- canvas ---------- */}
      <div className="lg-stage" onPointerUp={syncPins} onDoubleClick={syncPins}>
        {/* The cursor lives in CSS (crosshair, because dragging selects). The
            pointer handlers write it inline from there, which is why there is
            no style prop here -- one would win over the stylesheet forever. */}
        <svg id="lg-canvas" ref={svgRef}>
          <g id="lg-viewport">
            <g id="lg-hulls" />
            <g id="lg-edges" />
            <g id="lg-nodes" />
            <path
              id="lg-lasso" style={{ display: 'none' }} fill={colors.accent}
              fillOpacity="0.05" stroke={colors.accent} strokeWidth="1.4"
              strokeDasharray="5 4" pointerEvents="none"
            />
          </g>
        </svg>

        {/* ---------- top chrome ---------- */}
        <div className="lg-top">
          <div className="lg-search">
            <SearchIcon size={14} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search your library by meaning…"
              aria-label="Semantic search"
              spellCheck="false"
            />
            {searching && <div className="spinner" />}
            {!searching && !!results.length && (
              <span className="lg-qcount">{results.length}</span>
            )}
            {!!query && (
              <button className="lg-x" onClick={clearSelection} title="Clear">
                <X size={14} />
              </button>
            )}
          </div>

          <div className="lg-layers">
            <button className="lg-chip on" onClick={(e) => {
              const on = !e.currentTarget.classList.contains('on');
              e.currentTarget.classList.toggle('on', on);
              canvas.setLayer('themes', on);
            }}>Themes {graph.themes.length ? `· ${graph.themes.length}` : ''}</button>
            <button className="lg-chip on lg-amber" onClick={(e) => {
              const on = !e.currentTarget.classList.contains('on');
              e.currentTarget.classList.toggle('on', on);
              canvas.setLayer('gaps', on);
            }}>Gaps {graph.gaps.length ? `· ${graph.gaps.length}` : ''}</button>
            <button className="lg-chip" onClick={() => { setRunsOpen(true); }}>
              <Clock size={13} /> Runs
            </button>

          </div>

          {/* The layout dial. Not two modes -- one number. At Meaning every
              paper is exactly where the projection put it; sliding towards
              Force loosens the spring that holds it there, so the map declutters
              without ever throwing away what a position means. */}
          <div className="lg-blend">
            <span className={blend <= 0 ? 'is-live' : ''} title="Papers exactly where the projection put them">
              <Scan size={12} /> Meaning
            </span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={blend}
              aria-label="Layout: Meaning to Force"
              aria-valuetext={blend <= 0 ? 'Meaning — the projection' : `${Math.round(blend * 100)}% relaxed`}
              onChange={(e) => slideBlend(parseFloat(e.target.value))}
            />
            <span className={blend >= 1 ? 'is-live' : ''} title="Relax the same papers freely">
              Force <Waypoints size={12} />
            </span>
          </div>

          <button
            className={`lg-cog${cogOpen ? ' on' : ''}`}
            onClick={() => { setCogOpen((o) => !o); syncPins(); }}
            aria-expanded={cogOpen}
            title="Graph settings"
          >
            <Settings2 size={16} />
          </button>

          {/* the library at a glance -- what the map is made of, before you
              touch anything. Sits up here because the bottom of the stage
              belongs to the action bar once anything is selected. */}
          <div className="lg-stats" aria-label="Library at a glance">
            <span><b>{graph.nodes.length}</b> paper{graph.nodes.length === 1 ? '' : 's'}</span>
            <span><b>{graph.edges.length}</b> link{graph.edges.length === 1 ? '' : 's'}</span>
            <span><b>{graph.themes.length}</b> theme{graph.themes.length === 1 ? '' : 's'}</span>
            <span className={graph.gaps.length ? 'lg-amber-t' : ''}>
              <b>{graph.gaps.length}</b> gap{graph.gaps.length === 1 ? '' : 's'}
            </span>
            <span className="lg-stat-sep">·</span>
            <span><b>{analysed}</b>/{graph.nodes.length} analysed</span>
          </div>

          {/* The map holds still; this is how it says it has fallen behind.
              A button and not a banner, because redrawing is a decision --
              every node moves when it happens. */}
          {stale > 0 && !jobs.active && (
            <button className="lg-rebuild" onClick={rebuild}>
              <b>{stale}</b> new paper{stale === 1 ? '' : 's'} · rebuild the map
            </button>
          )}
        </div>

        {cogOpen && (
          <GraphSettings
            canvas={canvas}
            blend={blend}
            onBlend={slideBlend}
            pinCount={pinCount}
            onUnpinAll={() => { canvas.unpinAll(); syncPins(); }}
            onClose={() => setCogOpen(false)}
          />
        )}

        {/* One line, so nobody reads a relaxed layout as the projection. */}
        {blend > 0 && (
          <p className="lg-mode-note">
            <b>{Math.round(blend * 100)}% relaxed</b> — the same papers, loosened
            from where the projection put them. Drag one and it stays put.
          </p>
        )}

        {/* ---------- results list ---------- */}
        {!!results.length && (
          <div className="lg-results">
            <div className="lg-results-head">
              {results.length} paper{results.length === 1 ? '' : 's'} matched
            </div>
            {results.map((r) => (
              <button key={r.doc_id} className={`lg-rrow ${focus === r.doc_id ? 'on' : ''}`}
                onClick={() => {
                  onSelect(r.doc_id);
                  const p = canvas.pos[r.doc_id];
                  if (p) canvas.flyTo(p.x, p.y, 1.8, 420);
                }}>
                <span className="lg-score">{r.score.toFixed(2)}</span>
                <span>
                  <span className="lg-rtitle">{r.title && r.title !== r.doc_id ? r.title : (documents.find((d) => d.doc_id === r.doc_id)?.filename || r.doc_id)}</span>
                  <span className="lg-rmeta">
                    {r.hits.length} matching chunk{r.hits.length === 1 ? '' : 's'}
                    {r.hits[0]?.page ? ` · from p.${r.hits[0].page}` : ''}
                  </span>
                </span>
              </button>
            ))}
          </div>
        )}


        {/* ---------- choosing, for the first time ----------
            With nothing selected the action bar is hidden and nothing on this
            page can be run. The only two ways in were typing a search or
            knowing that shift-drag lassos a region -- one of which is not
            discoverable at all, and the hint line at the bottom was the only
            thing that said so.

            So: a list, in the exact spot the action bar will occupy the moment
            you use it, feeding the same `matches` map the search and the lasso
            already write to. It shows only until the first selection is made
            and then never again, because it is scaffolding for learning the
            gestures, not a second permanent way to work. */}
        {showPicker && !selection.length && (
          <div className="lg-pick">
            <div className="lg-pick-head">
              <span>Choose papers to work on</span>
              <button onClick={selectAllPapers}>Select all {nodeCount}</button>
              <button className="lg-pick-x" onClick={dismissPicker} aria-label="Hide this">
                <X size={13} />
              </button>
            </div>
            <div className="lg-pick-list">
              {graph.nodes.map((n) => (
                <label key={n.doc_id} className="lg-pick-row">
                  <input type="checkbox" checked={false} onChange={() => toggleDoc(n.doc_id)} />
                  <span>{n.title}</span>
                </label>
              ))}
            </div>
            <p className="lg-pick-foot">
              Or drag a box around a region of the map with shift held.
            </p>
          </div>
        )}

        {/* ---------- the selection is what every action runs on ---------- */}
        {selection.length > 0 && (
          <div className="lg-actbar">
            <span>{selection.length} selected</span>
            <button disabled={!!running || busy} onClick={() => startRun('summarize')}>
              <Brain size={13} /> Summarize
            </button>
            <button disabled={!!running || busy} onClick={() => startRun('claims')}>
              <Lightbulb size={13} /> Claims
            </button>
            <button disabled={!!running || busy || selection.length < 2}
              title={selection.length < 2 ? 'Needs at least 2 papers' : ''}
              onClick={() => startRun('themes')}>
              <Layers size={13} /> Themes
            </button>
            <button disabled={!!running || busy || selection.length < 2}
              title={selection.length < 2 ? 'Needs at least 2 papers' : ''}
              onClick={() => startRun('gaps')}>
              <Target size={13} /> Find gaps
            </button>
            {(running || busy) && (
              <span className="lg-busy">
                <div className="spinner" />
                {running ? `Running ${running}…` : 'Model busy elsewhere…'}
              </span>
            )}
          </div>
        )}

        {/* ---------- background analysis progress ----------
            Ingest queues summaries, claims, themes and a gap scan on the
            server, which together run for minutes. A spinner alone is
            indistinguishable from a hang over that long, so when the queue
            knows how many papers it is working through, this is a real bar. */}
        {jobs.active && (
          <div className="lg-jobs" role="status" aria-live="polite">
            <div className="lg-jobs-head">
              <div className="spinner" />
              <span>{jobs.label || 'Analysing your library…'}</span>
              {jobs.total > 1 && (
                <span className="lg-jobs-count">{jobs.done + 1} of {jobs.total}</span>
              )}
            </div>
            {/* Determinate only when the batch size is known. One long opaque
                model call gets the indeterminate bar instead of a bar that
                lies about where it has got to. */}
            {jobs.total > 1 ? (
              <progress className="lg-jobs-bar" value={jobs.done} max={jobs.total} />
            ) : (
              <progress className="lg-jobs-bar" />
            )}
            <div className="lg-jobs-note">
              This runs in the background — you can keep working.
            </div>
          </div>
        )}

        {/* ---------- where you are ----------
            The dots are static: node coordinates only move when the graph
            payload does. The viewport rectangle is written by the canvas's own
            paint, so panning never re-renders this component. */}
        {graph.nodes.length > 1 && (
          <div className="lg-minimap" aria-hidden="true">
            <svg viewBox={`0 0 ${canvas.W} ${canvas.H}`} preserveAspectRatio="xMidYMid meet">
              {graph.nodes.map((n) => {
                const lit = matches.has(n.doc_id) || focus === n.doc_id;
                return (
                  <circle
                    key={n.doc_id}
                    cx={n.x * canvas.W} cy={n.y * canvas.H} r={lit ? 30 : 22}
                    fill={lit ? colors.mark : colors['ink-4']}
                    fillOpacity={lit ? 0.95 : 0.4}
                  />
                );
              })}
              {graph.gaps.map((g) => {
                const p = canvas.pos[g.gap_id];
                return p ? (
                  <circle key={g.gap_id} cx={p.x} cy={p.y} r="20"
                    fill={colors.mark} fillOpacity="0.75" />
                ) : null;
              })}
              <rect
                id="lg-mm-vp" stroke={colors['ink-4']} strokeWidth="11"
                fill={colors['ink-4']} fillOpacity="0.07"
              />
            </svg>
          </div>
        )}

        {/* ---------- zoom ---------- */}
        <div className="lg-zoom">
          <span className="lg-zoom-readout" id="lg-zoom-readout">1.00×</span>
          <button onClick={() => canvas.zoomBy(1.25)} title="Zoom in">
            <Plus size={14} />
          </button>
          <button onClick={() => canvas.zoomBy(1 / 1.25)} title="Zoom out">
            <Minus size={14} />
          </button>
          <button onClick={() => canvas.fit()} title="Fit everything on screen">
            <Maximize2 size={14} />
          </button>
        </div>

        {/* newest at the bottom, nearest the map: the stack grows the way a
            pile of notes grows, and the one that just landed is the one your
            eye is already closest to */}
        {errors.length > 0 && (
          <div className="lg-errors" role="alert">
            {errors.map((e) => (
              <div key={e.id} className="lg-error">
                {e.text}
                <button onClick={() => dismissError(e.id)} aria-label="Dismiss">
                  <X size={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ---------- side panel ---------- */}
      {panel && (
        <div
          className="lg-grip"
          onPointerDown={onGrip}
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize the panel"
        />
      )}
      {panel && (
        <aside className="lg-panel">
          <button className="lg-panel-x" onClick={() => setPanel(null)}><X size={16} /></button>

          {panel.kind === 'paper' && (
            <PaperPanel
              node={panel.node}
              graph={graph}
              matches={matches}
              query={query}
              openAt={panel.seek}
              tab={panel.tab}
              onTab={(tab) => setPanel((p) => ({ ...p, tab }))}
              depth={depth}
              onDepth={setDepth}
              onSelect={onSelect}
              expanded={expanded}
              onExpand={setExpanded}
            />
          )}

          {panel.kind === 'claim' && (
            <>
              <div className="lg-kind">Claim</div>
              <h3>{(panel.claim.type || panel.claim.claim_type || 'claim').replace(/_/g, ' ')}</h3>
              <div className="lg-authors">from {panel.node.title}</div>
              <p>{panel.claim.text || panel.claim.claim_text}</p>
              {panel.claim.supporting_text && <div className="lg-quote"><q>{panel.claim.supporting_text}</q></div>}
              <button className="btn btn-secondary btn-sm"
                onClick={() => setPanel({ kind: 'paper', node: panel.node })}>Back to the paper</button>
            </>
          )}

          {panel.kind === 'gap' && (
            <>
              <div className="lg-kind lg-kind-gap">Gap · {panel.gap.severity} severity</div>
              <h3>{(panel.gap.gap_type || '').replace(/_/g, ' ')}</h3>
              <p>{panel.gap.description}</p>
              {panel.gap.evidence?.length > 0 && (
                <>
                  <h4>Evidence</h4>
                  {panel.gap.evidence.map((e, i) => <div key={i} className="lg-quote"><q>{e}</q></div>)}
                </>
              )}
              <GapPapers
                gap={panel.gap}
                nodes={graph.nodes}
                onOpen={(docId, quote) => onSelect(docId, null, false, quote)}
              />
              {panel.gap.suggestions?.length > 0 && (
                <>
                  <h4>Suggested directions · {panel.gap.suggestions.length}</h4>
                  {panel.gap.suggestions.map((s, i) => (
                    <div key={i} className="lg-sugg">
                      <b>{s.title}</b>{s.description}
                    </div>
                  ))}
                </>
              )}
            </>
          )}
        </aside>
      )}

      {/* ---------- runs drawer ---------- */}
      {runsOpen && (
        <div className="lg-drawer-wrap" onClick={() => setRunsOpen(false)}>
          <aside className="lg-drawer" onClick={(e) => e.stopPropagation()}>
            <div className="lg-drawer-head">
              <span><Clock size={15} /> Runs</span>
              <button onClick={() => setRunsOpen(false)}><X size={16} /></button>
            </div>

            <h4>Past analyses · {analysisRuns.length}</h4>
            {analysisRuns.length === 0 && <p className="lg-muted">Nothing yet.</p>}
            {analysisRuns.map((r) => (
              <div key={r.run_id} className={`lg-run ${openRun?.run_id === r.run_id ? 'on' : ''}`}>
                <button onClick={() => setOpenRun(r)}>
                  <b>{RUN_LABELS[r.type] || r.type}</b>
                  <span>{fmtDate(r.created_at)} · {r.doc_ids?.length || 0} papers</span>
                </button>
                <button className="lg-run-x" onClick={() => deleteRun('analysis', r.run_id)}
                  aria-label="Delete run"><X size={14} /></button>
              </div>
            ))}

            <h4>Past gap scans · {gapRuns.length}</h4>
            {gapRuns.length === 0 && <p className="lg-muted">Nothing yet.</p>}
            {gapRuns.map((r) => (
              <div key={r.run_id} className={`lg-run ${openRun?.run_id === r.run_id ? 'on' : ''}`}>
                <button onClick={() => setOpenRun(r)}>
                  <b>Gap scan</b>
                  <span>{fmtDate(r.created_at)} · {r.total_gaps ?? 0} gaps</span>
                </button>
                <button className="lg-run-x" onClick={() => deleteRun('gaps', r.run_id)}
                  aria-label="Delete run"><X size={14} /></button>
              </div>
            ))}

            {openRun && <RunResult run={openRun} />}
          </aside>
        </div>
      )}

      {/* ---------- password gate ---------- */}
      {pwPrompt && (
        <div className="lg-modal-wrap" onClick={() => setPwPrompt(null)}>
          <div className="lg-modal" onClick={(e) => e.stopPropagation()}>
            <h3><Lock size={16} /> Password required</h3>
            <p>
              {encryptedInSelection.map((d) => d.filename).join(', ')}
              {encryptedInSelection.length === 1 ? ' is' : ' are'} encrypted. The
              password is needed to read the text for this run.
            </p>
            <div className="lg-pw">
              <input type={showPw ? 'text' : 'password'} className="input" value={password}
                autoFocus onChange={(e) => setPassword(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && password && doRun(pwPrompt.action, password)}
                placeholder="Enter encryption password…" />
              <button className="btn-icon" onClick={() => setShowPw(!showPw)}
                aria-label="Toggle password visibility">
                {showPw ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
            <div className="lg-modal-actions">
              <button className="btn btn-secondary" onClick={() => { setPwPrompt(null); setPassword(''); }}>
                Cancel
              </button>
              <button className="btn btn-primary" disabled={!password}
                onClick={() => doRun(pwPrompt.action, password)}>Run</button>
            </div>
          </div>
        </div>
      )}
      </div>
    </div>
  );
}

/** the result of whichever run is open, rendered by type. */
function RunResult({ run }) {
  const res = run.result || run;
  if (run.type === 'summarize') {
    return (
      <div className="lg-runres">
        <h4>Summary</h4>
        {/* Set when the paper had to be summarized in pieces because it did not
            fit this machine's context window. Kept out of summary_text on
            purpose: it is a fact about the machine, not about the paper, and
            must not read as the model's view of the research. */}
        {res.notice && <p className="lg-muted">{res.notice}</p>}
        <p>{res.summary_text}</p>
        {res.key_points?.length > 0 && (
          <ul className="key-points">{res.key_points.map((p, i) => <li key={i}>{p}</li>)}</ul>
        )}
      </div>
    );
  }
  if (run.type === 'claims') {
    return (
      <div className="lg-runres">
        <h4>Claims · {res.total ?? res.claims?.length ?? 0}</h4>
        {(res.claims || []).map((c, i) => (
          <div key={i} className="lg-quote">
            <span className="lg-tag">{c.claim_type || c.type}</span>
            <q>{c.claim_text || c.text}</q>
          </div>
        ))}
      </div>
    );
  }
  if (run.type === 'themes') {
    return (
      <div className="lg-runres">
        <h4>Themes · {res.total ?? res.themes?.length ?? 0}</h4>
        {(res.themes || []).map((t, i) => (
          <div key={i} className="lg-sugg"><b>{t.label}</b>{t.description}</div>
        ))}
      </div>
    );
  }
  // gap scan
  const gaps = res.gaps || [];
  return (
    <div className="lg-runres">
      {gaps.length > 0 && (
        <Suspense fallback={null}><GapSeverityChart gaps={gaps} /></Suspense>
      )}
      <h4>Gaps · {gaps.length}</h4>
      {gaps.map((g, i) => (
        <div key={i} className="lg-sugg">
          <b>{(g.gap_type || '').replace(/_/g, ' ')} · {g.severity}</b>
          {g.description}
        </div>
      ))}
      {gaps.length === 0 && <p className="lg-muted">No significant gaps identified.</p>}
    </div>
  );
}

/**
 * The papers a gap cites, each showing the passage the gap rests on.
 *
 * A gap is a claim ABOUT several papers, so it is shown as the passage it
 * rests on in each one, not as a list of titles that loses the gap on click.
 *
 * The text is fetched through the shared cache, so opening a gap warms the
 * reader for exactly the papers you are about to open from it.
 */
function GapPapers({ gap, nodes, onOpen }) {
  const [texts, setTexts] = useState(new Map());

  useEffect(() => {
    let live = true;
    const ids = gap?.doc_ids || [];
    Promise.all(ids.map((id) => fetchPaper(id).then(
      (doc) => [id, doc.chunks],
      () => null,                       // one unreadable paper is not an error
    ))).then((pairs) => {
      if (live) setTexts(new Map(pairs.filter(Boolean)));
    });
    return () => { live = false; };
  }, [gap]);

  const found = gapPassages(gap, texts);
  if (!found.length) return null;

  return (
    <>
      <h4>Papers · {found.length}</h4>
      {found.map(({ docId, passage }) => {
        const node = nodes.find((n) => n.doc_id === docId);
        if (!node) return null;
        return (
          <div key={docId} className="lg-gap-paper">
            <button
              className="lg-claim"
              disabled={!passage}
              onClick={() => passage && onOpen(docId, passage.quote)}
            >
              {node.title}
            </button>
            {passage
              ? <q className="lg-gap-evidence">{passage.text}</q>
              : (
                // Said plainly rather than hidden: the gap still cites this
                // paper, we just cannot point at where.
                <span className="lg-muted lg-gap-evidence">
                  The evidence could not be located in this paper.
                </span>
              )}
          </div>
        );
      })}
    </>
  );
}
