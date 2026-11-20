# Issues

What is broken, what is unfinished, what is limited by design, and what past
failures taught. Fixed defects are also recorded in [CHANGELOG.md](CHANGELOG.md);
the entries kept here are the ones whose cause is worth not rediscovering.

- [Open defects](#open-defects)
- [Unfinished polish](#unfinished-polish)
- [Limits by design](#limits-by-design)
- [Resolved: what each failure taught](#resolved-what-each-failure-taught)

---

## Open defects

### Product

- **A paper encrypted before 2026-11-19 holds plaintext until its password is
  next used.** Its v1 envelope carries only the joined text, and only the
  password can encrypt the rest, so the first read with it locks the paper at
  rest. Until then the files hold the text; no route serves it.
- **Model-written LaTeX tables can be malformed.** A row with more `&` than the
  `tabular` declares fails in Tectonic with `! Extra alignment tab`. Since
  2026-08-22 `compiler._check_tables` names the wrong row in plain language, but
  it reports and never repairs, and generation can still produce the table.
  Prevention is in FUTURE_WORK (grammar + compile before showing).
- **Users on ≤1.10.0 cannot update in place.** `window.confirm()` never returns in
  a Tauri webview on Windows, so the old update button cannot finish. They must
  reinstall; a broken updater cannot ship its own repair.
- **A Qwen3 model served by Ollama still thinks.** llama.cpp-loaded thinking
  models get an empty think block pre-filled (ADR 2026-11-20); the Ollama path
  sends its own request and was not changed, because it could not be tested here.

### Release tooling

- **`promote.sh release` derives a stale version** (printed 1.6.7 while 2.3.5
  is published). Cosmetic now that `release` publishes nothing.
- **Windows and macOS bundles have never been enumerated** file by file the way
  the Linux AppImage has.

### Tests

- **The Windows fake-model fix is unverified on Windows.** `tests/conftest.py`
  now marks fake models sparse (`FSCTL_SET_SPARSE`) before `truncate()`, and
  `test_a_fake_model_costs_almost_no_disk` measures allocated bytes, but CI and
  development run on Linux, where truncation was already sparse.

---

## Unfinished polish

Not broken, not finished. The interface is Aditya's and Jitvan's (from
2026-08-18); these are theirs to schedule, reorder or reject. Status was checked
against the code on 2026-11-19.

1. **A node click should explain the node.** Neighbours are listed now. Still
   missing: which gaps cite this paper (`model.gaps[].doc_ids`, read the other
   way), which theme it sits in and how many share it.
2. **Hidden labels have no way back.** `placeLabels` in `useCanvas.js` hides a
   label that collides; reveal it on hover, and let the focused paper keep its
   own.
3. **Level of detail by node count.** Semantic zoom only fades labels. On a large
   library, zoomed out should show theme territory and hide individual nodes.
4. **Prototype features not ported** from the original HTML concept (local-only,
   not in the repo): keyboard node-walk, breadcrumb trail, density terrain
   (shading sparse regions inside the library hull), a suggested reading path.
5. **Smaller things:** errors are a toast that must be dismissed by hand and is
   overwritten by the next one; "Fan out claims" is offered on papers with no
   claims; the LitGraph panel disappears below 900px with no alternative;
   which papers are still being analysed is not shown per node.

**Open question:** after every ingest, analysis, a re-cluster and a gap scan are
queued. Whether that stays reasonable on a large library with a small CPU model
has not been measured.

---

## Limits by design

- **Search scans every chunk.** That is what makes it exhaustive, and it is fine
  at a few thousand chunks. An approximate index is the upgrade if libraries grow
  much larger.
- **The TeX cache covers what the starters and common documents use**
  (article, report and book at 10, 11 and 12pt, Beamer, the template packages
  and TikZ libraries, imakeidx). Anything else needs a network on its first
  compile.
- **No retry if Ollama returns malformed JSON.** The GBNF grammar makes
  `llama.cpp` reliable; the Ollama path has no equivalent.
- **Metadata extraction has a long tail:** mathematics in a title, publisher
  cover pages before the paper (an Elsevier "Highlights" sheet as page 1), and
  brand-new arXiv submissions with no stamp yet (year is left empty rather than
  guessed). Rules have plateaued; the route past it is a small classifier
  (FUTURE_WORK).
- **Scanned PDFs have no text layer**, so nothing can be extracted or searched.
  That needs OCR, which is not shipped.

---

## Resolved: what each failure taught

Newest first. Each: symptom → cause → fix → the rule it left behind.

### 2026-11-19/20: what a line-by-line read of the code found

Each fixed with a test that fails without the fix.

- **"Encrypt" did not hide the paper.** It added an encrypted copy and left the
  chunk text and PDF plaintext; `GET /api/documents/{id}` returned the text with
  no password. Now chunk text and PDF are encrypted at rest and removing
  encryption restores both exactly (`domain/encryption/at_rest.py`, ADR
  2026-11-19). *Rule:* a security feature's tests must read what is on disk,
  not only what the API returns. The routes had 26% coverage.
- **Any web page could trigger seven write routes.** CORS stops a foreign page
  reading a reply, not sending a "simple" request (multipart, or no body).
  `main._refuse_foreign_writes` refuses a write whose Origin is foreign.
- **The interface promised a bundled model** three times after none shipped.
- **The reasoning-model guard checked an empty list** once nothing was bundled.
  It now checks `BASE_MODEL`, and a test proves the check can fail.
- **Untitled papers were labelled with a hex id** on the map; now the filename.
- **`promote.sh` reported that `main` released** ("a fix ships to users
  immediately"); a push to `main` publishes nothing.
- **The changelog was never promoted.** Only the dead `release.sh` did it.
  Now `ship.sh` renames `[Unreleased]` on `beta` and cherry-picks it to `dev`
  (ADR 2026-11-20), accepting a hand-resolved conflict if `dev` adds an entry
  in between.
- **Qwen3-4B, the catalog's best model, returned `{}` for gap finding.** Under
  the JSON grammar a thinking model cannot open `<think>`, so it closed the
  object at once. Now its think block is pre-filled empty; the same prompt gives
  5 gaps and 3 suggestions. *Rule:* "never bundle a reasoning model" guarded
  the bundled slot only; the downloadable one was never measured.
- **Encrypting left plaintext in two more places:** papers encrypted the old
  way (now locked at rest the first time their password is used), and past
  summary, claims and gap runs that quoted the paper (now removed with it;
  theme runs, which hold only names and membership, stay).
- **Four of six starter templates could not compile offline**, including the
  default paper. The warm-up document never loaded the TikZ libraries the
  templates load, never used Beamer, and only typeset the font sizes it
  happened to use. CI compiles with a network, so every missing file was
  downloaded silently. Running the built installer's backend with no network
  then showed the same for any plain `\documentclass{article}`: the default
  10pt size file was never warmed. Now the warm-up covers every starter, both
  default base sizes, the report and book classes, the index package and every
  font size and shape; its stamp records which warm documents proved it, so a
  change re-warms; and a heavy test compiles templates and ordinary documents
  with `--only-cached`. Even then the built app failed an indexed document
  offline: Tectonic fetches the bundle checksum for any cache miss, including
  LaTeX probing for an optional file that exists nowhere. The compiler now
  tries the cache alone first. *Rule:* test an offline promise offline, on the
  built app, with the network actually gone.
- **A local build bundled whatever TeX cache sat in `data/tex`.** `build.sh`
  ran `fetch-tex.sh` only when the engine binary was missing, and a failed fetch
  only printed a warning. It now always asks `fetch-tex.sh`, which re-warms
  anything its stamp does not prove, and stops the build on failure.

### 2026-08-15: the first round on other people's machines

Four defects from macOS and Windows testers after a fortnight of green suites,
all fixed in 2.3.5 with tests:

- **Windows: no PDF opened.** `mimetypes`, seeded from the Windows registry, has
  no `.mjs` entry, so the viewer's worker was served as `text/plain` and refused.
  Fixed at import, before the static mount.
- **The gap finder repeated findings.** Now deduplicated on the normalised
  description; evidence merged, worse severity kept.
- **Map nodes were hard to click.** An invisible hit target keeps a constant
  on-screen size at any zoom.
- **The page was too bright.** Only the page was lowered, not the desk.

*Rule:* two of the four were invisible to any suite by construction: one lived in
another OS's registry, one was pure geometry (`jsdom` computes no layout). That
is the boundary of automation, not a gap to fill with more tests.

### 2026-08-02: LitGraph lag, overlap, and invisible analysis

- **The canvas lagged on a three-paper library.** Hover-out and selection both
  called `render()`, rebuilding every hull, edge, node and label and re-attaching
  listeners; panning ran a label sweep on every `pointermove`; the lasso path grew
  without bound. Now `restyle()` writes onto existing elements, camera writes are
  one per animation frame, and lasso points closer than a few pixels are dropped.
  Measured: hover, select and search cause zero structural DOM mutations.
  Splitting this exposed two latent bugs: `render` never depended on `graph`
  (mutated in place, so identity never changed) and a reload after ingest drew the
  previous library; and the hover handler closed over a `matches` that would have
  gone stale.
- **Nodes and labels overlapped.** `graph_builder._separate()` relaxes the PCA
  layout until crowded pairs are `MIN_SEP` apart, seeded by PCA and capped at a
  fixed pass count so the same library always draws the same map. Labels are
  separate: `placeLabels()` hides any whose box lands on one already placed, in
  draw order (a theme label outranks a paper title). Gap markers later got the
  same separation pass. A test named
  `test_identical_documents_do_not_stack_or_blow_up` had asserted only finite
  coordinates; all five were `(0.5, 0.5)`. It asserts spacing now.
- **Claims and summaries run by hand never reached the canvas.** The canvas reads
  `doc_analysis_cache`, which only ingest-time precompute wrote. Both routes now
  write through `DocAnalysisCache.merge()` (`put()` would have erased the other
  half). A comparative summary is deliberately not cached per document.

### 2026-08-01: analysis and the packaged build

- **"Mojibake" in titles was a model-quality issue, not a decode bug.** `U+FFFD`
  appeared at non-ASCII characters in the packaged app's store only. Every layer
  (PyMuPDF extraction, llama.cpp tokenize round trip, streaming and grammar-
  constrained generation, the Ollama JSON decode) was tested clean against the
  real files. The corrupt entries were written by the bundled 0.5B on CPU. *Rule:*
  do not add defensive re-encoding for a failure nobody can reproduce; a guard
  nobody can test is not a guard.
- **Theme clustering returned one-paper themes** and once drew a hull around a
  hallucinated `doc_id`. Membership now comes from cosine between centroids; the
  model only names groups it cannot change.
- **Valid JSON was confused with correct JSON.** The grammar guarantees JSON, not
  the right shape: list items came back as bare strings (`item.get` raised outside
  the `try`, surfacing as 500s), a bare-list response read as "no claims", and
  invented categories reached the canvas. `domain/analysis/parsing.py` coerces
  and recovers; `tests/test_slm_contract.py` pins it.
- **The packaged build reported 0.0 GB RAM** and pinned every install to the
  lowest tier. `psutil` was missing from `.venv-build`. `--hidden-import psutil`
  names a module to bundle; it does not install one, which is exactly why the
  cause looked impossible. Fixes: installed; `build.sh` gained a preflight that
  imports every runtime dependency in the build venv; `_detect_ram` logs the real
  exception.
- **Hardware detection crashed on machines with CUDA.** `hardware.py` read
  `total_mem`; the attribute is `total_memory`, and `AttributeError` was not
  caught. Now caught, so a future rename degrades to "no GPU".
- **`build.sh` could not run on Windows** (POSIX venv path, `:` as the
  `--add-data` separator, `python3` as the Store stub), so Windows builds were done
  by hand, which is how `.venv-build` drifted. Now detects the layout and
  separator.
- **`thinkstack-api.spec` was suspected of shipping a broken app.** It is
  generated by PyInstaller on every run, gitignored, and never used by CI or
  `build.sh`. Nothing to fix.
- **The frozen backend bundled modules it never runs.** `tkinter`, `nltk` and
  `pytest` are excluded after blocking each import and re-running every runtime
  path. *Rule:* `sklearn` and `scipy` must **not** be excluded:
  `sentence_transformers` imports `sklearn.metrics` at runtime, and dropping it
  ships a build with no embeddings. Test an exclusion; do not reason about it.
- **A stale `.env` survived every rebuild for a week.** Tauri copies
  `bundle.resources` into `<target>/release/` without removing what is there, and
  `config.py` reads the `.env` beside the executable last, so a path on one
  developer's machine won over everything. `build.sh` had been clearing a
  directory that was not the real target, because `CARGO_TARGET_DIR` redirected
  it. `build.sh` now resolves `CARGO_TARGET_DIR` and clears the staged `api/`.

*Note on `--no-bundle`:* it produces a runnable desktop binary without an
installer, but it must be launched from the repo root, because with no installer
`sidecar_path()` falls back to `dist/thinkstack-api` relative to the working
directory.
