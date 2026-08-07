import { useEffect, useMemo, useRef, useState } from 'react';
import { targetsFor, findSpan } from './pdfmarks';

/**
 * The paper, drawn by us, with the marks over it.
 *
 * The reader used to be an <iframe> at the browser's own pdf viewer. That shows
 * the paper and nothing else: no dom, no text layer, nothing to draw on. So
 * everything the map knows about a paper -- the passage that matched, the one a
 * claim came from, the one a gap cites -- was visible only in the *text*
 * fallback, the path taken when the pdf is missing. The good reader was the one
 * almost nobody saw.
 *
 * ── Three layers per page ──
 *
 * The canvas is the paper. Over it sits pdf.js's own text layer: transparent
 * glyphs positioned exactly over the painted ones, which is what makes the pdf
 * selectable and searchable with the browser's own find. Over that sit the
 * marker strokes.
 *
 * The strokes are measured with a DOM Range across that text layer rather than
 * computed from text-item geometry. pdf.js hands back one item per typeset run
 * -- often a whole line -- with a single width and no per-glyph metrics, so any
 * position inside an item is an estimate; estimating by character count drew
 * strokes through the middle of words. A Range knows where the glyphs actually
 * are, and `getClientRects` returns one rectangle per line, which is exactly
 * one stroke of a marker per line.
 *
 * ── Why everything is in percent ──
 *
 * The panel is resizable, so the page's width changes under a drag. pdf.js
 * positions the text layer in percentages already, the canvas is `width: 100%`,
 * and the strokes are stored the same way -- so a drag is a reflow. Only the
 * glyph *size* needs the scale factor, which a ResizeObserver keeps current.
 */

// The pdf's own size, times this, is what gets rasterised -- before the device
// pixel ratio. 1.5 keeps small type legible when the panel is narrow.
const RASTER = 1.5;

/**
 * pdf.js, loaded once and only when a paper is actually opened.
 *
 * The worker is imported with `?url` so vite emits it as a local asset. The
 * default build resolves the worker against a cdn, and this app is packaged to
 * run offline -- that would not fail loudly, it would fall back to a bare
 * specifier no browser can resolve. That exact shape of bug already cost this
 * codebase its katex rendering.
 */
let pdfjsPromise = null;
function loadPdfjs() {
  if (!pdfjsPromise) {
    pdfjsPromise = (async () => {
      const [pdfjs, worker] = await Promise.all([
        import('pdfjs-dist/build/pdf.mjs'),
        import('pdfjs-dist/build/pdf.worker.min.mjs?url'),
      ]);
      pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
      return pdfjs;
    })();
  }
  return pdfjsPromise;
}

export default function PdfReader({ url, chunks, spans, seek, onSeeked, legend }) {
  const { pages, error } = usePdfPages(url);
  const bodyRef = useRef(null);

  const targets = useMemo(() => targetsFor(chunks, spans), [chunks, spans]);

  // Scroll to the passage a claim was opened from. Prefers its own stroke; a
  // passage that did not locate still has a page to land on, and the right page
  // beats not moving at all.
  useEffect(() => {
    if (!seek || !pages) return;
    const root = bodyRef.current;
    // Strokes are measured a frame after the page renders, so look on the next
    // one rather than racing them.
    const id = requestAnimationFrame(() => {
      const el = root?.querySelector(`[data-chunk-id="${CSS.escape(seek)}"]`)
        || root?.querySelector(`[data-page="${pageOf(chunks, seek) ?? ''}"]`);
      if (!el) return;
      el.scrollIntoView({ block: 'center', behavior: 'smooth' });
      el.classList.add('lg-chunk-landed');
      onSeeked();
    });
    return () => cancelAnimationFrame(id);
  }, [seek, pages, chunks, onSeeked]);

  if (error) {
    return (
      <div className="lg-tabbody lg-muted">
        <p>Could not open the pdf: {error}</p>
      </div>
    );
  }
  if (!pages) {
    return <div className="lg-tabbody lg-muted"><p>Loading the paper…</p></div>;
  }

  return (
    <div className="lg-tabbody lg-reader-pdf" ref={bodyRef}>
      {legend}
      {pages.map((p) => (
        <Page
          key={p.number}
          page={p.page}
          number={p.number}
          width={p.width}
          height={p.height}
          // A chunk with no recorded page is looked for on every page.
          targets={targets.filter((t) => !t.page || t.page === p.number)}
        />
      ))}
    </div>
  );
}

/** The page a chunk was extracted from, when the chunker recorded one. */
function pageOf(chunks, chunkId) {
  return (chunks || []).find((c) => c.chunk_id === chunkId)?.metadata?.page_number ?? null;
}

/**
 * One page: paper, text, strokes.
 *
 * Rendering and measuring are separate effects on purpose. The marks change
 * whenever the search or the analysis does; the page is rasterised once.
 */
