# Aditya: contributions

A record of the parts of ThinkStack I worked on, written mainly so the rest of
the team (and future me) can find the reasoning behind the decisions.

I built the original backend (commit `dadb6db`, "THE BEGINNING"): the ingestion
pipeline, the knowledge base, search, analysis, the gap finder, and the API
routes over them. Most of what follows is that core plus the two rounds of
optimisation it went through since.

## Ingestion and the knowledge base

`domain/ingestion/` turns a PDF into retrievable text: `pdf_parser.py` extracts
per-page text, `chunker.py` splits it into overlapping chunks that respect
sentence boundaries, and `metadata_extractor.py` pulls title, authors, year, and
abstract out of the first pages. `domain/knowledge_base/repository.py` is the
storage boundary the rest of the app calls (`store_chunks`,
`get_chunks_by_doc_id`, `delete_chunks_by_doc_id`, `get_collection_stats`), so
no feature module talks to the vector store directly.

`domain/knowledge_base/embedding_service.py` generates embeddings locally with
sentence-transformers (all-MiniLM-L6-v2). Two decisions there are deliberate:

- The `sentence_transformers` import is deferred into `get_model()`. Importing
  it at module load pulls in torch and transformers, which is what made the
  backend socket, and therefore the Tauri loading screen, wait several seconds
  on every launch. Lazy, the server comes up in about a second and torch loads
  on the first embed.
- The embedding model is pinned to the CPU. It is a 22M-parameter MiniLM and a
  64-chunk batch takes roughly 0.2s there, so giving it VRAM would only steal
  headroom from the GGUF that actually needs the GPU.

## Search

Three modules under `domain/search/`, exposed through `api/routes_search.py`:

- `semantic_search.py`: embeds the query and does a cosine-similarity lookup
  against the vector store, with optional `doc_ids` filtering and a minimum
  score cutoff.
- `keyword_search.py`: BM25 over the same chunks (`rank_bm25`), for queries
  where exact term matching beats embedding similarity (author names, dataset
  names, acronyms).
- `hybrid_search.py`: merges both lists with reciprocal rank fusion,
  `score = sum(1 / (k + rank))` with `k = 60`. RRF ranks on position rather than
  raw score, which matters here because a cosine score and a BM25 score are not
  on the same scale and cannot be blended by weighted sum without tuning a
  constant per corpus.

## Analysis

`domain/analysis/` holds the three cross-paper tasks, all running on the local
model: `summarizer.py` (single-paper and comparative summaries),
`claim_extractor.py` (findings, methodology, limitations, future work), and
`theme_clusterer.py` (thematic clusters across a selection).
`api/routes_analysis.py` exposes them and records every run to history.

## Gap finder

`domain/gap_finder/` identifies gaps across a selection of papers and proposes
research directions to address them. `api/routes_gaps.py` orchestrates it.

The first version cost N+2 model calls for N papers: one analysis call per
paper, then a gaps call, then a suggestions call. On a local SLM that was around
two minutes for a handful of papers, and every one of those calls was serialized
behind the single-model lock. The redesign (commit `1d2de41`) cut a warm scan to
one call:

- `domain/analysis/document_analysis.py` produces a paper's summary and claims
  in a single call instead of two.
- `infrastructure/analysis_cache.py` persists that per-paper result keyed by
  `doc_id`. A document's chunk text is immutable for a given id (a fresh UUID is
  minted on every upload), so the analysis only ever needs to run once per
  paper. `api/routes_documents.py` precomputes it at ingest time, best-effort,
  so an upload never fails because the model was unavailable, and the gap route
  falls back to computing it lazily on a miss. Deleting a document evicts its
  entry, so a re-upload is never served a previous document's summary.
- `domain/gap_finder/gap_pipeline.py` merges gap identification and suggestion
  generation into one call. The model links each suggestion to the gaps it
  addresses by 1-based index, and the pipeline remaps those to the gap ids we
  assign, dropping out-of-range indexes so a hallucinated one cannot break the
  response. The grounding text is capped at 6000 characters because the context
  window is 4096 tokens and the output needs room.

## Local SLM runtime

`infrastructure/ollama_client.py` is the async client every feature generates
through. The parts I own:

