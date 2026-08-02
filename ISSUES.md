# Known issues

Open problems, newest first. Written 2026-08-01 after the
Bibliotekh · LitGraph · Scribe consolidation, revised the same day after
investigating the analysis pipeline, and again on 2026-08-02 after merging
`dev` and clearing both BLOCKING items.

---

## Resolved 2026-08-02

### The canvas was laggy — issue 1 below

All four causes, in `useCanvas.js`. Hovering off a node and selecting a node
both called `render()`, which cleared and re-created every hull, edge, node,
label and sub-node and re-attached a listener to each. Both are `restyle()`
now, which writes opacity, fill and the relevance arc onto elements that
already exist.

Measured in the browser: hovering, selecting and searching produce **zero**
structural mutations. 60 pointermoves produce **one** transform write (was 60,
each also sweeping every label in the document). A slow 150 px lasso keeps 38
points out of 300 events.

The split exposed two more. `render` never depended on `graph` — `model` and
`state` are mutated in place so their identity never changes — which meant a
reload after ingest updated the model and left the canvas drawing the previous
library. And the hover handler closed over `matches`; listeners are attached
once per structural rebuild, so once selection stopped rebuilding, that value
would have gone stale.

### Nodes and labels overlapped — issue 2 below

`graph_builder._separate()` relaxes the PCA projection until crowded pairs are
`MIN_SEP` (0.055 of the unit square ≈ 60 px between centres) apart, seeded by
the PCA positions and capped at a fixed pass count so the same library always
draws the same map. 60 papers reach the full gap; 200 go from 0.003 to 0.026,
and the padded square cannot hold much beyond 230 at this spacing.

Labels are a separate problem — spacing nodes cannot make a 26-character title
fit beside its neighbour — so `placeLabels()` walks them in draw order and hides
any whose box lands on one already placed. Draw order is priority order: a theme
label outranks a paper title.

`tests/test_graph_builder.py` had a test named
`test_identical_documents_do_not_stack_or_blow_up` that asserted only that the
coordinates were finite. They were; all five were also `(0.5, 0.5)`. It asserts
the spacing now.

Still open, deliberately: a gap marker is drawn at its evidence centroid offset
a flat 70 px upward with no check that the spot is free. Marked in-code.

### Claims and summaries run by hand never reached the canvas

The canvas reads `doc_analysis_cache`, and only the ingest-time precompute ever
wrote to it. Pressing Claims or Summarize recorded a run in the history and
nothing else, so the work was done, paid for, and invisible: no sub-nodes to fan
out, and the node still labelled unanalyzed.

Both routes write through now, via a new `DocAnalysisCache.merge()` — `put()`
takes both halves, so the claims route would have erased the summary. A
comparative summary over several papers is deliberately not cached per document.

---

## Resolved 2026-08-01

### The SLM output "mojibake" was never an ingestion bug — and is not a code bug

Recorded because the original entry (issue 4 below) named the wrong cause, and
the wrong cause is worth writing down so nobody chases it twice.

The symptom is real: `AppData/Local/ThinkStack` holds titles and summaries with
`U+FFFD` at exactly the non-ASCII characters — `Drug<?>Drug`, `1<?>10`. The
original guess was an ingestion-side encoding bug. It is not. Every layer was
tested against the real files and the real models:

| Layer | Result |
| --- | --- |
| `extract_text` on the real PDF | clean — 225 en-dashes, ligatures (ﬁ ﬀ ﬃ) intact |
| `_extract_title` (pure regex over that text) | clean |
| llama.cpp `tokenize` → `detokenize` | byte-exact round trip |
| `create_chat_completion`, non-streaming | clean |
| the same, streaming | clean |
| the same, under `JSON_GBNF_GRAMMAR` | clean |
| the full metadata path, real PDF, Qwen3-4B on GPU | clean |
| `httpx.Response.json()` (the Ollama path) | 0.28.1 decodes bytes via `json.loads`; UTF-8 safe |