function Page({ page, number, width, height, targets }) {
  const wrapRef = useRef(null);
  const canvasRef = useRef(null);
  const textRef = useRef(null);
  const [drawn, setDrawn] = useState(false);
  const [strokes, setStrokes] = useState([]);

  useEffect(() => {
    let live = true;
    (async () => {
      const pdfjs = await loadPdfjs();
      const scale = RASTER * (window.devicePixelRatio || 1);
      const viewport = page.getViewport({ scale });
      const canvas = canvasRef.current;
      if (!canvas || !live) return;

      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      await page.render({ canvasContext: canvas.getContext('2d'), viewport, canvas }).promise;
      if (!live || !textRef.current) return;

      // Scale 1: pdf.js then lays the layer out in percentages of the page box,
      // which is what lets a panel drag reflow it instead of re-rendering it.
      const layer = new pdfjs.TextLayer({
        textContentSource: page.streamTextContent(),
        container: textRef.current,
        viewport: page.getViewport({ scale: 1 }),
      });
      await layer.render();
      if (live) setDrawn(true);
    })().catch(() => { /* one unreadable page must not take the reader down */ });

    return () => { live = false; };
  }, [page]);

  useEffect(() => {
    if (!drawn) return undefined;
    const wrap = wrapRef.current;
    const text = textRef.current;

    const sync = () => {
      // Positions are percentages, but glyph size is not -- without this the
      // text layer's boxes drift from the painted glyphs as the panel resizes,
      // and the strokes drift with them.
      text.style.setProperty('--total-scale-factor', wrap.clientWidth / width);
      setStrokes(measure(wrap, text, targets));
    };

    sync();
    const ro = new ResizeObserver(sync);
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [drawn, targets, width]);

  return (
    <div
      className="lg-pdf-page"
      data-page={number}
      ref={wrapRef}
      style={{ aspectRatio: `${width} / ${height}` }}
    >
      <canvas ref={canvasRef} />
      <div className="lg-pdf-text" ref={textRef} />
      <div className="lg-pdf-marks">
        {strokes.map((s, i) => (
          <div
            key={i}
            className={`lg-hl lg-hl-${s.kind}`}
            data-chunk-id={s.chunkId}
            style={{ left: s.left, top: s.top, width: s.width, height: s.height }}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * Where each target lands on this page, in percentages of the page box.
 *
 * One rectangle per line, straight from the Range -- which is what a marker
 * does when a sentence wraps.
 */
function measure(wrap, textEl, targets) {
  const { text, map } = indexText(textEl);
  if (!text) return [];
  const box = wrap.getBoundingClientRect();
  if (!box.width || !box.height) return [];

  const out = [];
  for (const t of targets) {
    const at = findSpan(text, t.text);
    if (!at) continue;
    const range = rangeOver(map, at.from, at.to);
    if (!range) continue;

    for (const r of range.getClientRects()) {
      // A zero-width rect is a collapsed line break, not a piece of the
      // sentence, and it would draw as a sliver.
      if (r.width < 1 || r.height < 1) continue;
      out.push({
        kind: t.kind,
        chunkId: t.chunkId,
        left: pct((r.left - box.left) / box.width),
        top: pct((r.top - box.top) / box.height),
        width: pct(r.width / box.width),
        height: pct(r.height / box.height),
      });
    }
  }
  return out;
}

/**
 * The text layer's text, and where each node sits in it.
 *
 * A space is inserted between adjacent nodes that do not already have one:
 * pdf.js emits one span per typeset run, and concatenating them raw would glue
 * the last word of one to the first of the next and hide both from the match.
 * The inserted spaces belong to no node, which is why `rangeOver` looks up an
 * offset rather than assuming it can subtract.
 */
function indexText(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  let text = '';
  const map = [];
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    const v = n.nodeValue;
    if (!v) continue;
    if (text && !/\s$/.test(text) && !/^\s/.test(v)) text += ' ';
    map.push({ node: n, from: text.length, to: text.length + v.length });
    text += v;
  }
  return { text, map };
}

function rangeOver(map, from, to) {
  const start = map.find((m) => from >= m.from && from < m.to);
  const end = map.find((m) => to > m.from && to <= m.to);
  if (!start || !end) return null;
  const range = document.createRange();
  range.setStart(start.node, from - start.from);
  range.setEnd(end.node, to - end.from);
  return range;
}

/**
 * Load the document and its page handles.
 *
 * Both pieces of state are read back through the current url rather than
 * cleared when it changes, the same way `usePaperText` reads through the
 * current doc_id: clearing in the effect is a synchronous setState on every
 * switch, and it would flash the previous paper's pages in between.
 */
function usePdfPages(url) {
  const [loaded, setLoaded] = useState(null);
  const [failed, setFailed] = useState(null);

  const pages = loaded?.url === url ? loaded.pages : null;
  const error = failed?.url === url ? failed.msg : '';

  useEffect(() => {
    let live = true;
    let doc = null;

    (async () => {
      const pdfjs = await loadPdfjs();
      doc = await pdfjs.getDocument({ url }).promise;
      if (!live) return;

      const out = [];
      for (let n = 1; n <= doc.numPages; n += 1) {
        const page = await doc.getPage(n);
        const { width, height } = page.getViewport({ scale: 1 });
        if (!live) return;
        out.push({ number: n, page, width, height });
      }
      if (live) setLoaded({ url, pages: out });
    })().catch((e) => {
      if (live) setFailed({ url, msg: e?.message || 'the file could not be read' });
    });

    return () => {
      live = false;
      // Frees the worker's copy. Without this, paging through a library keeps
      // every paper it ever opened parsed in the worker.
      doc?.destroy?.();
    };
  }, [url]);

  return { pages, error };
}

const pct = (v) => `${(v * 100).toFixed(3)}%`;
