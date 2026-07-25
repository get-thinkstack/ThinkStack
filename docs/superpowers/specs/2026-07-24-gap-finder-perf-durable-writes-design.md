# Gap Finder performance + durable vector-store writes

Date: 2026-07-24
Status: approved (in-chat), implementing

## Problem

1. **Gap analysis takes 4–5 min.** The pipeline is N+2 fully-serialized local-LLM
   generations (N per-document summary/claim calls + 1 gap call + 1 suggestion
   call), all queued through the single-model lock. The per-document analysis is
   recomputed on every run and never persisted.
2. **Silent total data loss risk.** `VectorStore._save()` truncates and rewrites
   `vectors.json` in place; a crash mid-write corrupts the whole knowledge base,
   and `_load()` then silently resets to empty.

## Goals

- Cut a gap scan of already-ingested papers from N+2 generations to 1.
- Make vector-store persistence crash-safe.
- No change to the gap-analysis HTTP response shape (frontend untouched).

## Design

### A. Atomic JSON writes
`infrastructure/atomic_io.py` → `atomic_write_json(path, data)`: serialize to a
sibling `*.tmp` file, `flush` + `fsync`, then `os.replace()` onto the target
(atomic on Windows + POSIX, same filesystem). On any failure the original file
is left intact and the temp file is cleaned up.

`VectorStore._save()` uses it (fixes the data-loss risk).

### B. Per-document analysis cache
`infrastructure/analysis_cache.py` → `DocAnalysisCache` backed by
`data/doc_analysis.json`, keyed by `doc_id`, storing `{summary, claims}`.
Atomic writes via (A). API: `get(doc_id)`, `put(doc_id, summary, claims)`,
`delete(doc_id)`. Key is an immutable per-upload UUID, so entries never go
stale. Cleaned up on document delete.

### C. Document analysis unit
`domain/analysis/document_analysis.py` → `analyze_document(doc_id, text)`:
the single summary+claims LLM call (moved out of `routes_gaps.py`), returning
`{summary, claims}`. Computed at **upload time** (best-effort; upload still
succeeds if it fails) and cached. Missing entries are computed lazily on first
scan (fallback for papers ingested before this change), then cached.

### D. Gap pipeline reuse
`routes_gaps.analyze`: per paper, cache hit → use it (no LLM, no
decrypt/full-text fetch); miss → compute once + cache. Then a single
aggregation call.

### E. Merged gaps + suggestions
`gap_finder` gains `analyze_gaps_and_suggestions(summaries, claims, doc_ids)`:
one prompt returns `{gaps, suggestions}` where suggestions carry
`related_gap_indexes` (1-based). After parsing, each gap is assigned a
`gap_id`; indexes are remapped to `related_gaps` gap-ids. Response shape is
identical to today. A content budget caps combined summaries+claims so
prompt+output fit the 4096 ctx. `max_tokens` sized to fit (not aggressively
trimmed — too-low caps truncate JSON and break parsing).

## Out of scope (this round)
B1 (frontend suggestion→gap linkage), B2 (failed-doc counting), B4/B5, CORS,
training-data privacy. E keeps the backend `related_gaps` linkage correct so a
later B1 fix works without backend changes.

## Testing (pytest, new `tests/`)
- atomic_io: original preserved on mid-write failure; no temp left on success.
- analysis_cache: get/put/delete round-trip; miss→None; corrupt file handled.
- vector store: `_save` is crash-safe (original intact when serialization fails).
- document_analysis: mocked LLM → structured output; parse failure → graceful.
- gap merge: mocked LLM JSON → gap_ids assigned + `related_gap_indexes` remapped.
- cache reuse: second scan makes zero `analyze_document` calls.
