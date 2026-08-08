"""
litgraph graph builder.

assembles the spatial map of a library out of state that already persists.
nothing here calls the language model: positions come from the embeddings
written at ingest, themes and gaps come from analysis runs the user has
already paid for, and summaries and claims come from the per-document
analysis cache. the graph is derived, cheap, and rebuilt on every request.

the layout rules the canvas depends on:

  * position encodes meaning   -- PCA over per-document embedding centroids
  * an edge encodes similarity -- cosine between those centroids
  * territory encodes theme    -- hulls drawn by the client over doc_ids
"""

import logging

import numpy as np

from domain.knowledge_base.repository import get_all_doc_ids
from infrastructure.analysis_cache import doc_analysis_cache
from infrastructure.analysis_history import analysis_history
from infrastructure.gap_history import gap_history
from infrastructure.local_vector_store import get_vector_store

logger = logging.getLogger(__name__)

# Similarity below this is not evidence of anything. Academic text embeds into
# a narrow cone -- almost every pair of papers scores "somewhat similar" -- so
# a low threshold alone yields a hairball that reads as noise.
EDGE_THRESHOLD = 0.35

# ...and a threshold alone is not enough, because a tightly-focused library
# clears it everywhere. Each paper additionally keeps only its strongest few
# neighbours; the union of those is the edge set. This bounds edge count at
# O(n) instead of O(n^2) and is what keeps a 200-paper map legible.
MAX_EDGES_PER_NODE = 4

# fraction of the unit square left as margin, so nodes never sit on the edge
# of the world box where the client's hull padding would clip them.
PAD = 0.08

# Closest two node centres may sit, in normalised units.
#
# PCA places related papers tightly by design, which is the point -- but nothing
# stopped two near-duplicates landing on the same pixel, and a library of
# identical papers stacked every node at the centre. The client draws a node at
# radius 11 + min(chunks,200)/14, so 25 px at worst, in a 1100x760 world: two
# nodes need ~60 px between centres to read as two things. 60/1100 = 0.055.
#
# This spaces NODES. It cannot make a 26-character label fit beside its
# neighbour -- labels are handled by the collision pass in useCanvas.js.
MIN_SEP = 0.055

# How many relaxation passes to run. Each pass resolves every pair that is too
# close; a handful is enough to settle the clusters PCA actually produces, and
# capping it keeps the layout a deterministic function of the input rather than
# something that runs until it feels done.
SEPARATION_PASSES = 24


def _collect() -> tuple[list[str], np.ndarray, dict]:
    """one pass over the store: centroid, chunk count and metadata per doc.

    deliberately a single unfiltered read. the filtered form scans every entry
    once per document, so calling it per doc is O(docs x chunks) -- fine at
    seven papers, visibly slow at two hundred.

    returns:
        (doc ids, centroid matrix of shape (n, d), {doc_id: {chunks, meta}}).
        documents with no stored vectors are dropped rather than given a zero
        row, which would park them at the origin and invent a similarity to
        everything else sitting there.
    """
    got = get_vector_store().get_embeddings()
    if got["embeddings"] is None or len(got["ids"]) == 0:
        return [], np.empty((0, 0), dtype=np.float32), {}

    embeddings = np.asarray(got["embeddings"], dtype=np.float32)
    order: list[str] = []
    rows: dict[str, list[np.ndarray]] = {}
    info: dict[str, dict] = {}

    for i, meta in enumerate(got["metadatas"]):
        doc_id = (meta or {}).get("doc_id")
        if not doc_id:
            continue
        if doc_id not in rows:
            rows[doc_id] = []
            info[doc_id] = {"chunks": 0, "meta": meta or {}}
            order.append(doc_id)
        rows[doc_id].append(embeddings[i])
        info[doc_id]["chunks"] += 1

    if not order:
        return [], np.empty((0, 0), dtype=np.float32), {}

    matrix = np.vstack([np.mean(rows[d], axis=0) for d in order])
    return order, matrix, info


def _normalise(coords: np.ndarray) -> np.ndarray:
    """scale coordinates into [PAD, 1-PAD] on each axis independently.

    per-axis scaling deliberately discards PCA's aspect ratio. the canvas is a
    fixed viewport, and preserving the ratio would leave a one-dimensional
    library rendered as a thin line across an otherwise empty screen.
    """
    out = np.empty_like(coords)
    for axis in range(coords.shape[1]):
        col = coords[:, axis]
        lo, hi = float(col.min()), float(col.max())
        span = hi - lo
        if span < 1e-9:
            # every document identical on this axis; centre them rather than
            # dividing by ~zero and scattering them to infinity.
            out[:, axis] = 0.5
        else:
            out[:, axis] = PAD + (col - lo) / span * (1 - 2 * PAD)
    return out


