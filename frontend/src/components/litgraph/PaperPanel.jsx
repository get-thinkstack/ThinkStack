import { useState, useEffect, useRef } from 'react';
import { documentsApi } from '../../utils/api';
import { neighbours, nearestFurthest } from './panel';
import { markChunks, locateQuote } from './highlight';

/**
 * The paper panel: what the map knows, and the paper itself.
 *
 * Two tabs, because these answer different questions and neither should be
 * scrolled past to reach the other. `About` is the map's view -- who this
 * paper sits next to, which theme it belongs to, which gaps cite it. `Read`
 * is the paper.
 *
 * All of About comes out of the single /graph payload the canvas already
 * holds. None of it is a new request; it was simply never shown.
 */

/**
 * Chunk text by doc_id, kept between tab switches and panel opens.
 *
 * It holds the in-flight PROMISE, not the resolved document. Caching the
 * result instead deadlocks under StrictMode's double-invoked effects: the
 * first run's cleanup cancels its own setState, the second run finds the
 * cache already warm and returns without setting anything, and the reader
 * sits on "Loading the paper" forever with the text sitting in the cache
 * beside it. Awaiting one shared promise also means one request per paper
 * however many times the panel is opened.
 *
 * ponytail: unbounded map. A library is a few dozen papers on one desktop --
 * add an LRU if that ever stops being true.
 */
const textCache = new Map();

const fetchPaper = (id) => {
  if (!textCache.has(id)) textCache.set(id, documentsApi.get(id));
  return textCache.get(id);
};

// Whether the original pdf exists for a doc, probed once with a HEAD request.
// 403 (encrypted) and 404 (file gone) both mean "show the text fallback".
const pdfOkCache = new Map();