Two facts locate it. The corrupted store is `AppData/Local/ThinkStack` — the
**packaged app's** state dir — while the dev store (`data/vectorstore`) is
clean. And the corrupted title omits an author line that today's regex path
includes, so it was written by the SLM path, not the regex one.

So it was produced by the packaged build running the bundled **0.5B on CPU**,
which is simply worse at reproducing exotic characters than the 4B this machine
develops against. That makes it a model-quality observation, not a decode bug,
and the fix is re-ingestion plus the model-quality work — not a patch.

**Do not add defensive re-encoding for this.** It cannot be reproduced against
current code, and a guard for an unreproducible failure is a guard nobody can
ever test.

### Theme clustering returned one-paper themes

`cluster_by_themes` asked the SLM to cluster papers from text excerpts. On a
library of three closely-related DDI papers it returned three themes of one
paper each — not a clustering, and it made LitGraph's "territory encodes
category" rule encode nothing. A hallucinated `doc_id` also drew a hull around
nothing, with no way to notice.

Membership now comes from cosine between the document centroids already written
at ingest; the model only *labels* groups whose membership it cannot change.
Verified live on the two-paper dev library: one theme, both papers, labelled
"Drug-Drug Interaction Prediction", 23.7 s.

### Valid JSON was being confused with correct JSON

`JSON_GBNF_GRAMMAR` constrains the model to emit valid JSON. Nothing constrained
it to emit the *right* JSON, and seven call sites assumed the right shape:

- `document_analysis.py` and `gap_pipeline.py` called `item.get(...)` on list
  entries that a small model routinely returns as bare strings. Both calls sat
  **outside** the `try` that was meant to contain parse failures, so the
  `AttributeError` escaped as a 500 (or as "ingest-time analysis skipped").
- `data.get("claims", [])` against a bare-list response returned `[]`, which is
  indistinguishable from "this paper genuinely has no claims".
- `claim_type`, `confidence`, `gap_type`, `severity` were passed through
  unvalidated, so an invented category reached the canvas as a node label.

`domain/analysis/parsing.py` now coerces these shapes and recovers the content
rather than discarding it — a claim the model wrote as a bare string is still a
claim. 32 cases in `tests/test_slm_contract.py`.

### The packaged build reported 0.0 GB RAM — root cause found

`psutil` was **not installed in `.venv-build`**, the environment PyInstaller
freezes from. `--hidden-import psutil` tells PyInstaller to bundle a module it
cannot see being imported; it does **not** install it. Absent from the venv,
the freeze silently produced a build without it, `_detect_ram` caught the
`ImportError`, and every packaged install got `(0.0, 0.0)` and pinned itself to
the `low` tier — 2048 context, smallest model.

The flag is precisely why this cause looked impossible. It appears in
`.github/workflows/_build-desktop.yml:342` and in the spec, so "psutil is
missing" was ruled out by inspection. Nobody checked the build venv.

`requirements.txt` lists 15 packages; `.venv-build` was missing exactly one, and
it was this one. CI installs from `requirements.txt` so CI builds are fine — the
drift was local, and the local artifact is what was tested and filed.

Three fixes, because one would not have been enough:

1. `psutil` installed into `.venv-build`; it now reports medium tier, 15.2 GB.
2. `scripts/build.sh` gained a **preflight** that imports every runtime
   dependency in the build venv and fails loudly if one is missing. A
   `--hidden-import` for something uninstalled is now a build error, not a
   silently degraded app.
3. `_detect_ram` logs the real exception at error level (below), so the next
   instance of this names itself instead of needing an investigation.

### `thinkstack-api.spec` is not a second build path — it was never in the repo

Issue 5 below said the stale spec "would ship a broken app to anyone who ran
it". It cannot: the file is gitignored (`.gitignore:103-104`), has never been
committed on any branch, and PyInstaller regenerates it from the command line
flags on every run. It is a local build artifact, not a source file. Nothing to
fix and nothing to delete from the repo.

### `scripts/build.sh` could not run on Windows

