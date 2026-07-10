# architecture decision records (adr)

## 2026-06-19: secure p2p networking layer
**decision:** adopt libp2p and public key infrastructure (pki) for user-to-user document sharing.
**rationale:** think stack is a privacy-first tool. rather than hosting user papers on a central database, users will serve files directly from their desktop instances. access is granted based on cryptographic signatures verified between peers.
**status:** accepted.

## 2026-06-19: migration to tauri desktop architecture
**decision:** bundle the entire python backend and frontend into a single native desktop application using tauri and sidecars.
**rationale:** running local ai models and a latex compiler requires direct hardware access, unrestricted file i/o, and bypassing browser sandboxes. tauri allows us to write the ui in react while maintaining native performance and minimal memory overhead compared to electron.
**status:** accepted.

## 2026-06-16: project renaming
**decision:** renamed the project from `scholarlens` to `think stack`.
**rationale:** the project scope has evolved into a broader, edge-ai focused research assistant and paper writer.
**status:** accepted.

## 2026-06-17: backend infrastructure audit & fixes
**decision 1:** renamed `chromadb_client.py` to `local_vector_store.py`.
**rationale:** the module did not use chromadb. it was a custom numpy-based cosine similarity implementation. the new name accurately reflects its function.

**decision 2:** added gbnf grammar to `llama_cpp` client.
**rationale:** prevented the llm from outputting conversational filler before json. this strict enforcement stops `json.loads()` crashes in downstream analysis modules, and lays the groundwork for forcing valid latex generation.

**decision 3:** added gpu fallback.
**rationale:** on machines where vram is insufficient (oom errors), the model will gracefully fallback to cpu-only inference rather than crashing the application.

## 2026-06-23: AI-assisted paper writer implementation
**decision:** implement the paper editor and compiler workflow as a core integrated component in the Tauri desktop application.
- **editor:** integrate CodeMirror as a lightweight, performant monospaced code editor within the React frontend of the Tauri desktop app.
- **file format:** use `.ths` (ThinkStack) extension representing raw user input/prompts. When generating, the local AI translates these prompts in-place to compilable LaTeX code.
- **compiler:** use system `pdflatex` to compile LaTeX code into a PDF, running two compiler passes to properly generate cross-references/indexes.
- **diagnostics:** parse `pdflatex` logs on compilation failure to extract clean, readable errors and present them directly under the editor.
- **testing:** create a standalone, automated unit and integration test suite (`scripts/test_paper_writer.py`) that tests all domain compiler operations and boots the FastAPI server to test API endpoints.
**status:** accepted.

## 2026-07-01: real-time latex preview (client-side)
**decision:** add a browser-side LaTeX → HTML renderer using KaTeX alongside the existing pdflatex compilation.
**rationale:** users need immediate visual feedback while editing LaTeX. waiting for pdflatex to compile on every keystroke is too slow. the client-side renderer handles common academic paper elements (sections, math, lists, tables, formatting) and renders them live. complex elements (tikz, pgfplots) still require the pdflatex compile step.
**implementation:** `LatexPreview.jsx` component using KaTeX for math. two-tab preview pane in `PaperWriter.jsx`.
**status:** accepted.

## 2026-07-01: cpu-only inference defaults
**decision:** change `llm_gpu_layers` from `-1` (all GPU) to `0` (CPU-only) as the default. change `llm_model_path` from a hardcoded Windows path to the project-local `data/models/` directory.
**rationale:** the app must work out-of-the-box on machines without GPU drivers (like fedora without CUDA). GPU acceleration is opt-in via `THINKSTACK_LLM_GPU_LAYERS=-1`.
**status:** accepted.

## 2026-07-01: cross-platform tauri shell
**decision:** replace hardcoded Windows paths in `lib.rs` with env var + auto-detection logic.
**rationale:** the previous constants (`PYTHON`, `PROJECT_DIR`, `MODEL_PATH`) only worked on one specific Windows machine. the new logic auto-detects the venv, project directory, and model path on both Linux and Windows.
**status:** accepted.

## 2026-07-01: fine-tuning data collection pipeline
**decision:** passively log every prompt → LaTeX generation pair to `data/training/latex_generation.jsonl`. gap analysis pairs logged to `data/training/gap_analysis.jsonl`.
**rationale:** to fine-tune the local SLM for better LaTeX generation and research gap analysis, we need training data. collecting it passively from real usage is the most natural source. data is stored in chat-format JSONL ready for QLoRA fine-tuning.
**implementation:** `domain/fine_tuning/data_collector.py` hooked into `routes_papers.py`.
**status:** accepted.

## 2026-07-01: dead scaffold cleanup
**decision:** removed the unused `src/` directory files (App.tsx, api.ts, main.ts, PaperWriter.tsx) and root-level test scripts (test_grammar.py, test_json.py).
**rationale:** these were leftover create-tauri-app scaffold and scratch test files. the active frontend is `frontend/`. keeping them caused IDE errors and confusion.
**status:** accepted.

## 2026-07-08: cross-platform ci/cd + desktop binary distribution
**decision:** implement a github actions workflow that builds ThinkStack desktop binaries for linux (x64 .deb/.rpm/.AppImage), macOS (universal .dmg), and windows (x64 .msi/.exe) on every version tag push.
**rationale:** users should be able to download a single file for their OS and install it with one click. the ci matrix runs pyinstaller to freeze the python backend, then tauri to compile the native shell. binaries are published to github releases.
**implementation:** `.github/workflows/build-release.yml` with 3-runner matrix. `tauri.conf.json` `externalBin` for sidecar bundling.
**status:** accepted.

## 2026-07-08: sidecar-first backend launch
**decision:** update `lib.rs` to prefer the bundled pyinstaller sidecar binary in production, falling back to `python -m uvicorn` for development.
**rationale:** production builds include the frozen backend as a sidecar binary next to the tauri executable. this eliminates the python/venv dependency for end users. developers still get the live-reload python workflow.
**status:** accepted.

## 2026-07-08: devops script overhaul
**decision:** rewrote all scripts (`setup.sh`, `dev.sh`, `build.sh`, `validate.sh`) with skip flags, colored output, macOS support, and a verification matrix.
**rationale:** a new developer should clone the repo, run `./scripts/setup.sh`, and be ready to build. `dev.sh --tauri` launches the entire stack in one command. `validate.sh` now checks python, frontend lint, and rust before pushing.
**status:** accepted.

## 2026-07-10: download landing page
**decision:** create a static html landing page (`docs/landing/index.html`) for github pages deployment with per-platform download buttons.
**rationale:** users visit the page, see buttons for their OS, and click to download the right binary. linux uses AppImage (works on any distro without root/package-manager). macOS uses a universal dmg (apple silicon + intel). windows uses an exe installer.
**status:** accepted.