- The llama.cpp path alongside the original Ollama one, so the app runs fully
  offline against a bundled GGUF with no separate server to install.
- A GBNF grammar that constrains output to valid JSON, plus `_extract_json_text`
  as a second line of defence: even with the grammar, a fallback path can return
  JSON wrapped in markdown fences or behind a short preamble, which breaks
  `json.loads`. Structured output was the single largest source of failures in
  the analysis and gap features.
- GPU-only enforcement (commit `a97a09f`). A CPU-only build of
  `llama-cpp-python` silently ignores `n_gpu_layers` and runs on the CPU without
  error, which reads as "the app is just slow" rather than as a
  misconfiguration. When GPU offload is requested the build is verified with
  `llama_supports_gpu_offload()` and a bad setup raises with the exact install
  command instead of falling back. Flash attention is enabled where the build
  accepts it, which shrinks the KV cache and buys headroom on a 6 GB card.
  Supporting work: `docs/gpu_setup.md`, `tools/verify_gpu.py`, and
  `tools/fix_gpu_dlls.py`.
- Per-call timing in the log (completion tokens, elapsed, tok/s, prompt tokens).
  This is what made the N+2 problem visible: it separates "the model is slow"
  from "we are making too many calls", and confirms at a glance whether a build
  is actually on the GPU. Current baseline is about 46.5 tok/s.
- Frozen-build configuration in `config.py`: `BUNDLE_DIR` for the read-only
  payload we ship and `STATE_DIR` for writable user data, since writing into the
  install directory is either denied or silently discarded on the next launch.
  `.env` is resolved from an ordered candidate list rather than the relative
  path, because a relative `.env` resolves against whatever directory the
  desktop shell launched us from and a packaged build would quietly fall back to
  the CPU-only defaults.

## Durability and run history

Both long-running features used to discard their output on the next run, and
every JSON store truncated its file in place.

- `infrastructure/atomic_io.py`: `atomic_write_json` serializes to a sibling
  temp file, fsyncs, then renames over the target, so a crash mid-write leaves
  either the old complete file or the new one, never a torn one. The vector
  store, the analysis cache, and both history stores write through it. Before
  this, a kill during a `vectors.json` save could take out the whole library.
- `infrastructure/run_history.py`: a capped, newest-first log of past runs,
  written atomically, with `gap_history.py` and `analysis_history.py` binding it
  to their own files. A corrupt or missing file is treated as empty history,
  since a stale log costs history, never correctness.
- `Analysis.jsx` and `GapAnalysis.jsx` grew a history panel that lists past
  runs, reopens one without recomputing it, and deletes individual entries. The
  analysis records keep their run `type` so the UI re-renders the matching view.

43 tests cover this work (`tests/test_atomic_io.py`, `test_analysis_cache.py`,
`test_document_analysis.py`, `test_gap_pipeline.py`, `test_gap_history.py`, the
two history route suites, `test_routes_gaps_integration.py`,
`test_routes_documents_wiring.py`, `test_vector_store_durability.py`).

## Paper writer

A supporting role here; Rithesh owns the feature. My contributions:

- Error recovery in `domain/paper_writer/compiler.py`: `_extract_errors` parses
  the meaningful `! ...` blocks out of a pdflatex log with enough context to
  carry the `l.NN` source line, and the salvage path replaces the specific
  broken environment (`tikzpicture`, `axis`, `pgfplots`, `figure`, `table`) with
  a placeholder box built from core LaTeX primitives, so one bad figure degrades
  to a note in the PDF instead of failing the document.
- The KaTeX loading fix in `LatexPreview.jsx`. The dynamic import was marked
  `@vite-ignore`, which left a bare `"katex"` specifier in the bundle output
  that no browser can resolve, so every equation silently fell through to the
  `<code>` fallback. Removing the annotation lets Vite code-split it properly:
  math renders, and KaTeX still stays out of the initial bundle.

## Frontend and docs

I set up the initial React app and the page shell (`PageHeader.jsx`, the loading
screen, the recharts panels under `components/charts/`), and did the Tauri
integration pass in `ee37d48`. On the docs side I wrote the first project
documentation and `docs/academic/presentation.md`.
