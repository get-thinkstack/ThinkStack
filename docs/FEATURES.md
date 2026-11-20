# Features

What ThinkStack does, and how each part works. Why it is built that way is in
[ADR.md](ADR.md); what is broken or unfinished is in [../ISSUES.md](../ISSUES.md).

The app has four sections. Three follow the order research happens in; the
fourth is the workshop.

| Section | Job | Main code |
|---|---|---|
| **Library** | collect: import, correct, encrypt | `domain/ingestion/`, `domain/knowledge_base/`, `domain/encryption/` |
| **LitGraph** | understand: search, map, analyse, find gaps | `domain/search/`, `domain/litgraph/`, `domain/analysis/`, `domain/gap_finder/` |
| **Scribe** | write: LaTeX projects, generation, citations, compile | `domain/paper_writer/` |
| **Bench** | what this machine can run, and with which model | `domain/model_manager/`, `infrastructure/capability.py` |

- [Library](#library)
- [Search](#search)
- [LitGraph](#litgraph)
- [Scribe](#scribe)
- [Bench](#bench)
- [Local inference](#local-inference)
- [Updates](#updates)
- [Training-data collection](#training-data-collection)

---

## Library

### Ingesting a PDF

`POST /api/documents/upload` runs the pipeline in this order:

    save PDF -> extract text -> read page-1 layout -> metadata -> chunk
             -> embed + store -> queue analysis (after the response)

- **Text extraction** tries PyMuPDF first and falls back to pdfplumber for
  layouts PyMuPDF cannot read (`domain/ingestion/pdf_parser.py`).
- **Chunking** splits text into overlapping chunks on paragraph and sentence
  boundaries, keeping the page number of each (`chunker.py`).
- **Embedding** uses `all-MiniLM-L6-v2` through `sentence-transformers`, on the
  CPU, loaded on first use and reused. It is bundled; a packaged build that is
  missing it logs a packaging error before falling back to a download.
- **Analysis is queued, not awaited.** Summary and claims are computed in the
  background job queue right after ingest, then themes are re-clustered and a
  gap scan queued. The upload returns immediately; LitGraph is ready by the time
  it is opened.

### Metadata

Title and authors are read from **page layout**, not flat text
(`layout.py`, `layout_metadata.py`). A PDF stores every glyph with a size and a
position: the title is the largest horizontal text near the top of page 1, and
the authors are the rows beneath it. Flattening the page to a string throws that
away.

- A paper with no title is shown under its filename.
- Year comes from the arXiv identifier or a stated copyright line, and is left
  empty when the paper states none.
- A small-language-model fallback runs only when the layout result fails a
  plausibility check, and it is given the font sizes rather than flat text.
- Handles one and two columns, many authors, small caps, hyphenated titles,
  ligatures, accents, and author blocks laid out in columns, in one
  comma-separated line, or one per row.
- Accuracy is measured on randomly sampled arXiv papers against arXiv's own
  metadata, not on hand-picked ones; the method and latest scores are in the ADR
  (2026-08-12 entries).

**Corrections.** Title, authors and year are editable in the Library. The fix
carries into every later citation, because that metadata labels map nodes,
names search hits and builds BibTeX entries.

### The knowledge base

Chunks, embeddings and metadata are persisted in SQLite (`vectors.db`) and
searched with exact cosine similarity over one in-memory NumPy matrix
(`infrastructure/local_vector_store.py`). No database server; persistence
needs only the standard library's `sqlite3`. Every write goes through
`domain/knowledge_base/repository.py`; search, grounding and the LitGraph builder
read the store directly. Author lists are stored as JSON, because a comma is
BibTeX syntax and cannot separate names safely (`author_codec.py`).

### Encryption

A paper can be encrypted **at rest** with a password
(`domain/encryption/at_rest.py`, routes in `api/routes_encryption.py`):

    encrypt   chunk texts -> one envelope on each chunk, then the text is
              blanked; the PDF -> `<file>.pdf.tsenc`, then the original is
              deleted; the cached summary and claims are dropped
    read      the text, with the password; nothing changes
    remove    text and PDF restored exactly

While encrypted, the paper stays in the Library and on the map (its embeddings
are kept, so search by meaning still finds it), but no route returns its text
or PDF without the password. Embeddings reveal a paper's topic, not its words.
Papers encrypted before 2026-11-19 are only partly at rest; see ISSUES.

- **Key:** Argon2id turns the password into a 256-bit key, with a fresh random
  salt per paper.
- **Cipher:** AES-256-GCM. A wrong password fails the authentication tag check
  instead of returning garbage.
- **Envelope:** everything except the password travels in one versioned string,
  `TSENC1.<kdf params>.<salt>.<nonce>.<ciphertext>`, so the format can change
  later without breaking old papers.

---

## Search

Purely meaning-based (`domain/search/semantic_search.py`). The query is embedded
and scored against **every chunk of every paper**, not a pre-filtered pool, so a
passage on page 40 is as findable as the abstract.

- **Exact-token bonus.** A small bonus (`EXACT_TOKEN_BONUS` × the fraction of
  query tokens that appear verbatim) is added after the cosine score. It can only
  break near-ties, which keeps rare literal terms (`FedAvg`, a surname) findable
  without letting keyword overlap outrank a better semantic match. Keyword search
  (BM25 + rank fusion) was removed; see ADR 2026-08-01.
- **Per-paper rollup.** `group_by_doc` returns papers, each with every matching
  chunk in reading order. That is what LitGraph draws.
- **Grounding.** Scribe can pass search results into a generation so the model
  writes from what the papers say (`grounding.py`).

---

## LitGraph

One canvas for the middle of the work. It replaced three pages (Search,
Analysis, Gap Finder), which were three views of the same question: what is in
this collection, and what is missing.

**How the map is built** (`domain/litgraph/graph_builder.py`, rebuilt on every
request from stored embeddings, the analysis cache and past runs, so there is no
graph state to go stale):

| Mark | Meaning |
|---|---|
| position | each paper's chunk embeddings averaged to a centroid, projected to 2D with PCA, then nudged apart until no two are closer than `MIN_SEP` |
| edge | cosine between centroids above `EDGE_THRESHOLD`, at most `MAX_EDGES_PER_NODE` per paper so a focused library is not a hairball |
| territory | a theme: a soft hull around papers clustered together |
| amber node | a research gap, placed at the centroid of the papers that evidence it, with dashed edges back to each |
| sub-nodes | a paper's extracted claims, fanned out on double-click |

**Using it.**

- **Search by meaning.** The map dims to what matched, with a ring showing how
  strong each match is.
- **Select.** Shift-drag a loop, run a search, or tick papers in the list. The
  selection is what *Summarize*, *Claims*, *Themes* and *Find gaps* run on.
- **Read a paper.** The panel says where the paper sits, lists its neighbours
  (followable to a chosen depth), and opens the passages that matched.
- **Take hold of a paper.** Drag it to pin it and see what it is tied to. A
  press that does not move is a selection, not a drag.
- **Relax the plate.** One dial from the PCA projection exactly, through overlap
  loosened with clusters intact, to a free layout. Every paper keeps a spring to
  its projected home, so the map is always a reading of the embedding space.
- **New papers do not move the map under you.** After an ingest the map offers
  to rebuild rather than redrawing itself (an empty map draws immediately).
- **Runs are kept.** Every analysis and gap scan is saved and can be reopened or
  deleted from the Runs drawer.

**Analysis** (`domain/analysis/`):

- Summaries of one paper or a comparison across several.
- Key-claim extraction.
- Themes: **membership is decided by cosine between paper centroids**; the model
  only names each group (ADR 2026-08-01).
- Model output is valid JSON by grammar, but not necessarily the *right* JSON.
  `parsing.py` coerces the shapes small models actually return (a claim as a bare
  string is still a claim) and validates categories.

**Gap finding** (`domain/gap_finder/gap_pipeline.py`) finds contradictions,
methodological gaps and missing validation across the selected papers, proposes
research directions, and deduplicates findings that say the same thing.

---

## Scribe

A LaTeX editor that compiles offline. **It needs no library**: a fresh install
can create, write and compile a document without ingesting anything. The `cite`
trigger simply finds nothing.

### Projects

- **A paper is a folder** on disk, and the file tree is the way into it
  (`domain/paper_writer/files.py`, `FileTree.jsx`). Add figures, split a paper
  into section files, keep a `.bib` beside it. Right-click for new file or
  folder, rename (F2), duplicate, copy/paste, delete; drop files onto a paper to
  add them; drag files between folders and between papers. Every path goes
  through `safe_path()`, which resolves first and then refuses anything outside
  the project.
- **Starter documents:** research paper, article, letter, CV, report, Beamer
  slides. The **+** in the tree lists them with what each gives you; choosing is
  the same click that creates. The list comes from the backend
  (`templates.py`), so the menu cannot offer one that does not exist, and an
  unknown id gives you the paper rather than an error.
- **Editor and PDF side by side**, with dividers that remember their position.
  One file open at a time. The compiled PDF is the only preview.
- **Keyboard:** `Ctrl+K` opens a palette of every screen and every paper. The
  tree sorts by name or last edit and filters once there are enough projects.

### Using files that live elsewhere

`domain/paper_writer/links.py`.

- **Link a file or folder without copying it**, then write its bare name:
  `\includegraphics{chart.png}` resolves to the linked file where it sits. The
  compile is given the file's directory as a search path, so one
  `references.bib` can serve three papers and stay one file. Copying in is still
  available for a project that must travel as a unit.
- **Links survive renames.** Each link stores the path *and* the OS file
  identity (inode + device on Unix, NTFS file id on Windows). On open: try the
  path; if it is gone, look for the identity in folders the project already
  refers to; only then mark it **missing** and offer to locate it. A missing link
  never breaks the compile.
- **Anything can be linked**, not only what LaTeX reads. The chooser marks which
  files a document could reference, as a hint.
- **Choosing is navigating.** The picker browses directories through the backend
  (`Ctrl+O` for a file, `Ctrl+K Ctrl+O` for a folder), so the same window works
  in the desktop app and in a browser tab.
- Clicking an image previews it and shows the `\includegraphics` line to paste.

### Writing with the model

Select plain English and press `Ctrl+Enter`: it becomes LaTeX at the cursor, not
appended at the end. Optionally grounded in papers from the library. Needs a
model: the one assigned to Scribe (`latex_writer`) in Bench, or the router's
fallback.

### Citations

Type `cite` and the library drops down under the caret; filter by title, author,
year or key; Enter writes `\cite{vaswani2017attention}` and adds the entry to the
project's `references.bib` (`bibliography.py`). Dismiss it and `cite` stays a
word.

- **Numbers are not tracked.** BibTeX renumbers on every compile, so emitting
  keys gets correct numbering for free.
- **The `.bib` is the authority.** A key already written there is never
  recomputed, so a typed citation cannot break when the library grows, and the
  file stays yours to edit.
- A bibliography panel lists every entry and marks the ones nothing cites. It
  reads the source, so an entry appears the moment it is written.
- A document that cites but never declared a bibliography is given one, so a
  citation cannot silently become `[?]`.

### Compiling

`domain/paper_writer/compiler.py`.

- **Engine:** the bundled Tectonic, with a package cache warmed by
  `scripts/fetch-tex.sh`, so every starter template and an ordinary article,
  report or book compiles on a clean machine with no network
  (`tests/test_offline_templates.py` proves it with `--only-cached`). Every
  compile tries the cache alone first and reaches the network only for a file
  the cache truly lacks (ADR 2026-11-20). A document needing another package downloads it on
  its first compile. A system
  `tectonic` or `pdflatex` is used only when the bundled one is absent (source
  checkouts).
- **Auto-compile** a moment after you stop typing; compiling saves first. An
  *Auto* toggle hands control to the Compile button.
- **Auto-healing.** When a compile would fail, the compiler injects missing
  `\usepackage` lines (tikz, pgfplots, booktabs, ...), wraps a bare snippet into a
  full document, isolates a broken figure or table behind a placeholder, and as a
  last resort neutralises all figures, so you still get a PDF.
- **Indexes:** Tectonic runs BibTeX but not makeindex, so ThinkStack generates the
  `.ind` itself (`indexing.py`) and runs a second pass.
- **Errors:** engine diagnostics and missing-package hints are shown in the UI.
  A table row with the wrong number of cells is named in plain language
  (`_check_tables`); it is reported, never silently padded or truncated.
- **Save PDF** asks the desktop window where to save and names the file after
  the paper's title. In a browser it is an ordinary download.
- Every compile writes `main.synctex.gz`; `synctex.py` reads it (see
  FUTURE_WORK for the unfinished half).

---

## Bench

### Your machine

Memory, processor, graphics and how much text can be read at once, with
plain-language advice. *Re-examine* picks up changes such as closing other
applications. All hardware-derived decisions are made in
`infrastructure/capability.py` from facts passed in, so they are testable
without the hardware.

### Models

A card per model shows which jobs it does. Editing assignments takes effect on
the next request; no restart. A model that is assigned but not being used (too
large for the memory free right now, or outranked) says so on its card.

**No language model ships in the installer.** Three ways to get one, all into
the same registry (`registry.py`):

- **Add a model:** a native file dialog (or a typed path outside the desktop app)
  for a `.gguf` you have. It is **referenced where it is, never copied**.
- **Already on this machine:** models found in ThinkStack's model folder, a
  running Ollama server, Ollama's on-disk store, and LM Studio. Ollama-served
  models are reached over HTTP; their blobs cannot be opened by llama.cpp
  directly.
- **Get more models:** ThinkStack's catalog (`catalog.py`), each judged against
  this machine, plus Hugging Face search.

**Reusing what you have.** Runtimes name the same weights differently
(`qwen2.5:1.5b`, `Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`). `discovery.model_key()`
reduces each to `family/size` (`qwen2.5/1.5b`) so they compare equal.
Quantisation is ignored on purpose: a q4 and a q8 do the same job here. Every
probe is optional and guarded; a missing tool finds nothing and never delays
startup.

**Removing a model** is two actions: *Stop using it* forgets the model and keeps
the file; *Delete permanently* is offered only for files ThinkStack downloaded
itself. An imported file is never deleted from here.

**Hugging Face.** Search runs on submit, not as you type. Typing `owner/name`
goes straight to that repository. Each quantisation shows its size against free
memory and whether it will run at a useful speed here, before you download.
Download URLs are built from a repository id and filename, never accepted from
the caller.

**Suggestions consider speed, not only fit.** Without a usable GPU, suggestions
are capped at `CPU_COMFORTABLE_GB`. Larger models are still listed, marked as
slow.

### Which model does which job

Four tasks route independently: `general`, `analysis`, `gap_analysis`,
`latex_writer`. `domain/model_manager/router.py` resolves each, strongest claim
first:

    user-assigned (Bench) -> release-assigned (manifest) -> bundled.json
      -> TASK_MODEL_MAP / .env (deprecated) -> base model path

`bundled.json` is empty now that no model ships, so on a fresh install a task
resolves to nothing until a model is added. Each candidate must exist *and* fit
the memory free right now. A model skipped
for size is reported, so a weak summary has an explanation. Every generation
call must name its task; one that does not silently gets `general`.

### Graphics acceleration, on request

The bundled inference engine is processor-only, so the installer works on every
machine. If yours has graphics hardware llama.cpp can use, Bench offers to
download the Vulkan build of the engine (`infrastructure/acceleration.py`,
`accel_download.py`).

- **Vulkan, so any vendor:** NVIDIA, AMD, Intel, integrated, through the Vulkan
  loader your graphics driver already installed. On Linux that includes cards on
  Mesa's open-source drivers. Only ThinkStack's own engine is downloaded, never a
  driver.
- **It names the device it would use** (`infrastructure/vulkan.py`). A software
  renderer (llvmpipe) is listed but excluded: it is the CPU pretending to be a
  GPU, and offloading to it is slower.
- **The size shown is read from the release manifest**, not estimated.
- **Checked before it is switched on:** checksum, then loaded in a separate
  process; only if that survives is it enabled. Otherwise nothing changes and you
  are told why.
- **Reversible:** "Go back to the processor" keeps the files, so turning it on
  again is instant.
- **Not on macOS.** The right path there is Metal, which the engine is not built
  with; Bench says so rather than offering it.

---

## Local inference

`infrastructure/ollama_client.py`.

- **Two runtimes:** `llama.cpp` loading a GGUF directly, or a running Ollama over
  HTTP.
- **Structured output:** a GBNF grammar constrains `llama.cpp` to strict JSON
  where a task needs it. A thinking model (Qwen3) would emit `{}` under it,
  because its `<think>` block has nowhere to go, so its think block is
  pre-filled empty and the grammar applies to the answer. Any reasoning left in
  plain-text output is stripped before it reaches a document.
- **One model resident at a time;** the runtime swaps on demand to cap memory.
- **Sized to the machine.** The Tauri shell reads RAM, CPU and GPU at launch
  (`src-tauri/src/diagnosis.rs`, `nvidia-smi` under a timeout) and hands the
  result to the backend, so the backend never imports heavy ML libraries just to
  detect hardware. A model loads only if it fits the available-memory budget with
  headroom; otherwise a smaller one is used.

---

## Updates

Nothing is checked automatically. Press **Update app** in the sidebar: if a
newer build exists you are told the version and asked before anything
downloads. The bundle is verified against ThinkStack's public key, installed in
place, and the app restarts with papers, projects and settings kept. The sidebar
shows the running version, which is what a bug report should quote.

Channels are **stable**, **beta** (testers) and **nightly**; how each is
published is in [CONTRIBUTING.md](../CONTRIBUTING.md#releasing).

---

## Training-data collection

Each Scribe generation is logged as a prompt → output pair in chat format
(system / user / assistant) as JSONL under the data directory's `training/`
folder, for future fine-tuning (`domain/fine_tuning/data_collector.py`). It never
leaves the device. `save_gap_analysis_pair` exists but nothing calls it yet, so
analysis is not collected.
