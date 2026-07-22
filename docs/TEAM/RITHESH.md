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

### lightweight base model policy
- CI now bundles only Qwen2.5-0.5B-Instruct (q4_k_m gguf, ~470MB) instead of both 0.5B and 1.5B, so the installer stays small and runs safely on low-end/low-RAM machines out of the box
- see [docs/RELEASE_GUIDE.md](../RELEASE_GUIDE.md) for the full list of places to update if the default model changes again

### release documentation
- `docs/RELEASE_GUIDE.md` — the reference for cutting a release: pipeline stages, local build steps, the CI tag-push flow, the version-bump checklist, and a memory-pressure troubleshooting note for building Tauri releases on a dev laptop while other tools are running

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
