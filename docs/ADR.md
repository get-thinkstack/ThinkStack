# architecture decision records (adr)

## context and goals

the decisions below follow from a few fixed constraints, recorded here so the
rationale for the rest is clear.

**run entirely on-device, no cloud llm.** most research tools send papers and
prompts to a hosted llm api. that is a non-starter for users who cannot let their
data leave their machine: a medical or institutional researcher whose papers or
patient-linked data must not be uploaded, or used to train someone else's model.
running small language models locally also removes per-call api and cloud bills,
which matters for a student project with no budget. a secondary goal was to learn
how small language models and desktop application packaging actually work, rather
than wiring up another api client.

**"local web app" means localhost, not hosted.** the app ships two front ends
over the same local backend: a native desktop window (tauri) and a browser ui
served from `127.0.0.1`. neither is hosted on the internet; the browser mode is a
local server you open on your own machine. the only thing ever hosted is the
static download page, which handles no user data. this keeps the privacy claim
intact in both modes: nothing is served off-device.

**works without a network.** all inference, storage, and search are local, so the
app is fully functional offline. the one optional network call is the update
check (a version lookup against github releases), which sends no user data and
fails silently when offline.

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
**rationale:** the goal is to cut the friction of writing an academic paper. a researcher should be able to drop in their content and have the local model format it as compilable LaTeX, rather than learning LaTeX commands by hand or pasting drafts into a cloud LLM on top of an editor like Overleaf. keeping this local also fits the offline, on-device constraint (see context and goals).
**decision:** implement the paper editor and compiler workflow as a core integrated component in the Tauri desktop application.
- **editor:** integrate CodeMirror as a lightweight, performant monospaced code editor within the React frontend of the Tauri desktop app.
- **file format:** use `.ths` (ThinkStack) extension representing raw user input/prompts. When generating, the local AI translates these prompts in-place to compilable LaTeX code.
- **compiler:** use system `pdflatex` to compile LaTeX code into a PDF, running two compiler passes to properly generate cross-references/indexes.
- **diagnostics:** parse `pdflatex` logs on compilation failure to extract clean, readable errors and present them directly under the editor.
- **testing:** create a standalone, automated unit and integration test suite (`scripts/test_paper_writer.py`) that tests all domain compiler operations and boots the FastAPI server to test API endpoints.
**status:** accepted.

## 2026-07-01: real-time latex preview (client-side)
**decision:** add a browser-side LaTeX HTML renderer using KaTeX alongside the existing pdflatex compilation.
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
**decision:** passively log every prompt LaTeX generation pair to `data/training/latex_generation.jsonl`. gap analysis pairs logged to `data/training/gap_analysis.jsonl`.
**rationale:** to fine-tune the local SLM for better LaTeX generation and research gap analysis, we need training data. collecting it passively from real usage is the most natural source. data is stored in chat-format JSONL ready for QLoRA fine-tuning. this is groundwork for future work and a way to learn the fine-tuning pipeline end to end; it is not a shipped feature, and no fine-tuned model is used yet.
**implementation:** `domain/fine_tuning/data_collector.py` hooked into `routes_papers.py`.
**status:** accepted (data collection only; fine-tuning itself is future work).

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

## 2026-07-22: single lightweight base model bundled
**decision:** bundle only Qwen2.5-0.5B-Instruct (q4_k_m gguf, ~470mb) with every installer, dropping the 1.5b model that CI previously bundled alongside it.
**rationale:** the base model must be light enough to run on low-end/low-ram machines out of the box, and a smaller installer downloads faster. users who want higher quality can drop a larger gguf into `data/models/` themselves and switch to it as the active model.
**implementation:** `.github/workflows/build-release.yml` "download base model" step now pulls a single file. see [RELEASE_GUIDE.md](RELEASE_GUIDE.md) for the full list of places to update if this changes again.
**status:** accepted.

## 2026-07-22: `landing.html` (repo root) is the page of record
**decision:** `landing.html` at the repo root is the landing page intended for deployment, not `docs/landing/index.html`. fixed its download buttons (previously static `href="#"` placeholders promising windows/linux arm64 builds that ci does not produce) to wire real github releases urls matching what `build-release.yml` actually publishes, mirroring the working link-wiring script already present in `docs/landing/index.html`.
**rationale:** the two landing pages had drifted - different content, and only one had functioning download links. `docs/landing/index.html` is left in place for now but is not the deployment target; consolidate or remove it once `landing.html` is live and confirmed as the sole page.
**status:** accepted. hosting/deployment of `landing.html` itself is deferred until the desktop app has been tested end-to-end (see [RELEASE_GUIDE.md](RELEASE_GUIDE.md)).

## 2026-07-22: heavier model for structured-json analysis tasks
**decision:** route the structured-json analysis tasks (summarize, claims, themes, gap analysis) to a heavier model (`qwen2.5-1.5b-instruct-q4_k_m.gguf`, `settings.llm_analysis_model`) while chat/search/paper-writer keep using the lightweight 0.5b base model.
**rationale:** end-to-end testing showed the 0.5b model reliably works for free-text tasks (chat, latex generation) but produces truncated/unparseable json on the structured-extraction tasks, failing summarize/claims/gaps. the 1.5b model produces valid json. paired with demo's `max_tokens` caps (640/768/800) the analysis tasks became both reliable and faster (~20s single summary on cpu).
**implementation:** `TASK_MODEL_MAP` in `infrastructure/ollama_client.py` maps `analysis`/`gap_analysis` the 1.5b file; `_get_llama` keeps a **single model resident at a time and swaps on demand** (unload current, load requested) so peak memory stays at one model - important on low-ram machines. if the 1.5b file is absent, tasks fall back to the base model. see [RELEASE_GUIDE.md](RELEASE_GUIDE.md).
**status:** accepted.

