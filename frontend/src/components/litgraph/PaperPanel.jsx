import { useState, useEffect } from 'react';
import { documentsApi } from '../../utils/api';
import { neighbours, nearestFurthest } from './panel';

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

// Chunk text, kept between tab switches. A library is a few dozen papers on
// one desktop, so there is nothing to evict.
// ponytail: unbounded map, add an LRU if a library ever gets big enough to notice.
const textCache = new Map();

export default function PaperPanel({
  node, graph, matches, tab, onTab, onSelect, expanded, onExpand,
}) {
  const links = neighbours(node.doc_id, graph.edges);
  const theme = (graph.themes || []).find((t) => t.doc_ids?.includes(node.doc_id));
  const inGaps = (graph.gaps || []).filter((g) => g.doc_ids?.includes(node.doc_id));
  const place = nearestFurthest(node, graph.nodes);
  const titleOf = (id) => graph.nodes.find((n) => n.doc_id === id)?.title || 'a deleted paper';
  const hits = matches.get(node.doc_id)?.hits;

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
        ? <Reader node={node} />
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
                  <button key={i} className="lg-claim"
                    onClick={() => onSelect(node.doc_id, i)}>
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

/** The paper, whole, in reading order. */
function Reader({ node }) {
  const [fetched, setFetched] = useState(null);
  const [failed, setFailed] = useState(null);

  // Both are read through the current doc_id rather than reset when it
  // changes: clearing them in the effect would be a synchronous setState on
  // every cache hit, and would flash the previous paper's text in between.
  const doc = textCache.get(node.doc_id) || (fetched?.doc_id === node.doc_id ? fetched : null);
  const error = failed?.id === node.doc_id ? failed.msg : '';

  useEffect(() => {
    if (node.is_encrypted || textCache.has(node.doc_id)) return;
    let live = true;
    documentsApi.get(node.doc_id)
      .then((d) => {
        textCache.set(node.doc_id, d);
        if (live) setFetched(d);
      })
      .catch((e) => live && setFailed({ id: node.doc_id, msg: e.message || 'could not load the text' }));
    return () => { live = false; };
  }, [node.doc_id, node.is_encrypted]);

  // Encryption is not an error and must not read like one. Library owns the
  // decrypt flow; a second one here would be a second place to get it wrong.
  if (node.is_encrypted) {
    return (
      <div className="lg-tabbody lg-muted">
        <p>This paper is encrypted. Decrypt it in Library to read it here.</p>
      </div>
    );
  }
  if (error) return <div className="lg-tabbody lg-muted"><p>{error}</p></div>;
  if (!doc) return <div className="lg-tabbody lg-muted"><p>Loading the paper…</p></div>;
  if (!doc.chunks?.length) {
    return <div className="lg-tabbody lg-muted"><p>No text stored for this paper.</p></div>;
  }

  return (
    <div className="lg-tabbody lg-reader">
      <div className="lg-reader-head">{doc.filename} · {doc.total_chunks} chunks</div>
      {doc.chunks.map((c) => (
        <p key={c.chunk_id} className="lg-chunk" data-chunk-id={c.chunk_id}>
          {c.metadata?.page_number != null && (
            <span className="lg-page">p{c.metadata.page_number}</span>
          )}
          {c.text}
        </p>
      ))}
    </div>
  );
}
