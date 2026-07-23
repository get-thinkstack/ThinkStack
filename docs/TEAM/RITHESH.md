# rithesh — feature ownership

## what i'm responsible for

### paper writer (latex workflow)
- the editor → AI → compiler → PDF pipeline
- `domain/paper_writer/compiler.py` — auto-healing pdflatex compilation, error parsing, package injection
- `api/routes_papers.py` — project CRUD + generate + compile endpoints
- `frontend/src/components/PaperWriter.jsx` — editor UI, AI prompt bar, real-time preview tabs
- `frontend/src/components/LatexPreview.jsx` — client-side LaTeX → HTML renderer (KaTeX for math)

### real-time latex preview
- client-side rendering using KaTeX: sections, math, lists, tables rendered live as you type
- two-tab preview pane: "Live Preview" (instant, no compilation) + "Compiled PDF" (pdflatex output)

### fine-tuning data pipeline
- `domain/fine_tuning/data_collector.py` — passively collects prompt → LaTeX pairs from every generate call
- training data stored as JSONL in `data/training/` for future QLoRA fine-tuning
- covers both `latex_generation` and `gap_analysis` task types

### desktop application & cross-platform bundling
- `src-tauri/src/lib.rs` — cross-platform Tauri shell: auto-detects python venv, project dir, model path; sidecar-first backend launch for production, python fallback for dev
- `src-tauri/tauri.conf.json` — configured `externalBin` sidecar, bundle targets (deb/rpm/AppImage/dmg/msi/exe)
- `.github/workflows/build-release.yml` — CI/CD pipeline that builds for Linux (x64), macOS (universal), and Windows (x64), publishes binaries to GitHub Releases on tag push; trimmed to bundle a single lightweight base model (see below)
- `docs/landing/index.html` — download landing page for GitHub Pages with OS auto-detection and per-platform install buttons
- `landing.html` (repo root) — the landing page actually intended for deployment; fixed its download buttons to wire real GitHub Releases URLs (they were static `href="#"` placeholders, and promised Windows/Linux ARM64 builds CI doesn't produce)

### model bundling + analysis-model routing
- CI bundles **both** Qwen2.5-0.5B (chat/search/paper-writer) and Qwen2.5-1.5B (summarize/claims/gaps) — the 0.5B emits unparseable JSON on the analysis tasks, so those route to the 1.5B. `file_manager.seed_bundled_models()` seeds them from the read-only bundle into the writable models dir on first run
- `infrastructure/ollama_client.py` keeps a **single model resident and swaps on demand** (unload current → load requested) to cap peak memory. GPU when available, safe CPU fallback (no crash on cpu-only machines)
- validated end-to-end on a 16GB CPU-only machine: chat/search/ingest/encrypt/paper-writer on 0.5B, summarize/claims/gaps on 1.5B, memory-safe swap confirmed
- **frozen-build packaging validated locally:** `--onedir` + `--collect-all llama_cpp` + `--collect-all sentence_transformers`; a frozen backend passed ingest/search/chat with zero import errors (llama_cpp `.so` + sentence_transformers data correctly bundled)

### backend merge reconciliation (demo → v1)
- rebased onto `demo`, which shipped a **broken (non-importable) `ollama_client.py`** and a duplicate-kwarg `routes_gaps.py`; reconciled `ollama_client.py` into one clean working file (kept demo's good infra: frozen-build paths, `.env`, bundled embedding model, `max_tokens` caps, onedir `resources` packaging) rather than taking demo's verbatim

### auto-updates & deployment
- `frontend/src/utils/updater.js` + `App.jsx` — launch-time update check (no-op in web build)
- `src-tauri` — `tauri-plugin-updater`/`-process`, `plugins.updater` config, `createUpdaterArtifacts`, capabilities
- `.github/workflows/build-release.yml` — signs bundles + publishes `latest.json`; `scripts/compose-updater-manifest.sh` builds the manifest, `scripts/release.sh` bumps+tags
- signing keypair generated; private key kept out of the repo (`~/.tauri`, gitignored `*.key`), public key in `tauri.conf.json`

### release & deployment documentation
- `docs/RELEASE_GUIDE.md` — cutting a release: pipeline stages, local build, the CI tag-push flow, `release.sh`, and a memory-pressure note for building Tauri on a dev laptop
- `docs/DEPLOYMENT_AND_UPDATES.md` — per-OS download, the "install locally?" answer, the full auto-update/hotfix flow, signing-key management, and known issues to fix before the next real bundle

### devops & automation scripts
- `scripts/setup.sh` — one-command bootstrap (system deps, rust, python, node, latex); macOS/Fedora/Ubuntu/Arch support; `--skip-system`/`--skip-rust` flags; verification matrix
- `scripts/dev.sh` — starts backend + frontend with `--tauri` flag for desktop; port-in-use detection
- `scripts/build.sh` — 4-step production pipeline (frontend → pyinstaller → sidecar → tauri); `--skip-pyinstaller`/`--skip-tauri` flags
- `scripts/validate.sh` — pre-commit checks (python syntax, imports, stale refs, frontend lint, cargo check)

### backend infrastructure
- refactored and audited the backend (`refactor/thinkstack-backend`)
- integrated chatbot module and fixed core backend issues
- added GBNF grammar to llama.cpp client for strict JSON/LaTeX output
- added GPU → CPU fallback logic in the LLM client
- fixed `config.py` defaults for CPU-only operation (portable model paths, `llm_gpu_layers=0`)

### testing
- `scripts/test_paper_writer.py` — unit + integration tests for compiler and API

### documentation
- ADR entries, features list, future scope, README, `RELEASE_GUIDE.md`, this file