export default function PaperPanel({
  node, graph, matches, tab, onTab, onSelect, expanded, onExpand,
}) {
  const links = neighbours(node.doc_id, graph.edges);
  const theme = (graph.themes || []).find((t) => t.doc_ids?.includes(node.doc_id));
  const inGaps = (graph.gaps || []).filter((g) => g.doc_ids?.includes(node.doc_id));
  const place = nearestFurthest(node, graph.nodes);
  const titleOf = (id) => graph.nodes.find((n) => n.doc_id === id)?.title || 'a deleted paper';
  const hits = matches.get(node.doc_id)?.hits;
  const { doc, error } = usePaperText(node);

  // Which passage the reader should scroll to when it opens. Set by clicking a
  // claim; cleared once used, so returning to the tab does not jump again.
  const [seek, setSeek] = useState(null);
  const openAtClaim = (claim, i) => {
    // Falls back to the claim's own panel when the quote cannot be located --
    // a jump that silently lands at the top of the paper reads as broken.
    if (locateQuote(doc?.chunks, claim.supporting_text)) {
      setSeek(claim.supporting_text);
      onTab('read');
    } else {
      onSelect(node.doc_id, i);
    }
  };

  return (
    <>
      <div className="lg-kind">Paper</div>
      <h3>{node.title}</h3>
      <div className="lg-authors">{node.authors} {node.year}</div>

      <div className="lg-tabs" role="tablist">
        <button
          role="tab" aria-selected={tab !== 'read'}
          className={`lg-tab ${tab !== 'read' ? 'active' : ''}`}
          onClick={() => onTab('about')}
        >
          About
        </button>
        <button
          role="tab" aria-selected={tab === 'read'}
          className={`lg-tab ${tab === 'read' ? 'active' : ''}`}
          onClick={() => onTab('read')}
        >
          Read
        </button>
      </div>

      {tab === 'read'
        ? (
          <Reader
            key={node.doc_id}  /* a claim-jump page must not follow you to the next paper */
            node={node} doc={doc} error={error}
            hits={hits} claims={node.claims} theme={theme}
            seek={seek} onSeeked={() => setSeek(null)}
          />
        )
        : (
          <div className="lg-tabbody">
            {node.summary
              ? <p>{node.summary}</p>
              : (
                // Claims without a summary is a real state -- you can run
                // either one alone -- so this must not claim the paper is
                // untouched when its claims are listed directly below.
                <p className="lg-muted">
                  {node.claims?.length
                    ? 'No summary yet. Select it and run Summarize.'
                    : 'Not analyzed yet. Select it and run Summarize.'}
                </p>
              )}

            {hits?.length > 0 && (
              <>
                <h4>Why this matched</h4>
                {hits.slice(0, 4).map((h) => (
                  <div key={h.chunk_id} className="lg-quote">
                    <q>{h.text}</q>
                    <span>page {h.page} · {h.score.toFixed(2)}</span>
                  </div>
                ))}
              </>
            )}

            {/* The edge set has always been drawn and never listed. Hovering a
                node and watching what stays bright was the only way to read it. */}
            {links.length > 0 && (
              <>
                <h4>Connected to · {links.length}</h4>
                {links.map((l) => (
                  <button key={l.id} className="lg-claim" onClick={() => onSelect(l.id)}>
                    <span className="lg-tag">{l.weight.toFixed(2)}</span>
                    {titleOf(l.id)}
                  </button>
                ))}
              </>
            )}

            {theme && (
              <>
                <h4>Theme</h4>
                <p className="lg-fact">
                  <b>{theme.label}</b>
                  {theme.doc_ids.length > 1 && `, shared with ${theme.doc_ids.length - 1} other ${theme.doc_ids.length === 2 ? 'paper' : 'papers'}`}
                </p>
              </>
            )}

            {/* A gap names its evidence; this is that relation read backwards. */}
            {inGaps.length > 0 && (
              <>
                <h4>Cited in gaps · {inGaps.length}</h4>
                {inGaps.map((g) => (
                  <button key={g.gap_id} className="lg-claim" onClick={() => onSelect(g.gap_id, null, true)}>
                    <span className="lg-tag">{g.severity}</span>
                    {(g.gap_type || '').replace(/_/g, ' ')}
                  </button>
                ))}
              </>
            )}

            {place && (
              <>
                <h4>Where it sits</h4>
                <p className="lg-fact">
                  Closest to <b>{place.near.title}</b>
                  {place.far && <>, furthest from <b>{place.far.title}</b></>}.
                  {' '}The map is a projection of what each paper is about, so distance is disagreement.
                </p>
              </>
            )}

            {node.claims?.length > 0 && (
              <>
                <h4>Claims · {node.claims.length}</h4>
                {node.claims.map((c, i) => (
                  <button key={i} className="lg-claim" onClick={() => openAtClaim(c, i)}>
                    <span className="lg-tag">{(c.type || c.claim_type || '').replace(/_/g, ' ')}</span>
                    {c.text || c.claim_text}
                  </button>
                ))}
              </>
            )}

            <div className="lg-stat"><span>Chunks</span><b>{node.chunks}</b></div>
            {node.claims?.length > 0 && (
              <button className="btn btn-secondary btn-sm" style={{ marginTop: '0.75rem' }}
                onClick={() => onExpand(expanded === node.doc_id ? null : node.doc_id)}>
                {expanded === node.doc_id ? 'Collapse claims' : 'Fan out claims'}
              </button>
            )}
          </div>
        )}
    </>
  );
}

/**
 * The paper's text, fetched when the panel opens rather than when the Read
 * tab does: About needs it too, to know whether a claim can be jumped to.
 */
function usePaperText(node) {
  const [fetched, setFetched] = useState(null);
  const [failed, setFailed] = useState(null);

  // Both are read through the current doc_id rather than cleared when it
  // changes: clearing them in the effect would be a synchronous setState on
  // every switch, and would flash the previous paper's text in between.
  const doc = fetched?.doc_id === node.doc_id ? fetched : null;
  const error = failed?.id === node.doc_id ? failed.msg : '';

  useEffect(() => {
    if (node.is_encrypted) return;
    let live = true;
    fetchPaper(node.doc_id)
      .then((d) => live && setFetched(d))
      .catch((e) => {
        textCache.delete(node.doc_id);   // a failure must not cache as one
        if (live) setFailed({ id: node.doc_id, msg: e.message || 'could not load the text' });
      });
    return () => { live = false; };
  }, [node.doc_id, node.is_encrypted]);

  return { doc, error };
}

/** Same read-through shape as usePaperText: state is only trusted for the
 *  current doc_id, so switching papers never shows the previous answer. */
