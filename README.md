# thinkstack

offline slm-based research assistant for students and independent researchers:
ingest papers, search, summarize, find research gaps, chat over your library, and
write latex papers — all locally. runs as a desktop app (tauri) or as a local web app.

## features

- **ingest & index pdfs** — text extraction (pymupdf / pdfplumber) + sentence-transformer
  embeddings stored in a file-based vector store
- **search** — semantic + keyword search across your collection
- **analysis** — paper summaries and key-claim extraction
- **gap finder** — surfaces under-explored areas and suggests directions
- **chat** — a research assistant grounded on your selected papers (rag)
- **paper writer** — ai-assisted latex editor with a live, client-side preview (KaTeX for math,
  HTML rendering for structure) + compiled PDF tab. auto-adds missing packages, wraps bare
  snippets into full documents, recovers from errors, and still produces a pdf when a
  figure/table is broken
- **fine-tuning data** — passively collects prompt → LaTeX pairs for future QLoRA fine-tuning
- **encryption vault** — encrypt papers locally with password-derived keys
  (kdf + authenticated cipher); nothing is uploaded

all language-model inference is local via `llama.cpp` (`llama-cpp-python`, gguf models)
on cpu or gpu. embeddings run locally too. no data leaves your machine.

## architecture

the python backend lives at the repository root and serves both the api and the
built react ui; the tauri shell wraps it into a desktop window.

```text
main.py            fastapi app — serves the react spa + /api, with spa-fallback routing
config.py          pydantic-settings config (env prefix: THINKSTACK_)
api/               rest endpoints (documents, search, analysis, gaps, chat, papers,
                   encryption, system)
domain/            core logic — ingestion, knowledge_base, search, analysis,
                   gap_finder, chat, paper_writer, encryption, fine_tuning
infrastructure/    llm client (llama.cpp wrapper) + vector store
frontend/          react 19 + vite spa (built to frontend/dist, served by fastapi)
src-tauri/         tauri 2 desktop shell (rust) — starts & supervises the backend
scripts/           setup / dev / validate / build helpers + tests
data/              runtime state — uploaded papers, vector store, papers workspace
                   (gitignored, recreated on demand)
```

## quick start

### 1. clone & bootstrap

```bash
git clone <repo-url> && cd ScholarLens
./scripts/setup.sh
```

this installs system deps, rust, python venv + packages, node modules, and a
latex compiler. run with `--skip-system` or `--skip-rust` to skip steps you've
already done.

### 2. download a model

```bash
mkdir -p data/models
pip install huggingface-hub
huggingface-cli download Qwen/Qwen2.5-0.5B-Instruct-GGUF qwen2.5-0.5b-instruct-q4_k_m.gguf --local-dir data/models
```

`qwen2.5-0.5b-instruct-q4_k_m.gguf` (~400 MB) is the default bundled with releases — light
enough to run on low-end/low-RAM machines. for better quality (slower, more ram/vram): use
a larger gguf model such as `Qwen2.5-1.5B-Instruct-GGUF` or `Qwen3-4B-GGUF` instead — drop it
in `data/models/` and select it as the active model.

### 3. run

#### option a — web app (browser)

```bash
./scripts/dev.sh
```

opens the backend on `http://localhost:8000/docs` and the vite dev server on
`http://localhost:3000` with hot-reload + api proxy.

#### option b — desktop app (tauri)

```bash
# single command — starts backend, frontend, and the native desktop window
./scripts/dev.sh --tauri
```

or manually in two terminals:

```bash
# terminal 1: backend + frontend
./scripts/dev.sh

# terminal 2: desktop window
source "$HOME/.cargo/env"   # if rust was installed this session
npm run tauri dev
```

the desktop shell ([src-tauri/src/lib.rs](src-tauri/src/lib.rs)) starts the python
backend itself, shows a loading screen that polls until the backend is ready, opens
the ui, and **kills the backend it spawned when you close the window**.

> set `THINKSTACK_PYTHON`, `THINKSTACK_PROJECT_DIR`, or `THINKSTACK_LLM_MODEL_PATH`
> env vars if auto-detection doesn't work for your setup.

## scripts

| script | purpose |
|--------|---------|
| `./scripts/setup.sh` | one-time bootstrap (system deps, rust, python, node, latex) |
| `./scripts/dev.sh` | start backend + frontend dev servers (add `--tauri` for desktop) |
| `./scripts/validate.sh` | pre-commit checks (python syntax, imports, lint, rust check) |
| `./scripts/build.sh` | production build (frontend → pyinstaller → sidecar → tauri) |

