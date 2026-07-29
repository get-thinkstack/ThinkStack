# thinkstack

offline slm-based research assistant for students and independent researchers.
it ingests papers, searches them, summarizes them, finds research gaps, answers
questions grounded on your library, and helps you write latex, all on your own
machine. it runs as a tauri desktop app, or as a local server you open in your
own browser (bound to localhost, not hosted anywhere). either way nothing is
served to the internet and no data leaves the device: language-model inference
runs locally through `llama.cpp`, and embeddings run locally too.

## features

- **ingest and index pdfs.** text extraction (pymupdf, pdfplumber) followed by
  sentence-transformer embeddings, stored in a file-based vector store.
- **search.** combined semantic and keyword search across your collection.
- **analysis.** paper summaries, key-claim extraction, and thematic clustering.
- **gap finder.** surfaces under-explored areas and suggests research directions.
- **chat.** a retrieval-augmented assistant grounded on the papers you select.
- **paper writer.** an ai-assisted latex editor with a live client-side preview
  (katex for math, html for structure) and a compiled-pdf tab. the compiler adds
  missing packages, wraps bare snippets into full documents, recovers from
  errors, and still produces a pdf when a single figure or table is broken.
- **fine-tuning data.** prompt-to-latex pairs are collected passively as jsonl
  for a future qlora fine-tuning run.
- **encryption vault.** papers can be encrypted locally with password-derived
  keys (a kdf plus an authenticated cipher). nothing is uploaded.

## documentation

- **[docs/ABOUT.md](docs/ABOUT.md)** — what ThinkStack is, how to install it, and
  how to use each feature (start here as a user).
- **[docs/FEATURES.md](docs/FEATURES.md)** — the detailed feature reference and
  roadmap.
- **[scripts/README.md](scripts/README.md)** — the devops runbook: the branch
  model, cutting a release, the local gate, and the git hooks.
- **[docs/ADR.md](docs/ADR.md)** — every architecture decision and *why* it was
  made, including the release pipeline.
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — setup, the branch model, what blocks
  your push, how to merge and how to release (and who may), and how to add tests
  or models.
- **[CHANGELOG.md](CHANGELOG.md)** — what changed in each released version.

Two genres, kept apart on purpose: `docs/ADR.md` records **why**, and
`scripts/README.md` + `CONTRIBUTING.md` are the **how-to**.

## architecture

the python backend lives at the repository root and serves both the rest api and
the built react ui. the tauri shell wraps that backend into a desktop window.

```text
main.py            fastapi app: serves the react spa and /api, with spa-fallback routing
config.py          pydantic-settings config (env prefix: THINKSTACK_)
api/               rest endpoints (documents, search, analysis, gaps, chat,
                   papers, encryption, system)
domain/            core logic: ingestion, knowledge_base, search, analysis,
                   gap_finder, chat, paper_writer, encryption, fine_tuning
infrastructure/    llm client (llama.cpp wrapper), vector store, hardware profiler
frontend/          react 19 + vite spa (built to frontend/dist, served by fastapi)
src-tauri/         tauri 2 desktop shell (rust): starts and supervises the backend
scripts/           setup / dev / validate / build helpers and tests
data/              runtime state: uploaded papers, vector store, models
                   (gitignored, recreated on demand)
```

inference is local through `llama.cpp` (`llama-cpp-python`, gguf models) on cpu
or gpu. the installer bundles **one** model - a 0.5b used for chat, search, and
the paper writer - so a fresh install works offline immediately with no download.
the structured-json analysis tasks (summarize, claims, gap finder) do better on a
larger model, so the app offers to fetch a 1.5b **only** when the machine can run
it and no equivalent is already installed (it reuses models you already have via
ollama or lm studio). without it, analysis degrades to the 0.5b rather than
failing. only one model is resident at a time; the runtime swaps on demand to
keep memory bounded, and falls back to cpu when no usable gpu is present.

## quick start

### 1. clone and bootstrap

```bash
git clone <repo-url> && cd ThinkStack
./scripts/setup.sh
```

this installs system dependencies, rust, the python venv and packages, node
modules, and a latex compiler. pass `--skip-system` or `--skip-rust` to skip
steps you have already done.

### 2. download a model

```bash
mkdir -p data/models
pip install huggingface-hub
huggingface-cli download Qwen/Qwen2.5-0.5B-Instruct-GGUF \
  qwen2.5-0.5b-instruct-q4_k_m.gguf --local-dir data/models
```

the 0.5b model (about 400 mb) is light enough for low-ram machines, and is the
one the installer ships. for the analysis features to produce their best output,
also download the 1.5b model (the packaged app offers this at first run instead):

```bash
huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct-GGUF \
  qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir data/models
```

any other gguf model can be dropped into `data/models/` and selected as the
active model.

### 3. run

web app (browser):

```bash
./scripts/dev.sh
```

this starts the backend at `http://localhost:8000/docs` and the vite dev server
at `http://localhost:3000` with hot reload and an api proxy.