It did `source .venv/bin/activate` (POSIX venv layout), used `:` as the
PyInstaller `--add-data` separator (Windows needs `;`), and called `python3`
(on Windows a Microsoft Store stub that does not run). So the documented build
path only worked on Linux/macOS and the Windows build was done by hand — which
is exactly how `.venv-build` drifted out of sync with `requirements.txt` and
produced the 0 GB bug above.

Now detects `Scripts/` vs `bin/`, prefers `.venv-build` then `.venv`, picks the
separator from `uname`, and uses a `$PY` that resolves correctly on both.

### Hardware detection crashed on machines that have a GPU

Worse than issue 6 below described. `hardware.py` read
`torch.cuda.get_device_properties(0).total_mem`; the attribute is
`total_memory`. `AttributeError` was not in the `except` list, so on a machine
that *actually has CUDA* the GPU probe raised instead of degrading to "no gpu".
It killed a script mid-run during this investigation.

Fixed, with `AttributeError` added to the catch so a future torch rename cannot
repeat it. `_detect_ram` now logs the real exception at error level — its old
"psutil not installed" warning was a guess, and that guess is what pointed the
packaged-build investigation at the wrong cause.

From source this machine now reports 15.2 GB RAM, RTX 4050, 6 GB VRAM, tier
medium. **The frozen-build half of issue 6 is still open** — see below.

---

## LitGraph

> Issues 1 and 2 are **resolved** — see the top of this file. The original text
> is kept because it is the record of what was measured and where.

### 1. ~~The canvas is laggy~~ — RESOLVED

Reported on a 3-paper library, so this is not a scale problem. It is several
compounding causes, all in `frontend/src/components/litgraph/useCanvas.js`:

- **Full scene rebuild on every hover-out.** `mouseleave` calls `render()`, which
  clears and re-creates every hull, edge, node, label and sub-node in the SVG,
  then re-attaches a listener to each. Moving the cursor across the canvas
  therefore rebuilds the whole DOM tree repeatedly. Marked in-code with a
  `ponytail:` comment as a known ceiling; it turns out to bite immediately, not
  at scale. **Fix:** a dim-only path that mutates `style.opacity` on existing
  nodes and never touches the DOM structure.
- **`render()` is rebuilt on every selection change.** It is a `useCallback`
  keyed on `matches`, `focus`, `expanded` and `colors`, and
  `useEffect(() => render(), [render])` re-runs whenever any of those change. So
  selecting a node re-creates the entire scene rather than restyling it.
- **`pointermove` does unthrottled work.** Panning calls `applyCam()` on every
  single move event, which writes the viewport transform *and* runs
  `semanticZoom()` over every label in the document
  (`querySelectorAll('.lg-label')`). **Fix:** coalesce into one
  `requestAnimationFrame` per frame.
- **The lasso path grows without bound.** Every `pointermove` pushes a point and
  re-serialises the whole path string. A slow drag produces thousands of points
  and an increasingly long `d` attribute rewritten each event. **Fix:** skip
  points closer than ~4px to the previous one.

### 2. ~~Nodes and labels overlap~~ — RESOLVED

There is no collision handling anywhere in the layout:

- **Node labels** are placed at a fixed offset (`y = r + 13`, centre-anchored)
  with no awareness of neighbours. PCA positions cluster related papers *tightly
  by design*, so in any real library the labels sit on top of each other and on
  adjacent nodes.
- **Titles are truncated at 26 characters** but still overflow horizontally,
  because truncation caps length, not rendered width.
- **Nodes themselves can overlap.** `graph_builder._project()` normalises PCA
  coordinates into the unit square but applies no minimum separation, so two
  near-duplicate papers land on nearly the same point. The `n < 3` circle
  fallback and the "one-dimensional library" guard both avoid *stacking*, but
  neither enforces spacing in the general case.
- **Gap markers can land on a paper node.** A gap is drawn at the centroid of the
  papers it cites, offset upward by a flat 70px — with no check that the spot is
  free.
- **Theme hull labels** are placed below each hull with no check against nodes or
  other hull labels; overlapping themes produce overlapping labels.