def _separate(coords: np.ndarray) -> np.ndarray:
    """push crowded nodes apart, towards a centre-to-centre gap of ``MIN_SEP``.

    seeded by the PCA positions and run for a fixed number of passes, so this
    stays a pure function of the input: the same library always draws the same
    map. a force layout with a convergence test would not -- and a map that
    rearranges itself between two visits is one you cannot learn.

    each pass sums the push from every crowding neighbour at once rather than
    resolving pairs one at a time, which settles a tight cluster in far fewer
    passes than sequential relaxation.

    the pass cap means crowded libraries are improved rather than guaranteed:
    60 papers reach the full gap, 200 get from 0.003 to 0.026 -- the padded
    square cannot hold much more than 230 nodes at this spacing anyway. Ten
    times the separation is what stops two papers reading as one; chasing the
    last of it would cost time on every graph build.
    """
    n = coords.shape[0]
    if n < 2:
        return coords

    out = coords.copy()
    lo, hi = PAD, 1.0 - PAD

    # Two documents can land on exactly the same point -- identical papers
    # normalise to the centre -- and a zero-length vector has no direction to
    # push along. Give every node a fixed angle by index so the tie is broken
    # the same way every time.
    ring = np.stack(
        [np.cos(2 * np.pi * np.arange(n) / n), np.sin(2 * np.pi * np.arange(n) / n)],
        axis=1,
    ).astype(out.dtype)

    for _ in range(SEPARATION_PASSES):
        # ponytail: O(n^2) per pass. At 200 papers that is a 200x200x2 array,
        # which is nothing; revisit if libraries reach the thousands.
        diff = out[:, None, :] - out[None, :, :]
        dist = np.hypot(diff[..., 0], diff[..., 1])
        np.fill_diagonal(dist, np.inf)

        crowded = dist < MIN_SEP
        if not crowded.any():
            break

        coincident = dist < 1e-9
        safe = np.where(coincident, 1.0, dist)
        unit = diff / safe[..., None]

        # where two nodes coincide, push along the difference of their ring
        # angles instead of their (zero) separation
        ring_diff = ring[:, None, :] - ring[None, :, :]
        ring_len = np.hypot(ring_diff[..., 0], ring_diff[..., 1])
        ring_unit = ring_diff / np.where(ring_len < 1e-9, 1.0, ring_len)[..., None]
        unit = np.where(coincident[..., None], ring_unit, unit)

        # half the shortfall each, so a pair meets in the middle
        overlap = np.where(crowded, (MIN_SEP - dist) / 2.0, 0.0)
        out += (unit * overlap[..., None]).sum(axis=1)
        np.clip(out, lo, hi, out=out)

    return out


def _project(matrix: np.ndarray) -> np.ndarray:
    """project embedding centroids to 2D positions in the unit square.

    uses PCA via SVD -- numpy already ships with the app, and this is a
    handful of documents, so a full decomposition costs nothing and avoids
    taking on sklearn for one function.

    fewer than three documents cannot define two principal axes, so those
    cases fall back to a circle: it is honest about carrying no information,
    and it still gives the camera something to frame.
    """
    n = matrix.shape[0]

    if n == 0:
        return np.empty((0, 2), dtype=np.float32)
    if n == 1:
        return np.array([[0.5, 0.5]], dtype=np.float32)
    if n < 3:
        angles = np.linspace(0, 2 * np.pi, n, endpoint=False) - np.pi / 2
        return np.stack([0.5 + 0.28 * np.cos(angles),
                         0.5 + 0.28 * np.sin(angles)], axis=1).astype(np.float32)

    centred = matrix - matrix.mean(axis=0)
    # full_matrices=False: we only ever want the first two components.
    _u, s, vt = np.linalg.svd(centred, full_matrices=False)
    coords = centred @ vt[:2].T

    if s.shape[0] < 2 or float(s[1]) < 1e-9:
        # the library is genuinely one-dimensional (or every paper is a near
        # duplicate). spreading it along a line beats stacking every node on
        # one pixel, so keep component 1 and fan the second axis by index.
        coords = np.stack(
            [coords[:, 0], np.linspace(-1, 1, n).astype(coords.dtype)], axis=1
        )

    # normalise first: MIN_SEP is defined in the normalised unit square, and
    # separating raw PCA coordinates would mean a different spacing for every
    # library. Separation clips back into the padded square itself, so it is
    # not re-normalised afterwards -- that would rescale the gaps it just made
    # straight back out again.
    return _separate(_normalise(coords.astype(np.float32)))