`build.sh` flags: `--skip-pyinstaller`, `--skip-tauri`.

## production build

```bash
./scripts/build.sh
```

this runs a 4-step pipeline:
1. **builds the react frontend** → `frontend/dist/`
2. **freezes the python backend** with pyinstaller (`--onedir`) → `dist/thinkstack-api/`
3. **verifies the onedir backend** (tauri bundles `dist/thinkstack-api/` as the `api/` resource — no sidecar copy)
4. **compiles the tauri desktop app** → `src-tauri/target/release/bundle/`

the final distributable is in `src-tauri/target/release/bundle/` (`.deb`, `.AppImage`
on linux, `.dmg` on macos, `.msi` on windows). only the 0.5b base model (see below)
ships in the installer, to keep it small and low-footprint.

> for the full release process — cutting a version (`scripts/release.sh`), the ci
> matrix, and what to do if a build eats too much memory on your machine — see
> [docs/RELEASE_GUIDE.md](docs/RELEASE_GUIDE.md). for how users download per-OS and
> how in-app auto-updates work (tauri updater + signed github releases), see
> [docs/DEPLOYMENT_AND_UPDATES.md](docs/DEPLOYMENT_AND_UPDATES.md).

> **model routing:** chat / search / paper-writer run on the light 0.5b base model;
> the structured-json analysis tasks (summarize, claims, themes, gap-finder) route to
> a heavier `qwen2.5-1.5b-instruct` model (`THINKSTACK_LLM_ANALYSIS_MODEL`) because
> 0.5b produces unparseable json on them. only one model is resident at a time — the
> runtime swaps on demand to cap memory. drop the 1.5b gguf in `data/models/` (or it
> falls back to the base model).

## prerequisites

- **python** 3.11+
- **node.js** 18+
- **rust toolchain** (`rustup`) — only needed for the desktop build
- a **gguf model** for llama.cpp (see quick start above)
- **pdflatex** on PATH — required by the paper writer
  ```bash
  # fedora
  sudo dnf install texlive-scheme-basic texlive-collection-latexrecommended
  # ubuntu/debian
  sudo apt install texlive-latex-recommended
  # macOS
  brew install --cask mactex-no-gui
  ```

## configuration

all settings use the `THINKSTACK_` env prefix (see [config.py](config.py)). common ones:

| variable                       | purpose                                    | default          |
|--------------------------------|--------------------------------------------|------------------|
| `THINKSTACK_LLM_MODEL_PATH`    | path to the gguf model (or a models dir)   | `data/models/`   |
| `THINKSTACK_LLM_ANALYSIS_MODEL`| heavier gguf for summarize/claims/gaps     | `qwen2.5-1.5b-instruct-q4_k_m.gguf` |
| `THINKSTACK_LLM_GPU_LAYERS`    | gpu layer offloading (-1 = all, 0 = cpu)   | `-1` (auto; safe cpu fallback) |
| `THINKSTACK_LLM_CTX_SIZE`      | context window size                        | `4096`           |
| `THINKSTACK_PYTHON`            | override python interpreter path           | auto-detected    |
| `THINKSTACK_PROJECT_DIR`       | override project root path                 | auto-detected    |

the active model selection is persisted in `data/active_model.txt` and applied on start.

## technology stack

| component        | technology                                         |
|------------------|-----------------------------------------------------|
| desktop shell    | tauri 2 (rust) + webview                            |
| frontend         | react 19 + vite, recharts, framer-motion, katex     |
| backend          | python fastapi + uvicorn                             |
| slm runtime      | llama.cpp (`llama-cpp-python`, gguf; cpu default)   |
| embeddings       | sentence-transformers                               |
| vector store     | file-based numpy cosine store (json)                |
| pdf processing   | pymupdf + pdfplumber                                |
| latex            | system pdflatex + auto-healing compiler             |
| live preview     | KaTeX (client-side math + structure rendering)      |
| encryption       | password-based kdf + authenticated cipher           |
| fine-tuning      | JSONL data collection → QLoRA (planned)             |

## tests

the paper-writer suite validates project management, latex compilation, graceful
error recovery, and the api over http:

```bash
source .venv/bin/activate
python scripts/test_paper_writer.py
```

## license

for academic and research purposes.