- **Claim sub-nodes** fan across an arc sized only by claim count, so a paper with
  many claims gets crowded labels regardless of available space.

**Fix direction:** either a light label-collision pass (hide or offset a label
when its box intersects one already placed, in draw order), or a few iterations
of simple repulsion on the projected coordinates before they are returned —
seeded by PCA so the layout stays deterministic and meaningful. Node radius is
already known server-side, so the separation constraint can live in
`graph_builder` rather than the client.

### 3. Prototype features not ported

The original HTML prototype (rev 3) had these working; the React version does
not. The prototype file itself is not in the repo — it is a local design
artifact on the author's machine — so this list is the record of what it did,
rather than a pointer to it:

- minimap, breadcrumb trail, keyboard node-walk, zoom in/out buttons (only "fit"
  exists)
- the reader pane — opening a paper at the passage that matched, and stepping
  between matches within it. The data is already there: `/api/search` with
  `group_by_doc` returns every matching chunk per paper in reading order, and the
  panel currently shows only the first four.
- density terrain, reading path, `Ctrl+K` command palette
- semantic zoom only fades labels; there is no level-of-detail switch by node
  count

### 4. Smaller LitGraph problems

- **No loading state during a run.** Clicking Summarize/Claims/Themes/Find-gaps
  disables the buttons and shows a small spinner, but a gap scan can take
  minutes; the old `GapAnalysis.jsx` had a full explanatory panel for this.
- **Errors are a toast that must be dismissed by hand** and are overwritten by the
  next error before the first has been read.
- **`title` falls back to the raw `doc_id`** when a PDF yielded no title metadata,
  so nodes can be labelled with a hex string.
- **Existing title metadata is mojibake** for papers in the packaged app's store
  (`Briefings in Bioinformatics, 00(0), 2021, 1<?>`). ~~an ingestion-side encoding
  bug~~ — this was investigated and the cause is neither ingestion nor a decode
  bug; see "Resolved" above. It clears on re-ingestion.
- **Panel hides below 900px** with no alternative affordance.

---

## Build / packaging

> Issues 5, 6 and 7 below are **resolved** — see the Resolved section at the top
> for what each one actually turned out to be. The original text is kept because
> two of the three named the wrong cause, and that is worth not repeating.

### 5. ~~`thinkstack-api.spec` is stale and would ship a broken app~~ — WRONG

- It stages the embedding model to `models/all-MiniLM-L6-v2`, but `config.py:94`
  looks in `data/models/all-MiniLM-L6-v2`. That exact mismatch is documented in
  the config comment as a bug that was already fixed once.
- It bundles **no GGUF model and no TeX engine** at all.

Anyone running `pyinstaller thinkstack-api.spec` gets a build that reaches for
HuggingFace on first ingest and cannot compile a PDF. CI does not use the spec —
`.github/workflows/_build-desktop.yml` and `scripts/build.sh` both use an inline
`pyinstaller` invocation with the correct `--add-data` flags. **Either fix the
spec to match, or delete it** so there is one build path.

### 6. ~~Hardware detection is broken in the frozen build~~ — RESOLVED

`/api/system/health` from the packaged backend reports:

```
"hardware": {"tier":"low","total_ram_gb":0.0,"gpu":"none","vram_gb":0.0,
             "recommended_ctx_size":2048}
```

`total_ram_gb: 0.0` is impossible. Because the tier drives context size and model
selection, every packaged install is likely being pushed to the most conservative
settings.

**Fully resolved.** Two separate faults wore one symptom. The `total_mem` /
`total_memory` crash is fixed, and the frozen build's zeros were `psutil` being
absent from `.venv-build` — a `--hidden-import` names a module to bundle, it does
not install one. Both the source run and the frozen build now report 15.2 GB and
tier medium on this machine. `scripts/build.sh` gained the dependency preflight
that makes this class of drift a build error rather than a degraded app.

### 7. ~~`scripts/build.sh` cannot run on Windows~~ — RESOLVED

