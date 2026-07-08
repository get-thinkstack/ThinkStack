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
- **paper writer** — ai-assisted latex editor with a live, overleaf-style pdf preview:
  it auto-adds missing packages, wraps bare snippets into full documents, recovers
  from errors, and still produces a pdf (with warnings) when a figure/table is broken
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
                   gap_finder, chat, paper_writer, encryption
infrastructure/    llm client (llama.cpp wrapper) + vector store
frontend/          react 19 + vite spa (built to frontend/dist, served by fastapi)
src-tauri/         tauri 2 desktop shell (rust) — starts & supervises the backend
scripts/           setup / dev / validate / build helpers + tests
data/              runtime state — uploaded papers, vector store, papers workspace
                   (gitignored, recreated on demand)
```

> note: the active frontend is `frontend/`. a leftover create-tauri-app scaffold
> remains at the repo root (`src/`, `index.html`, `vite.config.ts`) and is unused.

## running

### option a — desktop app (tauri)

the desktop shell ([src-tauri/src/lib.rs](src-tauri/src/lib.rs)) starts the python
backend itself, shows a loading screen that polls until the backend is ready (so a
slow first-launch model load never shows "localhost refused to connect"), opens the
ui, and **kills the backend it spawned when you close the window** so nothing is left
running on port 8000.

build (windows + msvc rust toolchain):

```bash
# 1. build the spa first — it is embedded into the exe at compile time
npm --prefix frontend run build

# 2. compile the desktop binary (needs cargo/rustup on PATH)
cargo build --release --manifest-path src-tauri/Cargo.toml
```

the binary is written to your cargo target dir, e.g. `target/release/tauri-app.exe`.
double-click it to launch.

> heads up (mvp): `lib.rs` currently hardcodes this machine's python venv, project
> directory, and model path in the `PYTHON` / `PROJECT_DIR` / `MODEL_PATH` constants.
> change those for another machine, or bundle the backend as a sidecar (pyinstaller)
> for a portable distribution.

### option b — local web app

```bash
python -m venv .venv
.venv\Scripts\activate              # windows  (use source .venv/bin/activate on unix)
pip install -r requirements.txt
npm --prefix frontend install
npm --prefix frontend run build

# point at a local gguf model, then run the server
set THINKSTACK_LLM_MODEL_PATH=E:\path\to\model.gguf
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

then open <http://localhost:8000>.

## prerequisites

- **python** 3.11–3.13
- **node.js** 18+
- **rust toolchain** (`rustup`, msvc on windows) — only needed for the desktop build
- a **gguf model** for llama.cpp (e.g. `Qwen3-4B-Instruct`, `gemma`)
- **pdflatex** on PATH — miktex (windows) or tex live — required by the paper writer
  to compile and preview pdfs

## configuration

all settings use the `THINKSTACK_` env prefix (see [config.py](config.py)). common ones:

| variable                     | purpose                                   |
|------------------------------|-------------------------------------------|
| `THINKSTACK_LLM_MODEL_PATH`  | path to the gguf model (or a models dir)  |
| `THINKSTACK_LLM_CTX_SIZE`    | context window size (desktop shell: 8192) |

the active model selection is persisted in `data/active_model.txt` and applied on start.

## technology stack

| component        | technology                                        |
|------------------|---------------------------------------------------|
| desktop shell    | tauri 2 (rust) + webview2                         |
| frontend         | react 19 + vite, recharts, framer-motion          |
| backend          | python fastapi + uvicorn                           |
| slm runtime      | llama.cpp (`llama-cpp-python`, gguf; cpu/gpu)     |
| embeddings       | sentence-transformers                             |
| vector store     | file-based numpy cosine store (json)              |
| pdf processing   | pymupdf + pdfplumber                              |
| latex            | system pdflatex (miktex / tex live) + auto-healing compiler |
| encryption       | password-based kdf + authenticated cipher (local vault) |

## tests

the paper-writer suite validates project management, latex compilation, graceful
error recovery, and the api over http:

```bash
.venv\Scripts\python scripts\test_paper_writer.py
```

## license

for academic and research purposes.