## 2026-07-22: reconcile `ollama_client.py` after demo merge - GPU-when-available, safe CPU fallback
**decision:** when rebasing onto `demo`, its `infrastructure/ollama_client.py` was **syntactically broken** (a botched merge - two `_get_llama` defs, an unclosed `Llama(` call; would not import; `main`/`demo` both affected). rather than take it verbatim, `ollama_client.py` was reconciled into one clean working file that keeps the analysis-model routing + single-resident swap, and loads on gpu **when available** but falls back to cpu instead of crashing when a cuda build/gpu is absent. demo's `routes_gaps.py` also had a duplicate `max_tokens=` kwarg (syntax error) which was fixed.
**rationale:** demo's file enforced gpu-only and refused cpu fallback ("fail loudly"), which contradicts the cpu-safe / low-end-machine direction and would refuse to run on machines without a usable cuda setup. gpu-when-available with safe cpu fallback runs everywhere and is still fast where a gpu exists.
**status:** accepted. (demo's good infra changes were kept: frozen-build `BUNDLE_DIR`/`STATE_DIR` paths, `.env` support, bundled embedding model, `max_tokens` caps, onedir `resources` packaging.)

## 2026-07-22: in-app auto-updates via tauri updater + github releases
**decision:** ship updates through tauri's built-in updater. on launch the installed app checks a signed `latest.json` on github releases and, if a newer version exists, downloads + verifies + installs it and relaunches.
**rationale:** asking users to re-download and reinstall the app for every fix is poor ux, so updates should arrive in-app. this appears to conflict with the offline stance, but it does not: the app never requires a network, and the update check is a single non-blocking http get for a version manifest. it sends no user data (no papers, no queries, just a version number), and when the machine is offline the check fails silently and the app runs normally. an always-offline install simply never auto-updates. github releases (already the CI publish target) hosts both the installers and the manifest for free, and integrates with the updater's signature verification.
**implementation:** `tauri-plugin-updater`/`-process` in `Cargo.toml`+`lib.rs`; `plugins.updater` (endpoint + pubkey) and `bundle.createUpdaterArtifacts` in `tauri.conf.json`; `updater:default`/`process:default` capabilities; `frontend/src/utils/updater.js` called from `App.jsx` (no-op in the web build); CI signs with `TAURI_SIGNING_*` secrets and publishes `latest.json` via `scripts/compose-updater-manifest.sh`; `scripts/release.sh` bumps+tags. private signing key stays at `~/.tauri` (gitignored `*.key`), public key committed. full flow in [RELEASE_GUIDE.md](RELEASE_GUIDE.md).
**status:** accepted. needs a real signed build to verify end-to-end; see "open items before a public release" in [RELEASE_GUIDE.md](RELEASE_GUIDE.md).

## 2026-07-23: bundle both models again + seed them on first run
**decision:** reverse the 2026-07-22 "single 0.5b model" decision - bundle **both** the 0.5b base and the 1.5b analysis model, and seed them from the read-only bundle into the writable models dir on first run.
**rationale:** the user needs the gap-finder / summarize / claims features to work in the *installed* app, and those route to the 1.5b model (the 0.5b emits unparseable json on them). the earlier 0.5b-only build would have shipped a broken gap-finder. bundling both makes analysis work offline out of the box, at the cost of a larger installer (~3.7gb). without seeding, a frozen build finds no model at all: `config.py` loads from the writable `STATE_DIR/models`, but pyinstaller `--add-data` places the ggufs under the read-only `BUNDLE_DIR/data/models`.
**implementation:** `settings.bundled_models_dir` (`BUNDLE_DIR/data/models`) + `file_manager.seed_bundled_models()` copies missing ggufs into `models_dir` at startup (no-op in a source checkout where the two dirs coincide). CI re-adds the 1.5b download. the embedding model is not bundled yet, so first-run embeddings still need internet (documented in the deployment guide).
**status:** accepted.

## 2026-07-23: PyInstaller collect-all for llama_cpp + sentence_transformers
**decision:** freeze the backend with `--collect-all llama_cpp --collect-all sentence_transformers` (in addition to the uvicorn/psutil hidden imports).
**rationale:** validated by a local onedir freeze + run - neither package ships a PyInstaller hook, so without these flags the frozen build silently omits llama_cpp's `lib/*.so` (chat + gap analysis crash at model load) and sentence_transformers' package data (embeddings/search break). torch/transformers/sklearn are collected by their own bundled hooks. a local frozen backend built with these flags passed ingest + search + chat with zero import errors.
**status:** accepted.

## 2026-07-24: cpu-only torch + per-OS bundle formats to fix bloated, failing builds
**decision:** install torch from the cpu wheel index in ci and setup, and restrict the bundle formats per os (linux: deb + appimage, windows: msi, macos: app + dmg).
**rationale:** the first real release build failed on every platform and produced a ~3.7gb installer. two causes: (1) the default torch wheel on linux/windows pulls the full cuda stack (`nvidia/*` 2.7gb, `torch` 1.2gb, `triton` 0.7gb) that a cpu-only app never uses, and (2) the ~3.7gb payload broke the rpm bundler (hung past the 6h ci limit) and the windows nsis bundler (hit its ~2gb mmap limit). cpu-only torch (~200mb) removes ~4gb; choosing deb/appimage/msi/dmg avoids the two bundlers that cannot handle a large payload. this makes builds succeed, cuts the installer to roughly 1.5-2gb, and lets the app run on lower-spec machines.
**status:** accepted. further reductions possible: bundle only the 0.5b model, or replace torch-based embeddings with an onnx runtime.
