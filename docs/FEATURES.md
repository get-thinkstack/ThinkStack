# ThinkStack — Features

A detailed reference for everything ThinkStack does. For "what is it and how do I
get started", see [ABOUT.md](ABOUT.md). For shipping releases, see
[../scripts/README.md](../scripts/README.md).

ThinkStack is an **offline, edge-AI research assistant**: a cross-platform desktop
app that ingests papers, searches and analyses them, finds research gaps, and
helps you write LaTeX — all running locally with no cloud dependency.

The app has four sections. Three follow the order the work happens:

| Section | What it does |
| --- | --- |
| **Library** | Collect — upload, encrypt and manage papers. |
| **LitGraph** | Understand — the map of your collection, and every analysis run. |
| **Scribe** | Write — AI-assisted LaTeX drafting and compilation. |
| **Bench** | Measure — what this machine can run, and the models it runs it with. |

- [Document ingestion](#document-ingestion)
- [Offline knowledge base](#offline-knowledge-base)
- [Semantic search](#semantic-search)
- [LitGraph](#litgraph)
- [Analysis & gap finder](#analysis--gap-finder)
- [Local LLM inference](#local-llm-inference)
- [Scribe — AI-assisted paper writer (LaTeX)](#scribe--ai-assisted-paper-writer-latex)
- [Paper encryption](#paper-encryption)
- [Hardware-aware model loading](#hardware-aware-model-loading)
- [Fine-tuning data collection](#fine-tuning-data-collection)
- [Updates](#updates)
- [Roadmap](#roadmap)
- [Known limitations](#known-limitations)

## Document ingestion

Turns a PDF into searchable, analysable knowledge.

- **Cascading PDF parser** — tries PyMuPDF (fast) first, falls back to pdfplumber
  for scanned or complex layouts.
- **Chunking** — splits text into overlapping chunks that respect paragraph and
  sentence boundaries, keeping page numbers via word-overlap scoring.
- **Metadata extraction** — pulls title, authors, abstract, and year via regex
  heuristics, with a small-language-model fallback for non-standard formatting.

## Offline knowledge base

- **Custom NumPy vector store** — embeddings and metadata are stored as JSON on
  disk with cosine-similarity search in NumPy. No external database (no ChromaDB,
  no server) — it just works offline for collections up to a few thousand chunks.
- **Local embeddings** — `sentence-transformers` (`all-MiniLM-L6-v2`), a 22M-param
  model that runs on the CPU (a 64-chunk batch embeds in ~0.2s).

## Semantic search

Search is purely meaning-based. The query is embedded and scored by cosine
similarity against **every chunk of every paper** — not a pre-truncated
candidate pool — so a passage buried on page 40 is as findable as one in the
abstract.

- **Exact-token bonus** — a small bonus (+0.05 × the fraction of query tokens
  appearing verbatim) is added after the cosine score. Meaning still decides the
  ordering; a literal match can only break a near-tie upward. This is what keeps
  rare tokens like `FedAvg` or an author surname findable without letting
  keyword overlap outrank a genuinely better semantic match.
- **Per-paper rollup** — `group_by_doc` returns papers rather than loose chunks,
  each carrying *every* chunk of its own that matched, in reading order. This is
  what LitGraph draws and what the reader pane steps through.

An earlier version fused semantic search with BM25 keyword search via Reciprocal
Rank Fusion. It was removed: paraphrase queries — the ones semantic search
exists for — were routinely out-ranked by lexically similar noise. See
[ADR.md](ADR.md).

## LitGraph

One canvas for the middle of the workflow. It replaced three separate pages
(Search, Analysis, Gap Finder), which were three views onto the same question:
what is in this collection, and what is missing from it.

- **Position encodes meaning** — each paper's chunk embeddings are averaged to a
  centroid and projected to 2D with PCA, so papers arguing about the same things
  sit together. Nothing is hand-placed.
- **Edges are similarity** — cosine between centroids above a threshold, capped
  to each paper's strongest few neighbours so a tightly-focused library does not
  render as a hairball.
- **Territory is theme** — clusters from a theme run are drawn as soft hulls.
- **Gaps are amber nodes** — placed at the centroid of the papers they cite, with
  dashed evidence edges back to each one.
- **Claims fan out** — double-click a paper to expand its extracted claims as
  sub-nodes.
- **The map is the selector** — shift-drag a lasso, or run a search, and the
  resulting set is what Summarize / Claims / Themes / Find-gaps operate on.

The graph is derived on every request from data that already persists
(embeddings, the analysis cache, past runs), so there is no graph state to
invalidate and no extra model call to build it.

## Analysis & gap finder

- Single- and multi-paper comparative **summarization**.
- **Thematic clustering** across a set of papers.
- **Gap analysis** — surfaces contradictions, methodological gaps, and missing
  validation, then proposes actionable research directions.

## Bench — model management

One screen for what the machine can run and what it runs it with.

**Your machine.** Memory, processor, graphics, and how much text can be read at
once, with plain-language advice. Re-examine picks up changes such as closing
other applications.

**Models.** A card per model showing what each job it is assigned to. Editing
those assignments takes effect on the next request; no restart. A model that is
assigned but not actually being used — too large for the memory free right now,
or outranked by a better one — says so on its own card.

**Adding a model.** Three routes, all leading to the same registry:
- *Add a model* opens a native file dialog (or a typed path outside the desktop
  build) for a `.gguf` you already have. The file is **referenced where it is**,
  never copied, so a multi-gigabyte import costs no extra disk.
- *Already on this machine* lists models found via Ollama, LM Studio or the
  models folder, assignable in one click. Ollama-served models are shown but not
  assignable: it stores weights as blobs llama.cpp cannot open, and the router
  reaches them over HTTP instead.
- *Get more models* lists what ThinkStack can fetch, each judged against this
  machine, and searches Hugging Face.

**Removing a model.** Two distinct actions, because they are different
intentions: *Stop using it* forgets the model and leaves the file alone;
*Delete permanently* is offered **only** for files ThinkStack created. An
imported model lives in the user's own folder and is never deleted from here.
Removing the included model is allowed, and says first what will stop working.

**Hugging Face.** The only part of ThinkStack that reaches the internet. Search
runs on submit, never as you type; the interface says so. Typing a full
`owner/name` goes straight to that repository's files. Each quantisation is
shown with its size against available memory and whether it will run at a useful
speed here — before the download, not after. Download addresses are constructed
from a repository id and filename, never accepted from the caller.

## Task routing

Four jobs route independently: general, analysis, gap finding, and Scribe.
Resolution order, strongest claim first:

    a model the user assigned  ->  a model a release assigned  ->  what this
    build bundled  ->  the deprecated task map  ->  the included model

Each candidate must exist *and* fit the memory free right now. A model skipped
for size is reported rather than silently dropped, so a disappointing summary
has an explanation.

## Local LLM inference

- **Dual runtime** — supports both `llama.cpp` (direct GGUF loading) and Ollama.
- **Structured output** — a GBNF grammar constrains `llama.cpp` output to strict
  JSON or LaTeX where the task needs it.
- **Task-based model routing** — every generation names the task it is
  (`general`, `analysis`, `gap_analysis`, `latex_writer`), and the router picks
  the model assigned to that task in Bench. Light work such as metadata
  extraction stays on the fast 0.5B; structured-JSON analysis routes to a
  heavier 1.5B that produces reliable JSON. Only one model is resident at a
  time; the runtime swaps on demand to cap memory.

## Scribe — AI-assisted paper writer (LaTeX)

Write ideas in plain language, get compilable LaTeX, and compile it locally with
no account, no queue and no time limit.

- **A paper is a folder** — a project is a directory on disk, and the file tree
  is the way into it. Add figures, split a long paper into section files, keep a
  `.bib` beside the document. Right-click for new file/folder, rename (F2),
  duplicate, copy/paste and delete; drop files straight onto a paper to add them.
  One file open at a time, as in Overleaf — a tab strip would cost height the
  editor and the preview want.
- **Figures work** — `\includegraphics{chart.png}` resolves because the file can
  actually be put next to `main.tex`. The compiler always ran with the project
  directory as its working directory; until the tree existed there was simply no
  way to place a second file there. Clicking an image previews it and shows the
  exact `\includegraphics` line to paste.
- **Editor and PDF, half the window each**, with draggable dividers that remember
  where you left them. The compiled PDF is the only preview: a second, browser-side
  renderer was removed because it disagreed with the real PDF, so what you looked
  at was never what you would publish.
- **Write at the cursor** — select plain English, press `Ctrl+Enter`, and it
  becomes LaTeX where you are working, not appended at the end. Optionally
  grounded in papers from your library, so the model writes from what they
  actually say.
- **Auto-compile** — rebuilds a moment after you stop typing (an "Auto" toggle
  turns it off and the Compile button drives it by hand). Compiling saves first,
  so an autocompile is also an autosave.
- **Auto-healing compiler** — what makes it robust. When compilation would fail it:
  - injects missing `\usepackage` lines the body needs (tikz, pgfplots, booktabs,
    …) — no more "Environment tikzpicture undefined";
  - wraps a bare AI snippet into a complete document;
  - isolates a single broken figure/table behind a placeholder so the rest of the
    paper still produces a PDF, and as a last resort neutralises all figures
    rather than failing outright.
- **Bibliographies and indexes build themselves** — the bundled engine runs BibTeX
  on its own. It does *not* run makeindex, so `\printindex` used to fail with
  `Undefined control sequence \indexentry`; ThinkStack now generates the `.ind`
  itself (sub-entries, `sort@printed` keys, `|hyperpage` encapsulators and
  `|(`…`|)` page ranges) and runs a second pass. Nothing extra to install.
- **Error surfacing** — when a compile fails, the parsed engine diagnostics (and
  missing-TeX-package install hints) show directly in the UI.

## Paper encryption

Optional password protection for a paper's text, done with modern authenticated
encryption:

- **Key derivation** — Argon2id turns your password into a 256-bit key, with a
  fresh random salt per paper (tuned to ~0.3–0.6s to resist brute force).
- **Cipher** — AES-256-GCM; decrypting with the wrong password fails loudly (the
  authentication tag check) rather than returning corrupted text.
- **Self-contained envelope** — everything needed to decrypt except the password
  travels in one versioned `TSENC1` string (KDF params + salt + nonce +
  ciphertext), so an encrypted paper is portable and future-proof.

## Hardware-aware model loading and suggestion

ThinkStack sizes itself to the machine it runs on.

- On launch the native Tauri shell runs a **hardware diagnosis** (RAM, CPU, GPU
  via `nvidia-smi` under a timeout) and hands it to the backend — so the app never
  has to import heavy ML libraries just to detect hardware.
- **Specification-based model selection** — a heavier model is loaded only if it
  fits the available-RAM budget (with headroom reserved for your other running
  apps); otherwise it gracefully downgrades to a lighter model instead of running
  out of memory.
- **CPU-only by default** — runs on any machine with no graphics drivers at all.

### Graphics acceleration, on request

ThinkStack ships a processor-only inference engine so the installer stays small
and works everywhere. If your machine has graphics hardware it can use, Bench
offers to add the graphics engine — about **90 MB**, downloaded only if you ask.

- **Vulkan, so it is not one vendor.** NVIDIA, AMD, Intel and integrated
  graphics all work, through the Vulkan loader that ships **with your graphics
  driver**. Nothing from NVIDIA, AMD or Intel is ever downloaded; the only
  download is ThinkStack's own graphics engine, which exists on no machine
  because it is ours. On Linux this includes cards reachable through Mesa's
  open-source drivers, so a machine with no proprietary driver installed is
  often still accelerated.
- **It names the device it would use.** A laptop can report three — a discrete
  card, an integrated chip, and a software renderer that is really the
  processor. All three are listed; the software one is shown and excluded,
  because offloading to it would be *slower* than the processor already doing
  the work.
- **The size shown is measured**, read from the release manifest rather than
  estimated, because the figure you agree to should be the figure downloaded.
- **It is checked before it is switched on.** The libraries are verified against
  a checksum, then loaded in a separate process. Only if that process survives
  is acceleration enabled. If it cannot run on your machine, nothing changes and
  you are told why.
- **Reversible.** "Go back to the processor" turns it off and keeps the files,
  so turning it on again is instant.
- **macOS already has it** — Metal ships in the Mac build, so nothing to add.
- You can **change the active model** yourself; the choice persists across
  restarts.

**Optional NVIDIA acceleration (advanced).** The shipped build is CPU-only, which
is why AMD and Apple Metal are reported but not used for offload — attempting it
would fail at model load. To run analysis on an NVIDIA GPU from a source
checkout, install the CUDA build and repair the two DLL issues the prebuilt wheel
has on toolkit-less machines:

```bash
pip install llama-cpp-python \
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
python tools/fix_gpu_dlls.py   # installs CUDA runtime DLLs, swaps a compatible CPU backend
python tools/verify_gpu.py     # prints tokens/sec and confirms offload
```

`fix_gpu_dlls.py` is idempotent — re-run it after any reinstall of
llama-cpp-python. Set `THINKSTACK_LLM_GPU_LAYERS=-1` to force full offload, or
`0` to force CPU.

### Reusing models you already have

If you already run **Ollama** or **LM Studio**, ThinkStack finds those models and
uses them instead of downloading its own copy. Nothing is ever fetched that your
machine already stores.

This matters because every runtime names the same weights differently:

| Where it came from | What it's called |
|--------------------|------------------|
| Ollama | `qwen2.5:1.5b` |
| LM Studio | `Qwen2.5-1.5B-Instruct-Q4_K_M.gguf` |
| ThinkStack | `qwen2.5-1.5b-instruct-q4_k_m.gguf` |

All three are the same model. ThinkStack reduces them to a canonical
`family/size` key (`qwen2.5/1.5b`) so they compare equal, then loads the copy you
already have. Quantisation is ignored on purpose — a `q4` and a `q8` of the same
model do the same job here, and re-downloading one because you have the other is
exactly the waste this avoids.

Models are discovered from ThinkStack's own directory, a running Ollama server,
Ollama's on-disk store (so it works even when Ollama isn't running), and LM
Studio. Every probe is optional and independently guarded: a missing tool or an
unreadable directory simply finds nothing, and never delays startup.

## Fine-tuning data collection

- Every AI generation passively logs a prompt→output training pair as JSONL under
  `data/training/`, in chat format (system/user/assistant), ready for future
  QLoRA fine-tuning.
- Separate datasets for `latex_generation` and `gap_analysis`. It's privacy-safe:
  the data stays on your device and never leaves it.

## Updates

**Nothing is checked automatically.** ThinkStack never contacts the network
unless you ask it to — an offline-first app that quietly phones home on every
launch is not offline in any sense that matters, even though the check carries
no personal data.

Press **Update app** in the sidebar to check. If a newer build exists you are
told the version and asked before anything downloads; the bundle is then
verified against ThinkStack's public key, installed in place, and the app
restarts. Your papers, projects and settings are kept. The sidebar also shows
the version you are running, which is what a bug report should quote.

Three channels exist: **stable** (everyone), **beta** (invited testers), and
**nightly**. See [../scripts/README.md](../scripts/README.md).

## Roadmap

Planned and in-progress work:

- **Feature-specific SLMs on CPU** — quantized small models downloaded and
  selected based on the user's hardware (the hardware-aware loading above is the
  foundation for this).
- **Federated cloud fine-tuning** — train QLoRA adapters on cloud GPUs, then sync
  tiny `.gguf` adapters down to apply over the local base model.
- **Secure P2P sharing** — share papers/drafts/analysis directly with specific
  peers via libp2p + public-key signatures, no central server.
- **Citation edges in LitGraph** — reference lists are not parsed today, so every
  edge on the map is semantic similarity. Citation edges would sit alongside them.
- **Density terrain** — shading the sparse regions *inside* the library hull, so
  the map draws the hole in the literature rather than only the papers around it.

## Known limitations

- **Full-corpus scan per search** — every query scores every chunk. That is what
  makes the search exhaustive, and it is fine at a few thousand chunks; an ANN
  index is the upgrade if collections get much larger.
- **Hover re-renders the whole canvas** — LitGraph rebuilds its SVG on hover-out.
  Invisible at typical library sizes; a dim-only path is the upgrade.
- **TeX cache covers the shipped preamble only** — the bundled package cache is
  warmed against every package the paper writer's preamble loads. A document that
  pulls in some other package needs a network connection the first time it is
  compiled; everything the app itself generates works offline.
- **Ollama JSON retries** — GBNF makes `llama.cpp` output reliable, but there's no
  extensive retry logic if the optional Ollama runtime returns malformed JSON.