def _edges(ids: list[str], matrix: np.ndarray) -> list[dict]:
    """similarity edges between document centroids.

    args:
        ids: document ids, aligned with the rows of ``matrix``.
        matrix: centroid matrix of shape (n, d).

    returns:
        list of ``{source, target, weight}``, each pair appearing once.
    """
    n = len(ids)
    if n < 2:
        return []

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    unit = matrix / norms
    sim = unit @ unit.T
    np.fill_diagonal(sim, -1.0)          # never link a paper to itself

    keep: set[tuple[int, int]] = set()
    for i in range(n):
        order = np.argsort(sim[i])[::-1][:MAX_EDGES_PER_NODE]
        for j in order:
            if sim[i, j] >= EDGE_THRESHOLD:
                keep.add((min(i, int(j)), max(i, int(j))))

    return [
        {"source": ids[i], "target": ids[j], "weight": round(float(sim[i, j]), 4)}
        for i, j in sorted(keep)
    ]


def _latest_themes() -> list[dict]:
    """themes from the most recent theme-clustering run, if any.

    only doc_ids still present in the library are kept: a theme referring to a
    deleted paper would draw a hull around a node that is not on the canvas.
    """
    live = set(get_all_doc_ids())
    for run in analysis_history.list():          # newest first
        if run.get("type") != "themes":
            continue
        themes = []
        for t in (run.get("result") or {}).get("themes", []):
            doc_ids = [d for d in t.get("doc_ids", []) if d in live]
            if not doc_ids:
                continue
            themes.append({
                "theme_id": t.get("theme_id", ""),
                "label": t.get("label", ""),
                "description": t.get("description", ""),
                "keywords": t.get("keywords", []),
                "doc_ids": doc_ids,
            })
        return themes
    return []


def _latest_gaps() -> list[dict]:
    """gaps from the most recent scan, each carrying its own suggestions.

    the ui used to match suggestions to gaps by position, which silently
    mismatched them; the backend links them by ``related_gaps``, so that is
    what is resolved here -- once, on the server, rather than in the client.
    """
    live = set(get_all_doc_ids())
    runs = gap_history.list()
    if not runs:
        return []

    run = runs[0]
    suggestions = run.get("suggestions") or []
    out = []

    for g in run.get("gaps") or []:
        gap_id = g.get("gap_id", "")
        out.append({
            "gap_id": gap_id,
            "gap_type": g.get("gap_type", ""),
            "severity": g.get("severity", "medium"),
            "description": g.get("description", ""),
            "evidence": g.get("evidence", []),
            "doc_ids": [d for d in g.get("related_doc_ids", []) if d in live],
            "suggestions": [
                {"title": s.get("title", ""), "description": s.get("description", ""),
                 "rationale": s.get("rationale", "")}
                for s in suggestions
                if gap_id in (s.get("related_gaps") or [])
            ],
        })

    return out


def build_graph() -> dict:
    """assemble the full graph payload for the canvas.

    returns:
        dict with ``nodes``, ``edges``, ``themes``, ``gaps`` and ``stats``.
        every list is present even when empty, so the client renders an empty
        state per layer rather than having to distinguish absent from off.
    """
    ids, matrix, info = _collect()
    coords = _project(matrix)

    nodes = []
    for i, doc_id in enumerate(ids):
        meta = info[doc_id]["meta"]
        cached = doc_analysis_cache.get(doc_id) or {}
        nodes.append({
            "doc_id": doc_id,
            "x": round(float(coords[i][0]), 4),
            "y": round(float(coords[i][1]), 4),
            "title": meta.get("title") or doc_id,
            "authors": meta.get("authors", ""),
            "year": meta.get("year", ""),
            "chunks": info[doc_id]["chunks"],
            "is_encrypted": meta.get("is_encrypted") in ("true", True),
            "summary": cached.get("summary", ""),
            "claims": cached.get("claims", []),
        })

    edges = _edges(ids, matrix)
    themes = _latest_themes()
    gaps = _latest_gaps()

    logger.info(
        "graph: %d nodes, %d edges, %d themes, %d gaps",
        len(nodes), len(edges), len(themes), len(gaps),
    )

    return {
        "nodes": nodes,
        "edges": edges,
        "themes": themes,
        "gaps": gaps,
        "stats": {
            "documents": len(nodes),
            "analyzed": sum(1 for n in nodes if n["summary"]),
            "total_chunks": sum(n["chunks"] for n in nodes),
        },
    }