function usePdfOk(node) {
  const [probed, setProbed] = useState(null);
  const ok = pdfOkCache.has(node.doc_id)
    ? pdfOkCache.get(node.doc_id)
    : probed?.id === node.doc_id ? probed.ok : null;

  useEffect(() => {
    if (node.is_encrypted || pdfOkCache.has(node.doc_id)) return;
    let live = true;
    fetch(documentsApi.pdfUrl(node.doc_id), { method: 'HEAD' })
      .then((r) => {
        pdfOkCache.set(node.doc_id, r.ok);
        if (live) setProbed({ id: node.doc_id, ok: r.ok });
      })
      .catch(() => live && setProbed({ id: node.doc_id, ok: false }));
    return () => { live = false; };
  }, [node.doc_id, node.is_encrypted]);

  return ok;
}

/**
 * The paper. The original pdf when it exists; the extracted text with its
 * marks only as the fallback (encrypted paper, file gone). Chunking never
 * mattered here -- the uploaded file was on disk all along.
 */
function Reader({ node, doc, error, hits, claims, theme, seek, onSeeked }) {
  const bodyRef = useRef(null);
  const pdfOk = usePdfOk(node);
  const target = seek && locateQuote(doc?.chunks, seek);

  // In pdf mode the page is derived, not stored, and seek is deliberately NOT
  // cleared: clearing it would change the iframe src back and reload the
  // viewer to page 1. The next claim click replaces it.
  const page = pdfOk
    ? (target && doc?.chunks?.find((c) => c.chunk_id === target)?.metadata?.page_number) || null
    : null;

  // Text mode scrolls once and clears, so returning to the tab does not jump.
  useEffect(() => {
    if (!target || pdfOk) return;
    const el = bodyRef.current?.querySelector(`[data-chunk-id="${CSS.escape(target)}"]`);
    el?.scrollIntoView({ block: 'center', behavior: 'smooth' });
    el?.classList.add('lg-chunk-landed');
    onSeeked();
  }, [target, pdfOk, onSeeked]);

  // Encryption is not an error and must not read like one. Library owns the
  // decrypt flow; a second one here would be a second place to get it wrong.
  if (node.is_encrypted) {
    return (
      <div className="lg-tabbody lg-muted">
        <p>This paper is encrypted. Decrypt it in Library to read it here.</p>
      </div>
    );
  }

  if (pdfOk) {
    return (
      <div className="lg-tabbody lg-reader-pdf">
        <iframe
          className="lg-pdf"
          title={node.title}
          src={documentsApi.pdfUrl(node.doc_id) + (page ? `#page=${page}` : '')}
        />
      </div>
    );
  }
  if (pdfOk === null) {
    return <div className="lg-tabbody lg-muted"><p>Loading the paper…</p></div>;
  }

  // ---- no pdf: the extracted text, marked ----
  if (error) return <div className="lg-tabbody lg-muted"><p>{error}</p></div>;
  if (!doc) return <div className="lg-tabbody lg-muted"><p>Loading the paper…</p></div>;
  if (!doc.chunks?.length) {
    return <div className="lg-tabbody lg-muted"><p>No text stored for this paper.</p></div>;
  }

  const marks = markChunks(doc.chunks, { hits, claims, theme });

  return (
    <div className="lg-tabbody lg-reader" ref={bodyRef}>
      {/* The stored filename is prefixed with the doc_id. That is storage's
          business, not the reader's. */}
      <div className="lg-reader-head">
        {doc.filename.replace(/^[0-9a-f]{8,}_/, '')} · {doc.total_chunks} chunks
      </div>

      {/* An unexplained highlight is noise, so the marks name themselves --
          and only the ones actually on the page are listed. */}
      {marks.size > 0 && (
        <div className="lg-legend">
          {[
            ['match', 'matched your search'],
            ['claim', 'supports a claim'],
            ['theme', 'theme keyword'],
          ]
            .filter(([kind]) => [...marks.values()].some((s) => s.has(kind)))
            .map(([kind, label]) => (
              <span key={kind} className={`lg-key lg-key-${kind}`}>{label}</span>
            ))}
        </div>
      )}

      {doc.chunks.map((c) => (
        <p
          key={c.chunk_id}
          className={['lg-chunk', ...[...(marks.get(c.chunk_id) || [])].map((k) => `is-${k}`)].join(' ')}
          data-chunk-id={c.chunk_id}
        >
          {c.metadata?.page_number != null && (
            <span className="lg-page">p{c.metadata.page_number}</span>
          )}
          {c.text}
        </p>
      ))}
    </div>
  );
}