It did `source .venv/bin/activate` (POSIX layout) and assumed a `.venv` that
does not exist here; the real build venv is `.venv-build` with
`Scripts/activate`. The documented local build path therefore only worked on
Linux/macOS. Fixed — and it was the upstream cause of issue 6.

### 11. The frozen sidecar bundles modules the app never runs

`tkinter`, `nltk` and `pytest` were all being collected into the shipped
backend. Each was verified unused by blocking its import and re-running every
runtime path (routes, embedding, search, graph, hardware), then added to
`--exclude-module`.

`sklearn` and `scipy` are **not** excluded despite the app never importing them
directly: `sentence_transformers` pulls `sklearn.metrics` at runtime, and
dropping it yields a build with no embeddings and no search. That was caught by
testing the exclusion rather than reasoning about it, and it is the reason the
list is short.

---

## Tests

### 8. `gguf_dir` fixture fills the disk and cascades ~40 failures

`tests/conftest.py:41` creates fake models with `f.truncate(size)`. On NTFS that
**allocates** the bytes rather than creating a sparse file, and the fixture is
used with sizes like 0.4 GB and 1.1 GB across ~29 tests.

A full `pytest` run left **23.8 GB** in `%TEMP%`, then failed with
`OSError: [Errno 28] No space left on device` — not only in the model tests but
in every later test using `tmp_path` (`test_file_manager`, `test_paper_writer`,
`test_local_vector_store`, …). Each file passes in isolation, which makes this
look like a flaky suite rather than a disk problem.

**Fix:** mark the files sparse on Windows (`fsutil sparse setflag`, or
`FSCTL_SET_SPARSE` via ctypes), or stop writing real bytes and stub the size
lookup the code under test actually calls.

### 9. `pytest-asyncio` is not installed locally

It is in `requirements-test.txt` but absent from this environment, so every
`async def` test errors with "async def functions are not natively supported"
(~26 tests: `test_gap_pipeline`, `test_routes_*`, `test_document_analysis`).
They do run in CI. `pip install pytest-asyncio` — note this failed here while the
disk was full from issue 8.

---

## Frontend build

### 10. Single 807 kB JS chunk

`npm run build` warns that the bundle exceeds 500 kB. Everything is in one chunk,
so the LitGraph canvas, Monaco/KaTeX and Recharts all load on first paint
regardless of which section the user opens. Route-level `React.lazy` would be the
obvious split.

---

## Status of the packaged build (2026-08-01)

Stopped mid-way, deliberately — resume from here:

| Step | State |
| --- | --- |
| CPU llama.cpp swap | done — `llama_cpp/lib` 1,441 MB → 7.9 MB |
| Assets fetched | GGUF 469 MB, MiniLM 88 MB, TeX 71 MB |
| Frontend build | done |
| PyInstaller freeze | done — `dist/thinkstack-api` = 1.4 GB |
| Frozen-backend smoke test | **passed** — healthy in 7s, `/api/graph` works |
| Rust compile | done — `tauri-app.exe`, 12 MB |
| MSI packaging | **not finished — stopped here** |

Uncompressed payload is 1.4 GB. CI compresses a comparable payload to an 800 MB
`.msi`, so the <1 GB target looks reachable, but **it has not been measured yet**.

To resume:

```bash
export PATH="/e/dev/cargo/bin:$PATH"
export RUSTUP_TOOLCHAIN=stable-x86_64-pc-windows-msvc
export TMP=D:/ts-tmp TEMP=D:/ts-tmp     # C: lacks headroom
npm run tauri build -- --bundles msi
```

Two things to keep in mind when resuming:

- Do **not** restore `dist/thinkstack-api/.env`. The dev `.env` pins
  `THINKSTACK_LLM_MODEL_PATH=E:/odysseus/...`, which exists only on this machine;
  a shipped artifact must use the bundled 0.5B instead.
- The bundle is CPU-only by decision (matching CI). GPU remains available to users
  through Ollama/LM Studio discovery, and to developers through the CUDA-wheel
  swap documented in `requirements.txt`.