desktop app (tauri):

```bash
./scripts/dev.sh --tauri
```

or manually, in two terminals:

```bash
# terminal 1: backend + frontend
./scripts/dev.sh

# terminal 2: desktop window
source "$HOME/.cargo/env"   # if rust was installed this session
npm run tauri dev
```

the desktop shell ([src-tauri/src/lib.rs](src-tauri/src/lib.rs)) starts the
backend, shows a loading screen that polls until the backend is ready, opens the
ui, and stops the backend it spawned when the window closes.

set the `THINKSTACK_PYTHON`, `THINKSTACK_PROJECT_DIR`, or
`THINKSTACK_LLM_MODEL_PATH` environment variables if auto-detection does not fit
your setup.

## scripts

| script | purpose |
|--------|---------|
| `scripts/setup.sh` | one-time bootstrap (system deps, rust, python, node, latex) |
| `scripts/install-hooks.sh` | activate the shared git hooks (run once per clone) |
| `scripts/dev.sh` | start the backend and frontend dev servers (add `--tauri` for desktop) |
| `scripts/preflight.sh` | run exactly what ci runs, before pushing |
| `scripts/validate.sh` | the fuller local gate (python, frontend, rust) |
| `scripts/build.sh` | production build (frontend, pyinstaller, tauri) |
| `scripts/promote.sh` | move work dev -> beta -> main and ship that channel's installers |
| `scripts/release.sh` | bump the version and tag a release |
| `scripts/compose-updater-manifest.sh` | build the auto-updater manifest (`latest.json`) |
| `scripts/set-repo.sh` | retarget the project at a different github owner/repo |

see [scripts/README.md](scripts/README.md) for the branch model and the full runbook.

## production build

```bash
./scripts/build.sh
```

the pipeline has four steps:

1. build the react frontend into `frontend/dist/`.
2. freeze the python backend with pyinstaller (`--onedir`) into
   `dist/thinkstack-api/`.
3. verify the frozen backend. tauri bundles that directory as the `api/`
   resource, so no separate sidecar copy is needed.
4. compile the tauri app into `src-tauri/target/release/bundle/`.

the installers land in `src-tauri/target/release/bundle/` (`.deb`, `.rpm`, and
`.AppImage` on linux, `.dmg` on macos, `.msi` and `.exe` on windows).

releases are cut by pushing a tag, never by pushing a branch — see
[scripts/README.md](scripts/README.md) for the branch model and the release
runbook, and [docs/ADR.md](docs/ADR.md) for why the pipeline is shaped that way.

## prerequisites

- python 3.11 or newer
- node.js 18 or newer
- rust toolchain (`rustup`), for the desktop build only
- at least one gguf model for llama.cpp (see quick start)
- `pdflatex` on `PATH`, required by the paper writer:
  ```bash
  # fedora
  sudo dnf install texlive-scheme-basic texlive-collection-latexrecommended
  # ubuntu / debian
  sudo apt install texlive-latex-recommended
  # macos
  brew install --cask mactex-no-gui
  ```

## configuration

all settings use the `THINKSTACK_` environment-variable prefix (see
[config.py](config.py)). the common ones:

| variable | purpose | default |
|----------|---------|---------|
| `THINKSTACK_LLM_MODEL_PATH` | path to the gguf model or a models directory | `data/models/` |
| `THINKSTACK_LLM_ANALYSIS_MODEL` | heavier gguf for summarize/claims/gaps | `qwen2.5-1.5b-instruct-q4_k_m.gguf` |
| `THINKSTACK_LLM_GPU_LAYERS` | gpu layer offloading (-1 = auto, 0 = cpu only) | `-1` (auto, with cpu fallback) |
| `THINKSTACK_LLM_CTX_SIZE` | context window size | `4096` |
| `THINKSTACK_PYTHON` | override the python interpreter path | auto-detected |
| `THINKSTACK_PROJECT_DIR` | override the project root path | auto-detected |

the active model selection is persisted in `data/active_model.txt` and applied
on start.

## technology stack

| component | technology |
|-----------|------------|
| desktop shell | tauri 2 (rust) with a system webview |
| frontend | react 19 + vite, recharts, framer motion, katex |
| backend | python, fastapi, uvicorn |
| model runtime | llama.cpp (`llama-cpp-python`, gguf; cpu by default) |
| embeddings | sentence-transformers |
| vector store | file-based numpy cosine store (json) |
| pdf processing | pymupdf and pdfplumber |
| latex | system `pdflatex` with an auto-healing compiler |
| live preview | katex (client-side math and structure rendering) |
| encryption | password-based kdf plus an authenticated cipher |
| auto-updates | tauri updater with signed github releases |

## tests

the paper-writer suite covers project management, latex compilation, graceful
error recovery, and the api over http:

```bash
source .venv/bin/activate
python tools/test_paper_writer.py
```

## license

for academic and research purposes.
