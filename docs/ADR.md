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
- **testing:** create a standalone, automated unit and integration test suite (`tools/test_paper_writer.py`) that tests all domain compiler operations and boots the FastAPI server to test API endpoints.
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
**implementation:** `.github/workflows/build-release.yml` "download base model" step now pulls a single file. see `scripts/set-repo.sh` and `release.config.json` for the places to update if this changes again.
**status:** accepted.

## 2026-07-22: `landing.html` (repo root) is the page of record
**decision:** `landing.html` at the repo root is the landing page intended for deployment, not `docs/landing/index.html`. fixed its download buttons (previously static `href="#"` placeholders promising windows/linux arm64 builds that ci does not produce) to wire real github releases urls matching what `build-release.yml` actually publishes, mirroring the working link-wiring script already present in `docs/landing/index.html`.
**rationale:** the two landing pages had drifted - different content, and only one had functioning download links. `docs/landing/index.html` is left in place for now but is not the deployment target; consolidate or remove it once `landing.html` is live and confirmed as the sole page.
**status:** accepted. hosting/deployment of `landing.html` itself is deferred until the desktop app has been tested end-to-end (see `scripts/README.md`).

## 2026-07-22: heavier model for structured-json analysis tasks
**decision:** route the structured-json analysis tasks (summarize, claims, themes, gap analysis) to a heavier model (`qwen2.5-1.5b-instruct-q4_k_m.gguf`, `settings.llm_analysis_model`) while chat/search/paper-writer keep using the lightweight 0.5b base model.
**rationale:** end-to-end testing showed the 0.5b model reliably works for free-text tasks (chat, latex generation) but produces truncated/unparseable json on the structured-extraction tasks, failing summarize/claims/gaps. the 1.5b model produces valid json. paired with demo's `max_tokens` caps (640/768/800) the analysis tasks became both reliable and faster (~20s single summary on cpu).
**implementation:** `TASK_MODEL_MAP` in `infrastructure/ollama_client.py` maps `analysis`/`gap_analysis` the 1.5b file; `_get_llama` keeps a **single model resident at a time and swaps on demand** (unload current, load requested) so peak memory stays at one model - important on low-ram machines. if the 1.5b file is absent, tasks fall back to the base model. see `scripts/README.md`.
**status:** accepted.

## 2026-07-22: reconcile `ollama_client.py` after demo merge - GPU-when-available, safe CPU fallback
**decision:** when rebasing onto `demo`, its `infrastructure/ollama_client.py` was **syntactically broken** (a botched merge - two `_get_llama` defs, an unclosed `Llama(` call; would not import; `main`/`demo` both affected). rather than take it verbatim, `ollama_client.py` was reconciled into one clean working file that keeps the analysis-model routing + single-resident swap, and loads on gpu **when available** but falls back to cpu instead of crashing when a cuda build/gpu is absent. demo's `routes_gaps.py` also had a duplicate `max_tokens=` kwarg (syntax error) which was fixed.
**rationale:** demo's file enforced gpu-only and refused cpu fallback ("fail loudly"), which contradicts the cpu-safe / low-end-machine direction and would refuse to run on machines without a usable cuda setup. gpu-when-available with safe cpu fallback runs everywhere and is still fast where a gpu exists.
**status:** accepted. (demo's good infra changes were kept: frozen-build `BUNDLE_DIR`/`STATE_DIR` paths, `.env` support, bundled embedding model, `max_tokens` caps, onedir `resources` packaging.)

## 2026-07-22: in-app auto-updates via tauri updater + github releases
**decision:** ship updates through tauri's built-in updater. on launch the installed app checks a signed `latest.json` on github releases and, if a newer version exists, downloads + verifies + installs it and relaunches.
**rationale:** asking users to re-download and reinstall the app for every fix is poor ux, so updates should arrive in-app. this appears to conflict with the offline stance, but it does not: the app never requires a network, and the update check is a single non-blocking http get for a version manifest. it sends no user data (no papers, no queries, just a version number), and when the machine is offline the check fails silently and the app runs normally. an always-offline install simply never auto-updates. github releases (already the CI publish target) hosts both the installers and the manifest for free, and integrates with the updater's signature verification.
**implementation:** `tauri-plugin-updater`/`-process` in `Cargo.toml`+`lib.rs`; `plugins.updater` (endpoint + pubkey) and `bundle.createUpdaterArtifacts` in `tauri.conf.json`; `updater:default`/`process:default` capabilities; `frontend/src/utils/updater.js` called from `App.jsx` (no-op in the web build); CI signs with `TAURI_SIGNING_*` secrets and publishes `latest.json` via `scripts/compose-updater-manifest.sh`; `scripts/release.sh` bumps+tags. private signing key stays at `~/.tauri` (gitignored `*.key`), public key committed. full flow in `scripts/README.md`.
**status:** accepted. needs a real signed build to verify end-to-end; this was verified by the v0.1.1 release, which published signed installers for all three platforms.

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

## 2026-07-25: release pipeline is config-driven, tag-triggered, and gated locally
**decision:** replace the monolithic build workflow with `release.config.json` (repo, platform matrix, channels, models) plus reusable `_build-desktop.yml` / `_publish-release.yml` and thin per-channel callers. branches never build installers; **tags do**. `scripts/preflight.sh` and the shared `.githooks/` reproduce the CI gate locally.
**rationale:** three long-lived branches (`dev` experiments, `beta` bundles and tests installers, `main` releases) each need different feedback. building on every push would burn ~20 minutes of runner time per commit for a binary nobody asked for, so the expensive path is opt-in via a tag or a manual `dev-build.yml` run. adding a platform or channel is a config edit rather than workflow surgery, which is what makes an enterprise or mobile target cheap later. the local gate exists because "green locally, red in CI" was a recurring waste - notably a shellcheck finding that only surfaced in CI because shellcheck was not installed locally.
**status:** accepted.

## 2026-07-25: smoke-test the frozen bundle before it can be published
**decision:** after PyInstaller freezes the backend, boot the frozen binary in CI and require a real 200 from `/api/system/health` before the build may continue. runs on all three platforms.
**rationale:** every other check reads the source tree. pytest cannot see a missing PyInstaller hidden import, a dropped shared library, or syntax the frozen interpreter rejects - all fatal at runtime and invisible until a user launches the app. a shipped build had already failed exactly that way (a stray `t"""` that only Python 3.12 rejects, while the dev machine ran 3.14). this is the only check that exercises the artifact users actually receive.
**status:** accepted.

## 2026-07-25: release guardrails that block unrecoverable mistakes
**decision:** `release.sh` refuses to tag when the version is older than what is published, or when CI is not green for that exact commit. the publish job fails when any asset reaches GitHub's 2 GiB limit.
**rationale:** a tag builds and publishes installers that installed apps auto-update to; none of it is reversible. releasing backwards would drag users to an older build, tagging a red commit ships known-broken installers, and an oversized asset kills the upload partway through after a ~45 minute build, leaving a half-populated release. version comparison uses `sort -V` so 0.10.0 correctly counts as newer than 0.1.0.
**status:** accepted.

## 2026-07-25: bundle only the baseline model; reuse what the user already has
**decision:** ship only the 0.5B baseline inside the installer. heavier models are optional, fetched only with explicit consent, and never fetched at all when an equivalent already exists on the machine.
**rationale:** bundling both models put installers at 1781-1940 MiB against a hard 2 GiB asset limit - roughly 5% headroom, so any dependency growth would have broken releases outright. dropping the 1.5B removes ~1066 MiB and lands every installer near 40% of the limit. the app stays genuinely offline-first because the baseline still ships, and analysis degrades to it rather than failing when the larger model is absent (verified end-to-end on Linux: a summarize call with only the baseline present produced a coherent summary). matching is on a canonical `family/size` key, since Ollama (`qwen2.5:1.5b`), LM Studio (`Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`) and our own naming all describe the same weights - comparing filenames offered a 1.1 GB download for weights already on disk.
**status:** accepted.

## 2026-07-25: hardware diagnosis stays conservative about GPUs
**decision:** the native Rust diagnosis (`src-tauri/src/diagnosis.rs`) reports RAM, CPU threads and NVIDIA VRAM, and enables GPU offload **only** for CUDA with >= 2 GB VRAM. AMD and Apple Metal are reported but treated as CPU-only.
**rationale:** the shipped `llama-cpp-python` is the CPU wheel. attempting offload on AMD or Metal would fail at model load, so reporting no usable GPU makes the app do the only thing it can. diagnosis is deliberately hardware-only and does not check for models - that belongs to the backend, which seeds the bundled model and resolves paths lazily. doing it in Rust removed a multi-second `import torch` from the startup path; the equivalent argument does not hold for model discovery, which is ~9 ms and dominated by I/O, so that stayed in Python next to its only consumer.
**status:** accepted.

## 2026-07-25: release guide folded into this log
**decision:** delete `docs/RELEASE_GUIDE.md`. the decisions it recorded live here; the runbook (branch model, `promote.sh`, `preflight.sh`, guardrails, hooks) lives in `scripts/README.md`, next to the scripts it describes.
**rationale:** the guide had grown to 450 lines mixing two genres - why the pipeline is shaped this way, and how to operate it - and duplicated `scripts/README.md`. splitting them by genre keeps each one short enough to stay accurate.
**status:** accepted.

## 2026-07-29: branch protection guards production, releases guard themselves
**decision:** `main` requires a green `CI OK` and a pull request (0 approvals, must be up to date); `beta` requires `CI OK` but allows direct pushes; `dev` is unprotected. force-push and deletion are blocked on both long-lived branches. tags are deliberately **not** protected - the release scripts, not github, enforce that a tag is safe to cut.
**rationale:** with three contributors, mandatory review would be ceremony that slows a team that already talks constantly; a required status check catches the thing review misses anyway. what actually needs guarding is not the merge but the tag, because a tag builds and publishes installers that auto-update every install and cannot be un-shipped. `release.sh` checks the version is not going backwards and that CI is green for the exact commit - checks github's branch rules cannot express, since a tag can point at any commit. the cost is that the guards only apply if you use the scripts, and any of the three of us can publish a stable release; that is a documented convention (maintainer cuts stable, anyone cuts beta) rather than an enforced rule. revisit with a `v*` tag ruleset if the team grows or a release ever goes out by accident.
**status:** accepted.

## 2026-07-30: two channel pages on one GitHub Pages site
**decision:** publish the public page at `/` from `main` and a beta page at `/beta/` from the `beta` branch, both from `deploy-pages.yml`. the beta page is generated from the same `landing.html` by rewriting `/releases/latest/download/` to `/releases/download/<newest-prerelease-tag>/` at deploy time, and carries a banner naming the tag. `dev` gets no page.
**rationale:** a repository gets exactly one Pages site, so a second site for beta is not available; a subpath is. generating the beta page rather than duplicating the file means a landing-page change cannot land on one channel and not the other. the tag must be substituted by something because github resolves `/releases/latest/` to the newest *stable* release by design and publishes no equivalent prerelease URL - doing that substitution in CI keeps `/beta/` a static file, with no client-side API call to rate-limit or fail in a tester's browser. the stable checkout is pinned to the default branch: a bare checkout takes the triggering ref, so a push to `beta` would have published beta's page publicly and handed pre-release downloads to everyone. the workflow fails the deploy if any stable download URL survives the rewrite, because the failure mode otherwise is a tester downloading the wrong build and reporting bugs against code we are not shipping.
**status:** accepted.

## 2026-07-30: updates are user-initiated; nothing is checked on launch
**decision:** remove the update check that ran on every app start. the updater is reached only through an explicit "Update app" button in the sidebar, which reports every outcome (up to date / newer version found / desktop only / failed) rather than staying silent. the running version is shown beside it, read at build time from `src-tauri/tauri.conf.json`.
**rationale:** the product's entire claim is that nothing leaves the device. an unprompted request to github on every launch contradicts that even though it carries no user data - a user watching their firewall would see an "offline" research tool calling home, and would be right to distrust the rest of the claim. the cost is that a user who never presses the button never updates; that is the correct trade for this product, and the button reporting "Up to date" makes the state visible rather than implicit. a silent variant of the checker was deleted rather than left unused, because leaving it in invites re-adding the launch-time call.
**status:** accepted.

## 2026-08-01: litgraph replaces search, analysis and gap finder
**decision:** collapse the search, analysis and gap-finder pages into a single spatial canvas, and rename the remaining sections. the app is now three: bibliotekh (collect), litgraph (understand), scribe (write).
**rationale:** the three pages were three views onto one question -- what is in this collection, and what is missing from it -- and splitting them across three routes pushed the joins into the user's head: which paper a claim came from, which papers a gap was about, whether a "theme" and a "cluster" were the same thing. on a canvas those joins are drawn instead of remembered: position is meaning, edges are similarity, hulls are themes, amber nodes are gaps with dashed edges to their evidence. the decisive part is that the map becomes the *selector* -- lasso a region or run a search and that set is what every analysis action operates on, so choosing papers and seeing why you chose them are one gesture rather than a checkbox list on another page. cost: it is a large surface with more state than three simple pages, and the old routes had to keep redirecting because a desktop shell makes a stale deep link a dead end.
**status:** accepted.

## 2026-08-01: search is purely semantic; bm25 and rrf removed
**decision:** delete `hybrid_search.py` and `keyword_search.py`, drop the `rank-bm25` dependency, and rank search results by cosine similarity alone -- plus a small exact-token bonus. sweep every chunk in the corpus rather than a `top_k` candidate pool, and add a per-paper rollup.
**rationale:** the fused ranking undercut the thing semantic search exists for. a paraphrase query that shares no vocabulary with the passage answering it was routinely out-ranked by lexically similar noise, because rrf merges by rank position and bm25 always has an opinion. worse, each leg only ever saw `top_k` chunks, so there was no full-corpus sweep at all and a passage deep in a long paper could not be reached. the one thing bm25 was genuinely better at -- rare literal tokens like `FedAvg` or an author surname -- is preserved by adding `0.05 x (fraction of query tokens present verbatim)` *after* the cosine score: it can break a near-tie upward but cannot lift a lexical match over a genuinely better semantic one. the rollup groups surviving chunks by paper, keeping every match rather than the best one, because the canvas asks "which papers does this touch, and where in each" rather than "which passage wins".
**tradeoff:** every query now scores every chunk. that is what makes the search exhaustive, and it is cheap at a few thousand chunks; an ann index is the upgrade if collections grow much larger.
**status:** accepted.

## 2026-07-30: the model prompt records what was answered, not that it was answered
**decision:** `ModelSetup` stores `{outcome, model, at}` instead of `dismissed=true`, treats declining and installing as different answers, only stays quiet about the *specific* model already answered for, and can be reopened from a sidebar button. the legacy boolean is dropped on read rather than honoured.
**rationale:** the boolean silenced the dialog permanently, for every future model, with no way back from inside the app - and it lives in the webview's localStorage under the app identifier, so reinstalling did not clear it. a tester who clicked "Not now" once would never be offered anything again and would reasonably report that the app never asked; that is exactly what happened during v1.0.0 validation. recording the model name means a later, different suggestion is still asked about, and the sidebar entry makes the decision reversible. the legacy flag is dropped because it carries no record of *what* was declined, so honouring it would mean silencing every future model on the strength of one click that was probably the bug.
**status:** accepted.

## 2026-08-05: models are a registry the user owns, not a hardcoded table

**Context.** The catalog was a frozen tuple of two specs and routing was a
dict of hardcoded filenames read at import. A researcher who already had
suitable weights — via Ollama, LM Studio, or a previous download — had no way
to tell ThinkStack to use them, and no way to see why a job had chosen one
model over another.

**Decision.** A writable registry (`domain/model_manager/registry.py`) records
every model available to the install and which jobs each may do, persisted
through `atomic_io`. A router (`router.py`) answers which model serves a task,
with every dependency passed in rather than imported.

**Consequences.**
- Routing is testable against fabricated hardware with no llama.cpp present.
  It was previously reachable only by constructing a real client.
- Two invariants carry the safety: `managed` (did ThinkStack create this file?)
  gates deletion, and `user_assigned` (did a human choose these tasks?) stops
  an update silently undoing someone's routing.
- An empty registry reproduces the previous routing exactly, which is what made
  the extraction safe to land mid-beta.

## 2026-08-05: imported models are referenced, never copied

**Context.** Model weights run to several gigabytes, and ThinkStack targets
machines already chosen for being memory-constrained.

**Decision.** Importing records an absolute path. The file is never copied into
ThinkStack's own directory.

**Consequences.** A 7 GB import costs no additional disk. The cost accepted is
that the app depends on a path it does not own: the file can move or vanish,
so entries are validated on read and shown as `missing` rather than failing at
generation time. Nothing outside ThinkStack's own directory is ever deleted.

## 2026-08-05: suggestions consider compute, not only memory

**Context.** A machine with 20 GB free and no usable GPU was told to download a
3B model. It would have loaded and then taken minutes per summary.

**Decision.** `runs_well_on(gpu_gb)` gates suggestions on whether the model can
be offloaded to a GPU the *engine* can use. Without that, size is capped at
`CPU_COMFORTABLE_GB` (1.2 GB) regardless of available memory.

**Consequences.** The same catalog produces different advice on different
machines. Large models are still listed and still downloadable, marked "will be
slow without acceleration" — shown rather than hidden, because a user with a
reason to want one should be able to have it, and should not discover the cost
after the download.

## 2026-08-05: never bundle a reasoning model

**Context.** Qwen3 0.6B was selected as a lighter, newer baseline. Every
structural check passed — verified URL, correct size, valid GGUF, parseable
output — and it returned `{}` for gap finding.

**Decision.** Reasoning families (Qwen3, DeepSeek-R1, QwQ, Marco-o1) are
rejected as the bundled model, enforced by tests over both `catalog.py` and
`release.config.json`.

**Consequences.** `generate_json` constrains output with a GBNF grammar that
permits only JSON from the first token, leaving a reasoning model's `<think>`
block nowhere to go. It emits the shortest legal document instead: `{}`.
`json.loads` succeeds, so nothing downstream notices. The baseline is now
chosen by measured behaviour on the two flagship jobs, not by size or recency.

## 2026-08-07: graphics acceleration is offered, not shipped

**Context.** ThinkStack ships a processor-only build of llama.cpp. A tester with
an RTX 4050 was told, correctly, that "the installed inference engine is a
CPU-only build and cannot use it" -- and offered nothing. The detection was
right; the dead end was the defect.

**Decision.** The engine is downloaded on request, verified, and switched on by
pointing `LLAMA_CPP_LIB_PATH` at the user's writable data directory.

**Consequences.** The installer does not grow by a byte. Nothing inside the
installation is written to, which matters because on Linux that is a read-only
AppImage mount and on macOS a signed bundle. `llama_cpp` is imported only inside
functions, so `main.py` can set the variable at startup -- no Rust change, no
restart choreography. Everything downstream already keys off
`llama_supports_gpu_offload()`, so flipping that one fact makes the advice, the
model suggestions and the routing GPU-aware with no further change.

## 2026-08-07: Vulkan, not CUDA

**Context.** CUDA had prebuilt wheels, so it looked cheapest. It reaches NVIDIA
cards only, through NVIDIA's proprietary stack, and needs ~557 MB of maths
libraries on any machine without the CUDA toolkit -- ~1 GB in total.

**Decision.** Build llama.cpp with its Vulkan backend and publish that instead.

**Consequences.** ~90 MB rather than ~1 GB, and it reaches NVIDIA, AMD, Intel
and integrated graphics through the loader that ships WITH the graphics driver.
The evidence that settled it: the development laptop has no NVIDIA packages
installed at all, and Vulkan already reports both its Intel iGPU and its RTX
3050 Ti through Mesa's open-source NVK driver. CUDA would have reached neither.
The cost is real -- Vulkan is slower than CUDA on an NVIDIA card -- but the
comparison that matters is against the processor, not against the fastest
possible backend. Nobody publishes a Vulkan build of llama-cpp-python, so
`.github/workflows/build-accel.yml` exists to make one.

## 2026-08-07: a software rasteriser is not a graphics device

**Context.** Vulkan reports `llvmpipe` as a device on most Linux machines. It is
the processor pretending to be a graphics card.

**Decision.** Usability is decided by device TYPE. Software and virtual devices
are excluded, discrete is preferred over integrated, and reported memory decides
nothing.

**Consequences.** Offloading to llvmpipe would route work through a translation
layer to reach the CPU already doing it, while reporting success -- a thing that
passes every check and does the wrong thing. Memory is excluded from the
decision because it lies: on the development laptop an Intel iGPU and an RTX
3050 Ti both report 12.4 GB, which is system RAM, and llvmpipe reports the most
of all. Ranking by memory would therefore have selected precisely the device
that must never be selected.

## 2026-08-07: nothing unverified is switched on

**Context.** Libraries can download perfectly and still fail to load -- a driver
too old, a missing dependency, a CPU without the instructions the build assumes.
Discovering that inside the running backend means the backend is already
damaged, on a machine where this app is the only thing that can read the user's
papers.

**Decision.** A separate process loads the libraries and reports back. The
override is committed only if that process survives, and `active_lib_dir()`
requires a `verified` flag that only a surviving probe writes.

**Consequences.** A failed activation costs a download and changes nothing else.
The checksum is verified before extraction, because a truncated download fails
to load in a way indistinguishable from an incompatible driver -- and the user
would then be told something untrue about their own machine.

## 2026-08-07: a paper is a directory, and the file tree is the way into it

**Context.** A project has been a directory since the first version --
`main.tex` and `meta.json` in `data/papers_workspace/<id>/` -- but `main.tex`
was the only file anything could reach. A user's paper failed with "Unable to
load picture or PDF file 'newplot-6.png'", then "Division by 0".

**Decision.** `domain/paper_writer/files.py` exposes the directory: list, read,
write, upload, mkdir, move, copy, delete. The UI is one tree with papers as its
top level, replacing the row of project chips.

**Consequences.** `\includegraphics{chart.png}` works, and always would have:
the compiler already ran with the project directory as its working directory, so
the relative path resolved and the file simply was not there. The second error
was the first one's consequence -- graphics dividing by a width read from a file
it never opened. Papers can now be split across section files and keep a `.bib`
beside them. Build artefacts are hidden from the tree; they are regenerated and
mean nothing to an author.

## 2026-08-12: a title is the biggest text on page 1, not the first line

**Context.** `_extract_title` kept any of the first ten lines longer than ten
characters, and `_extract_authors` matched two capitalised words. Both read
`extract_text()`, which flattens a PDF into a string.

**Decision.** `pdf_parser.extract_layout()` returns spans carrying size,
position and baseline. The title is the largest horizontal text in the top of
page 1; the authors are the rows beneath it.

**Consequences.** A PDF has no title field -- 18 papers checked, every one
carries only a creation date in its Info dictionary. What it has is glyphs
with sizes, and the typesetter already encoded the answer in them. Flattening
to a string throws away the only signal there was, which is why the old
version returned Google's copyright notice as the title of *Attention Is All
You Need* and 2014 as its year. No language change fixes that: the same regex
returns `Google Brain` just as confidently in Rust. Measured cost of the whole
pipeline is 6 ms extract, 1 ms metadata, against 3073 ms to embed.

## 2026-08-12: geometry is a separate module from bibliography

**Context.** The rules were accumulating inside two functions that both knew
about fonts and about what a title is.

**Decision.** `layout.py` turns spans into rows of cells and knows nothing
about papers. `layout_metadata.py` decides what a title or an author is.

**Consequences.** Three of the four worst bugs were geometry, not
bibliography: rows grouped by bounding-box top instead of baseline split a
small-caps title into `A : A M S O`; a font change mid-word inserted a space
into `ADAM`; a loose accent glyph left `Doll ´ar` unsearchable. None of those
are about papers, and none of them are visible while reading a function that
is also deciding whether something is an author.

## 2026-08-12: affiliations are removed by structure, never by naming employers

**Context.** The obvious filter is a list of institutions. Google, Tsinghua,
Mistral, NAVER -- a list that is always incomplete and always dating.

**Decision.** Three rules, none naming a company. A *structural* word
(university, institute, research) condemns a whole row. A short all-caps token
beside ordinary words is an acronym, and disqualifies the candidate as a name.
A phrase printed twice in the author band is an address, because a name
appears once per paper.

**Consequences.** The row-level test is what lets the word list stay small:
attention.pdf's affiliation row is `Google Brain | Google Brain | Google
Research | Google Research`, and only two of those four cells carry a listed
word -- "Brain" is not in the list and never will be. The repetition rule
needs no vocabulary at all, and is the only one that separates "United
Kingdom" from "Kaiming He", which are identical to any test of spelling.
Ablated: without the word list, 4 of 7 papers instead of 7 of 7, and it only
ever admits extra rows -- it never loses a name.

The acronym rule applies only to mixed-case text. A wholly capitalised
candidate is a typesetting choice, not an abbreviation: acmart sets every
byline that way, and `ANDREW CHU` was being read as an acronym.

Tried and reverted, with the numbers kept in a comment so it is not re-added
on the strength of the one case it helps: treating a bare acronym (`IEEE`) as
an institution. It fixes `Wang, Senior Member, IEEE` and costs more elsewhere,
85.7% down to 83.9% exact author lists.

## 2026-08-12: a plausibility check, because the failure mode is not silence

**Context.** An SLM fallback existed and was guarded on `not metadata.title`.
It never once ran.

**Decision.** `metadata_is_plausible()` replaces the emptiness test: a usable
result needs a title that is not boilerplate *and* at least one author.

**Consequences.** The regex never returned empty. It returned wrong, and
confidently. A guard that tests for silence cannot catch that, so the better
path was unreachable on exactly the papers it existed to rescue. This is the
third bug of the same shape found in a month -- the graphics advice gated on
`vram_gb`, the updater reading a missing `window.confirm` as "user declined",
and this. When the model does run it is handed font sizes rather than the flat
text, because a model given the same evidence makes the same mistake.

## 2026-08-13: the interface reads the backend's answer, never recomputes it

**Context.** Library's "Bench in use" panel did
`models.find((m) => m.status === 'ready') || models[0]`.

**Decision.** Read `routing` from the registry payload, one row per task. The
UI does not decide which model serves a request.

**Consequences.** `'ready'` is not a status this backend emits -- it says
`'present'` -- so the find never matched and every render silently fell through
to `models[0]`. Worse, the question has no single answer: routing is per task,
and which entry serves one depends on every other entry (assignment, size
against the memory free right now, rank). `routes_registry.py:186` had already
written this down: *"computed here, not in the UI: it depends on every other
entry, and duplicating that rule in javascript would let the two drift."* On
this machine the 1.5B that serves Analysis was not in `models` at all. Anything
the backend computes from global state is read, not re-derived.

## 2026-08-13: a dash is not a number, and three states are not one

**Context.** Two of Library's four stat cards were hardcoded `-`. The other
panels rendered `-` for "loading", for "nothing yet", and for "the request
failed" alike.

**Decision.** Counts come from the call Library already makes. Absent, empty
and failed are rendered as three different things.

**Consequences.** "Analyses Run" and "Gaps Found" had never displayed a number
in any release, which reads as broken software on the first screen a user sees.
`gaps` is the newest run rather than a running total: a scan covers the whole
library and supersedes the one before it, so summing every run counts the same
gap once per rescan and only ever climbs. This is the same shape as the
metadata guard from the day before -- a single value standing in for several
distinct facts, so the interesting one cannot be seen.

## 2026-08-13: a pane takes the height it is given

**Context.** Scribe and LitGraph sized themselves with `calc(100vh - 11rem)`
and `calc(100vh - 3rem)`, commented "the header is ~2.1rem of title plus its
margin".

**Decision.** The workspace is the viewport and its own scroll container.
Panes declare `flex: 1`, and the height is handed down `<main>` ->
`.page-frame` -> the page.

**Consequences.** A constant standing in for a measurement is wrong the moment
anything above it changes, and it fails silently -- removing the page titles
left a strip of dead space at the bottom of Scribe with nothing to indicate
why. It also has to be re-guessed per page, which is why there were two
different constants for the same idea.

The route transition wrapper had to be given a class. It sits between `<main>`
and the page, and `flex: 1` resolves against the nearest flex parent: with an
unclassed block in the chain both pages collapsed to the height of their own
content. The height has to be passed at every step, and a missing link is
invisible until it is rendered.

**Library declares `fills` as well**, reversing the 2.1.9 decision that it
should keep a measure. That rule is about PROSE -- a line set 1900px wide is
unreadable. Bench is read and keeps its measure; Library is counts, panels and
a list, and capping it left a third of a wide window empty.

## 2026-08-14: Paper and Ink replaces the interface

**Context.** The dark glass interface had accumulated twelve ad-hoc type sizes,
a sidebar that collapsed to nothing, and panes measured with `calc(100vh -
11rem)`. Rithesh proposed replacing it outright rather than continuing to
correct it; Aditya implemented the replacement as a parallel `new-frontend/`
tree while the old one went on shipping.

**Decision.** *Paper and Ink* -- a sheet of paper on a desk, worked in ink --
is the interface. `new-frontend/` is `frontend/`, and the old tree is deleted.

**Consequences.** A parallel tree is the right shape for this and has one
failure mode: the two drift, and the one nobody is looking at rots. Two things
were done about it. CI ran both through the same matrix, so neither could ship
having been checked differently. And the contract test was parameterised over
both trees, because it had hardcoded `frontend/src/utils/api.js` -- the moment
the replacement shipped it would have gone on proving things about a directory
nobody builds, passing while the live client called routes that did not exist.

Parity before the swap was established three ways: both clients called the same
44 routes, the contract test passed over both, and `local/check_api_reach.py`
called every route against a running backend. The third is not the same
guarantee as the first two -- reading both sides as text proves the paths
MATCH; only calling them proves the handlers RUN.

The replacement had already solved problems the old tree had not. Its folio --
one line of type on the masthead -- says what four glass cards said and costs
no vertical space, which is why the port kept it rather than reinstating cards.

## 2026-08-14: two trees means every fix is made twice

**Context.** The extractor work, the Library rebuild, the type scale and the
rail all landed in `frontend/` while `new-frontend/` was being written.

**Decision.** Port the DECISIONS into the new tree's idiom rather than copying
its markup across.

**Consequences.** Everything was built twice, and that is the real price of
replacing a running interface -- not the rewrite, the double maintenance while
both exist. Copying would have been faster and wrong: the new tree names its
colours `--text`, `--text-2`, `--text-primary`, so the type scale is `--type-*`
there and `--text-*` in the old one. A colour token answering to a size name is
a trap somebody falls into later.

The same applies to structure. The route wrapper is `.page-turn` here and was
`.page-frame` there, and Scribe's root had no class at all -- so the height
chain that fixes the panes had to be rebuilt, not pasted. It is one link per
step and a missing one resolves `flex: 1` against nothing.

## 2026-08-14: six named type steps, and a root size that is not fixed

**Context.** The stylesheets carried twelve different small font sizes: 0.68,
0.7, 0.72, 0.75, 0.76, 0.78, 0.8, 0.82, 0.84, 0.85, 0.9 and 0.95rem. The root
was a flat `16px`.

**Decision.** Six steps as variables -- `--text-xs` through `--text-2xl` -- and
a fluid root, `clamp(16px, 0.15vw + 14.6px, 18px)`. 161 declarations across
both stylesheets now resolve to them.

**Consequences.** Two-hundredths of a rem is not a decision anyone made; it is
what happens when each component picks a number on its own, and the result
reads as sloppy without any single value looking wrong. Six steps are far
enough apart to be deliberate, and the lower bound means nothing lands below
about 13px.

Fluid because this is a desktop application read at arm's length on whatever
display it lands on: 16px is cramped on a 13" laptop and small on a 27"
monitor. The range is narrow on purpose -- a first attempt at
`clamp(17px .. 20px)` resolved near 20 on a wide monitor, which read as zoomed
rather than as legible, and was rejected on sight.

## 2026-08-14: a figure earns its place by answering a question

**Context.** Library opened with six stat cards and a "chunks per paper" chart.
The module's author said it was too much at once.

**Decision.** The counts caption the Knowledge Base section instead of opening
the page. Bytes on disk and the chunk count are removed rather than moved. The
paper list pages five at a time.

**Consequences.** The cards were the first thing read and the least worth
reading, and they pushed the papers themselves below the fold. "175 KB" is the
clearest case: it is accurate, it is cheap to compute, and no reader has ever
wanted it -- nobody is short of 175 KB, and the number does not change what
they do next. The chunk count is the same in a subtler way: it describes how
the text is indexed, which is our concern rather than theirs.

What replaced them says something: **analysed reads "15 of 20"**, so the
distance between ingested and read is visible rather than implied.

Paging follows from the same idea. Library exists to be taken in at a glance,
and a list long enough to scroll buries everything above it, so the page is
worth more than the rows.

## 2026-08-14: the collapsed sidebar is a rail

**Context.** Collapsing set `--sidebar-w: 0px`. The sidebar left the screen, so
the logo was re-rendered as a floating button over the page and the "i" sat
over the content beside it.

**Decision.** Collapse to a 64px rail carrying the logo and the nav marks. The
floating logo is deleted.

**Consequences.** Zero width forces anything still needed to be drawn on top of
the page, which is the problem collapsing was meant to solve. Because
`.main-content`'s margin is the same variable, the content steps aside for the
rail rather than sliding under it -- no second measurement, and no way for the
two to disagree.

The guide needed `z-index: 110` to sit on the rail. The sidebar is 100 and the
guide 40, so on the rail it rendered *behind* it and simply vanished -- which
is worth recording because nothing about the change suggests a stacking
problem, and the symptom is an element that is present, correct, and invisible.

## 2026-08-14: the .bib file is the authority for a citation key

**Context.** A key is derived from metadata, so two papers can collide and the
tiebreak depends on what else is in the library. Derive it again after another
paper is ingested and the same document can get a different key.

**Decision.** `assign_keys` reads `references.bib` first and honours every key
already written there; only documents the file has never seen get a new one.
The document id travels in a `thinkstackid` field.

**Consequences.** A `\cite{}` already typed into the source cannot break -- the
alternative is a bibliography that silently stops resolving because an
unrelated paper was added to the library. The id field is unknown to every
`.bst`, which read only the fields they declare, so it never appears in the
rendered bibliography. It also means the file can be edited by hand -- rename a
key, fix an author list, paste an entry from elsewhere -- and the mapping back
to the library survives, which is what makes hand-editing the per-project
override rather than a thing that gets overwritten.

## 2026-08-14: the comma is BibTeX syntax, so an author list is JSON

**Context.** Chroma metadata holds str, int, float and bool. A list of authors
has to be flattened to store it, and `", ".join(authors)` is the obvious way.

**Decision.** JSON-encode the list. `decode` still accepts the comma form.

**Consequences.** In BibTeX the comma separates surname from given name --
`Vaswani, Ashish and Shazeer, Noam` is two people -- so re-splitting a joined
list on commas turned eight authors into sixteen half-names. Nothing raised;
a bibliography just printed them. The legacy path stays because a library is
not re-ingested to fix a codec, and it is honest about its limit: rows written
surname-first are wrong and are not repairable from the string, which is one
of the reasons the Library gained an editor for them.

## 2026-08-14: a citing document is given a bibliography, but only one to point at

**Context.** `\cite{key}` alone renders `[?]` and prints no reference list.
BibTeX is invoked by the `\bibdata` line that `\bibliography` writes into the
`.aux`, and that same command is where the list is typeset.

**Decision.** The compile-time heal adds `\bibliographystyle` and
`\bibliography{references}` before `\end{document}` -- when the document
actually cites something *and* the project has a `references.bib`.

**Consequences.** A document with citations and no bibliography is not a style
choice, it is the citation silently not working, and it looked exactly like the
feature being broken. Both conditions are load-bearing: pointing
`\bibliography` at a file that is not there turns a working compile into a
failed one, and an author who typed `\cite` by hand has no such file. The
engine matters too -- Tectonic runs BibTeX in its own driver and pdflatex does
not, so a build from source needed the pass added explicitly.

## 2026-08-14: a caret-anchored popup is positioned in viewport coordinates

**Context.** The cite list is anchored under the caret in a `<textarea>`, which
exposes a character offset and no coordinates. A mirror div wearing the
textarea's computed styles gives the pixel position.

**Decision.** `position: fixed`, coordinates from
`getBoundingClientRect()` plus the caret offset, the caret's y clamped into the
textarea's visible box, and the list flipped above the line when the window has
no room below. `--z-over`, the same layer as the context menu.

**Consequences.** Absolute-inside-the-pane was the intuitive choice and was
wrong twice over: the editor pane sits inside `overflow: hidden`, so a list
anchored near the foot of a long document was clipped away rather than scrolled
to, and the compiled PDF beside it sits on `--z-sheet` and painted over the
column holding the keys. The feature rendered correctly, with every row in it,
1382px down a 1000px window. Layout bugs of this shape do not show up in jsdom,
which has no layout; this one was found by driving the real page and reading
the box back.

## 2026-08-14: a wrong reference is repaired in the library, not in the bibliography

**Context.** Titles extract right about 93% of the time and author lists 86%,
so roughly one paper in seven is stored wrong. It can be corrected in two
places: the library record, or the `references.bib` of a project citing it.

**Decision.** The Library edits the record -- title, authors and year. Scribe
gets no second editor; `references.bib` is already a file in the project tree.

**Consequences.** The library is where the wrong data actually is, so fixing it
there fixes every future citation, every node on the map and every search hit
at once, while fixing the `.bib` fixes one project and the next one re-derives
the same mistake. Two editors over one field would be two sources of truth. The
ordering follows from the entry above: a `.bib` already written keeps what it
has, so the reference is fixed before it is cited, or in that project's file.
The one rule a user cannot guess is stated in the form -- authors separate on
commas, or on semicolons when a name contains one.

## 2026-08-22: a new document is not always a research paper

**Context.** Scribe is a LaTeX editor that happens to live inside a research
application. Every project began from one skeleton -- abstract, methodology,
results, a bibliography -- because every project was assumed to be a paper.
Someone opening it to write a letter, a report or a CV had to delete most of
the document before they could start, and the deleting was the first thing the
tool asked them to do.

**Decision.** Six starter documents: research paper, article, letter, CV,
report and Beamer slides. The set is served from the backend at
`GET /api/papers/templates` rather than listed in the interface, and an
unrecognised id returns the paper instead of an error.

**Consequences.** The picker and the set cannot drift: a template added to
`domain/paper_writer/templates.py` appears in the interface with no second
edit, and one removed cannot be offered for a shape that no longer exists. The
fallback is the important half -- a new document is not the place to refuse. An
id can be stale (a template retired between releases) or simply wrong, and in
both cases the author still wants a document; handing them the paper is worse
than what they asked for and far better than an error where a document should
be. The consequence to watch is that a typo cannot be detected, which is
accepted because the id is chosen from a served list, never typed.

The default is served too, as `default`. Hardcoding "paper" in the interface
would be a second place that has to change when the set does.

## 2026-08-23: a linked file is put on the compile's search path, not copied

**Context.** A link records where a file is rather than taking a copy. Tectonic
runs with the project as its working directory, so that was bookkeeping and
nothing more: `\includegraphics{chart.png}` failed on a file the panel listed
as present. The only thing that worked was typing an absolute path, which works
whether or not the file was ever linked and breaks the moment it moves --
precisely what linking exists to survive.

**Decision.** Every resolved link contributes a directory to the compile's
search path: a linked file its parent, a linked folder itself. Tectonic is
given `-Z search-path`; the pdflatex fallback is given `TEXINPUTS`, and its
separate BibTeX pass `BIBINPUTS`.

**Consequences.** `-Z search-path`, not `TEXINPUTS`, is the mechanism for the
shipped engine, and the difference is not cosmetic: Tectonic has its own IO
layer and ignores the environment variable outright. Verified against the
bundled 0.15.0 -- the same document fails with `TEXINPUTS` set and compiles
with the flag. Setting the variable and believing it worked is exactly how this
could have looked fixed while still failing, so a test asserts Tectonic is
*not* given it.

One flag covers `\input`, `\includegraphics` and `\bibliography` alike,
because BibTeX runs inside Tectonic's own multi-pass build and inherits it.
That makes a shared `references.bib` work, which was the case the feature was
argued for in the first place.

A missing link is skipped rather than failing the compile. It is already
reported in the panel, and refusing to build because one of several linked
files moved is a worse answer than building and saying what was missing.

## 2026-08-23: what may be linked is not decided by what LaTeX can read

**Context.** A suffix allowlist refused anything a LaTeX project could not use.
It was also doing security work: linking is the one place the application
accepts an absolute path, and refusing extensionless files kept `~/.ssh/id_rsa`
and `/etc/passwd` out of reach.

**Decision.** Any file may be linked or uploaded. The set survives as
`LATEX_SUFFIXES`, a hint the chooser shows -- which files a document could
actually reference -- rather than a refusal.

**Consequences.** The rule was refusing datasets, READMEs and image formats
people legitimately keep beside a paper, and telling them their own files were
not allowed in their own folder. A type the engine cannot read is useless to a
document, not dangerous to one; nothing here executes a project file, and a
served one goes out as `Content-Disposition: attachment`.

The security argument is not dismissed, it is relocated. What keeps an
absolute-path endpoint acceptable is that only the person at the machine can
reach it -- the same-origin check and the loopback bind, both landed earlier
this month. That is where an access question belongs, rather than in a list of
file extensions that never described the threat accurately anyway.

What is given up is honest to state: this was a second layer, and there is now
one. If the origin check were ever weakened, the blast radius is larger than it
was. The endpoint reaches any file the user can reach.


## 2026-08-23: a control that chooses must not displace the control that acts

**Context.** The template picker was added to the Scribe tree header as a
`<select>`. That header is a fixed-width flex row in a 200px sidebar whose
buttons are 22px and do not shrink, so 120px of dropdown pushed the **+**
button past the visible edge. Templates became selectable and papers became
uncreatable.

**Decision.** The **+** opens the templates as a menu, using the same treatment
as `.ft-menu`, the context menu already in that component. Choosing a template
is the same click that creates the paper.

**Consequences.** The menu costs no header width, so it cannot crowd out
anything. It also has room to describe each template rather than name it, which
is the difference between "CV" and a choice someone can make without first
making it to find out — a dropdown could never have done that in this space.
Making the choice and the creation one click removes a selected-but-unapplied
state that could drift from the paper it eventually made.

The general rule is worth stating: when a control that *configures* an action
shares a row with the control that *performs* it, the performing one must win
the space. A user who cannot configure is inconvenienced; a user who cannot act
is stuck.

## 2026-08-23: a custom property that does not exist fails only on screen

**Context.** The first version of that menu was written with
`background: var(--surface-1)`. This project's token is `--surface`. An
undefined custom property makes the declaration invalid, so the background
resolved to nothing and the menu rendered transparent over the file list.

Everything passed. The CSS is syntactically valid, the build succeeds, and
jsdom computes no cascade and no layout, so no interface test can see a panel
you can see through. It was found by looking at it.

**Decision.** `frontend/tests/cssTokens.test.js` asserts that every
`var(--token)` read without a fallback is one some stylesheet defines. Comments
are stripped first, because a token named in a comment is not a token used, and
`var(--x, fallback)` is exempt because a fallback makes the absence deliberate.

**Consequences.** This is the second defect in one evening that a green suite
could not see -- the other was a `<select>` clipping a button out of view. The
two share a shape: a change that is correct as code and wrong as pixels. Not
all of that class is testable, but the part that is a *name* is, and a name is
exactly what gets mistyped when a design system has both `--surface` and
`--surface-2`. The check is a string comparison over two files.

The rest of that class remains uncovered, and the honest mitigation is the one
that caught both: run it and look at it before committing.


## 2026-08-22: an empty library is a state, not a blocker

**Context.** The Library is the first screen, and on a new install it is empty.
It said one thing: drop a PDF here. For someone who installed ThinkStack to
write, that is a door with nothing behind it -- and the reasonable conclusion
from an app whose only instruction cannot be followed is that it is broken, or
that it is not for them.

**Decision.** Nothing in Scribe may require an ingested paper, and the empty
Library says so, offering writing beside reading. Tests hold the property
rather than the wording: the citation routes return empty rather than failing,
no starter document arrives citing a key nothing defines, and a project can be
created, edited, listed and compiled with no library at all.

**Consequences.** Scribe carries its own TeX engine and compiles offline, so
this is a claim the product can actually make -- writing genuinely does not
depend on reading. The tests matter more than the sentence in the empty state,
because the sentence is what a reader sees and the property is what makes it
true; a later change that made some panel throw on an empty library would leave
the invitation in place and break what it promises.

The link is asserted as a link, not as prose. A sentence mentioning Scribe with
no way to reach it is the same dead end in nicer words.

## 2026-08-22: a lazily-imported module is asserted over HTTP, not assumed

**Context.** `templates.py` is imported inside the two functions that use it,
never at module scope. PyInstaller's static analysis does follow function-level
imports -- verified against the shipped AppImage, whose `/api/models/registry`
handler imports `domain.model_manager.discovery` the same way and answers
correctly -- but that is a claim about a tool, checked once, on one platform.

**Decision.** `scripts/validate_bundle.py` asks the frozen backend for the
template list and asserts all six ids are present and every one is labelled.
It runs before packaging, on all three platforms, and is not
`continue-on-error`.

**Consequences.** The failure this guards against is silent rather than loud. A
bundle that lost the module would not crash: `create_project` falls back to the
paper on an unknown id, so the picker would offer a single option and look like
a design decision. Nothing in a build log would say otherwise. The label check
is there because a blank `<option>` has already shipped once -- the route sends
`label`, the interface read `name` -- and jsdom computes no layout, so an
interface test cannot see a picker that renders as empty lines.


## 2026-08-13: the page titles go, and Library introduces the others

**Context.** Every screen carried a heading repeating the nav item that was
already highlighted.

**Decision.** No page titles. Library carries a collapsible list of what the
other screens are for, generated from `features.js`.

**Consequences.** "LitGraph" and "Scribe" mean nothing to someone who has just
installed this, and each page's own "i" cannot help -- you have to already be
there, and you will not open a screen whose name tells you nothing. Saying it
once on the page everyone lands on is what lets the headings go, and Scribe
gets that strip back for its editor. Generated from `features.js` so a new
feature appears without anyone remembering, and so the wording cannot drift
from the "i" guide reading the same field. It expands only for someone who has
never run the app: introducing an existing user to their own workspace after an
update reads as a regression.

## 2026-08-12: the extractor is scored on papers nobody here chose

**Context.** A curated test set proves the rules match the papers the rules
were written against.

**Decision.** `local/eval_metadata.py` samples papers across 15 arXiv
categories through the API and scores against arXiv's own metadata.

**Consequences.** The curated 18 were 100%; the random 56 were 62.5%, and the
gap was entirely templates nobody had looked at -- RevTeX spacing wide enough
to read as columns, APS running from affiliations into an unlabelled abstract,
and a margin cutoff that was deleting the first line of any centred title.
Fixing those took the sample to 92.9% titles and 85.7% exact author lists. A
number from papers you picked measures your test set, not your extractor.

## 2026-08-09: the advice asks Vulkan, not nvidia-smi

**Context.** Two detectors answer "is there a GPU here". `vram_gb` comes from
`nvidia-smi`, which exists only where NVIDIA's proprietary driver is installed.
`accelerable_device` comes from Vulkan, which reaches AMD, Intel and Mesa/NVK
too. The Bench advice was gated on `vram_gb >= 2`.

**Decision.** Gate on `accelerable_device`, keeping `vram_gb` as the fallback
for a card `nvidia-smi` found but Vulkan could not reach.

**Consequences.** Every AMD, Intel and open-driver machine reported 0.0 GB, so
the sentence explaining that their GPU was idle never printed -- while the card
beside it offered them the graphics download anyway. The endpoint's own
docstring says it returns one payload so the panel can never render two halves
that disagree; this was the two halves disagreeing, on exactly the machines the
Vulkan work was done to reach. It was invisible here because the development
laptop reaches its RTX 3050 Ti through NVK, so `nvidia-smi` is absent and the
sentence had never once appeared.

## 2026-08-22: the branch name says which column moves

**Context.** Since 2026-08-05 every landing moved Z, and only a human running
the release workflow could move Y. The reasoning was that "is this a feature
release" is an editorial judgement and a script reading branch prefixes cannot
make one -- it can only guess consistently, which is what an earlier rule did
and what produced version numbers nobody had chosen.

**Decision.** `feat/` and `feature/` move Y and reset Z. `fix/` and `hotfix/`
move Z. X is untouched by any branch name and stays with the release workflow.

**Why the earlier reasoning does not hold.** It was right that the judgement is
editorial and wrong about who makes it. Naming a branch `feat/` *is* the
judgement, made by the person who built the thing, at the moment they know it is
true -- not reconstructed later from a list of merges by someone reading titles.
What the old rule produced in practice was Y almost never moving, so the number
stopped saying anything about the SHAPE of what had landed: a build that had
gained a whole subsystem read the same as one that had fixed a typo, and the
only signal was a warning nobody had to act on.

X stays a decision, because "this is a new generation of the product" is not a
claim a branch name can make.

**Consequence.** `replay_landings` in `scripts/next_version.py` routes features
through `bump_minor`. The `--pending-minor` warning is removed along with its
step-summary block in `release.yml`: it existed only because the old rule had no
enforcement, and now the condition it watched for cannot arise, so it could only
ever be wrong. Order of landings matters again and is asserted -- a feature
resets Z, so fix-feat-fix and feat-fix-fix differ.

Note that the entry below, from 2026-08-18, says "X and Y are editorial by
design". That was true when written and is now true only of X.

## 2026-08-18: Y carries into X at ten (supersedes 2026-08-09)

**Context.** The radix was raised from ten to twenty on 2026-08-09, so that X
would not climb after ten declared minors — ten features can be one quiet
quarter, and a major number that moves for reasons no user can feel says
nothing.

**Decision.** Back to ten. Y is a single digit, 0-9; at ten it carries into X
and resets. X is unbounded. Z is unbounded and resets whenever a column above
it moves.

**Why the earlier reasoning does not hold.** The scheme is a decimal odometer,
and the whole value of that is that Y never shows two digits — the distance
between two versions is then readable at a glance, without parsing. A radix of
twenty permits `1.19.4`, which is the exact shape the scheme was chosen to
avoid, and it buys nothing the reader can feel either.

The problem the earlier change was aimed at is real but sits elsewhere: if X
climbs too often, minors are being declared too readily. That is an editorial
habit, and X and Y are editorial by design. Moving the radix to fix it was
treating a judgement problem as an arithmetic one.

**Consequence.** `MINOR_RADIX = 10` in `scripts/next_version.py`, with tests
asserting the invariant directly rather than by example. `v1.10.0`, already
published, keeps a two-digit Y that the rule now forbids — re-tagging a
published release is blocked by the `v*` ruleset, and anyone on it would see a
version that no longer exists. It corrects itself at the next declared minor.

## 2026-08-09: Y carries into X at twenty

**Context.** The version scheme carried Y into X at ten, so a tenth feature
produced a major version.

**Decision.** Carry at twenty. Both lower columns still reset when X moves.

**Consequences.** Ten features can be one quiet quarter, so X climbed for
reasons no user could feel. Twenty is still an arbitrary line, but it falls
roughly where the application really has become a different one. Ordering is
unaffected, which is the only property the updater depends on.

## 2026-08-09: merging and publishing are one intention

**Context.** Promoting to production was `promote.sh release` to merge, then a
separate `gh workflow run release.yml` to publish. Both were needed; only the
first was memorable.

**Decision.** `scripts/ship.sh` does both, and asserts the result afterwards --
not a draft, not a prerelease, `latest.json` attached, four installers present,
`/releases/latest` resolving to the new tag.

**Consequences.** The gap was not theoretical: the merge was done, the dispatch
was not, and main sat un-released while everyone assumed it had shipped. The
assertions are there because each one has been wrong in a real release, and
because a broken release is indistinguishable from a working one from outside --
a draft is invisible, its assets 404, and the updater reads 404 as "up to date".

## 2026-08-09: a version may never go backwards, checked where the decision lands

**Context.** `release.yml` accepted a `version` override with no ordering check
at all. `-f version=1.0.0` would have tagged it and published it as "latest".

**Decision.** Refuse a version not ahead of the published one, in `ship.sh`
**and** in the workflow.

**Consequences.** The updater only moves forward, so a lower number is invisible
to everyone who already has the higher one, and nothing about the release says
so. The guard already existed in `release.sh`, which is not on the dispatch path
anyone uses -- duplicating it is deliberate, because a dispatch can be run from
the GitHub UI or a phone, which is exactly when no script is involved.

## 2026-08-09: rollback is two problems, because you cannot un-ship

**Context.** A bad release reaches two populations: people who have not updated
yet, and people who have.

**Decision.** `scripts/rollback.sh` marks the bad release a prerelease, which
makes `/releases/latest` fall back to the previous one within seconds. `--reship`
publishes the previous tree under a *higher* number.

**Consequences.** The updater only ever moves forward, so an app that already
updated will never move back and deleting the release does not reach it --
forward is the only direction that exists. Marking rather than deleting keeps
the assets for diagnosis and makes the first half reversible with `--undo`.

## 2026-08-08: a page declares whether it is a document or a workspace

**Context.** `.main-content` carried one `max-width: 1400px` for every screen.

**Decision.** A feature declares `fills: true` in `features.js`; workspaces take
the whole window, reading pages keep a measure.

**Consequences.** On a 1920px window Scribe's panes resized correctly inside a
1400px box and left 500px of dead space, so the dividers looked broken when they
were only out of room. The cap is right for reading -- prose set 1900px wide is
unreadable -- and wrong for working, and which one a page is belongs to the page.
Declared in the registry rather than matched on a path in CSS, for the same
reason as the nav, routes, marks and guides: a rewritten shell still reads it.

## 2026-08-08: the press arms the collapse; the gesture ending applies it

**Context.** Any press inside the page collapses the sidebar, and it collapsed
during the press.

**Decision.** `pointerdown` still triggers it, but the state change is deferred
to the end of the gesture. Keyboard stays immediate.

**Consequences.** The sidebar is 220px wide and the page is offset by it, so
collapsing slid the page 220px left while the button was still held. A click is
not something the page sends -- it is a conclusion the browser draws when
mousedown and mouseup land on the same element -- so moving the element between
them meant the sidebar shut and the action never ran. `pointerdown` remains the
trigger because LitGraph's lasso may never produce a click at all. Keyboard is
exempt because activating a focused control does not depend on where it is.

## 2026-08-08: a release asserts that it published

**Context.** A beta release built correctly, uploaded fifteen assets, reported
every job green, and stayed a draft.

**Decision.** After creating the release, assert it is not a draft and that the
manifest the updater fetches returns 200. Publish and retry if not.

**Consequences.** `draft: false` is a request, not a guarantee. A draft is
invisible and its assets 404, and the updater maps 404 to "up to date" -- so
testers were told they were current while the release sat there unreachable.
Checking the outcome beats predicting it; the suspected cause (`--cleanup-tag`)
was deliberately kept, because the rolling tag has to move to the new commit and
leaving it behind would strand beta on an older one.

## 2026-08-07: filenames arriving from the webview are untrusted

**Context.** The file API is reachable from the webview, which Tauri treats as
remote content. `../../../.ssh/id_rsa` is a filename.

**Decision.** Every operation resolves its argument against the project
directory and refuses anything landing outside. Resolution happens BEFORE the
check, never a string test for "..".

**Consequences.** Traversal, absolute paths, NUL bytes and symlinks pointing out
of the project are refused. Resolving first is what catches the symlink: nothing
about the name `notes.tex` says it points at `/etc`. Disabling the containment
check fails the tests, which is how we know they test it.

## 2026-08-07: the index is generated, not delegated to makeindex

**Context.** `\index{term}` writes `main.idx`; something must turn it into
`main.ind` before `\printindex` can read it. Tectonic runs BibTeX by itself but
not makeindex, so a paper with an index failed with `Undefined control sequence
\indexentry` -- `imakeidx` giving up and `\input`-ing the raw `.idx`.

**Decision.** `domain/paper_writer/indexing.py` builds the `.ind` in Python, and
the compiler runs a second pass when it changes.

**Consequences.** No second binary in the installer. Shelling out to makeindex
would have worked on this machine and on no user's -- the same mistake as
assuming a system LaTeX, which is what the bundled engine exists to avoid.
Sub-entries, `sort@printed` keys, `|hyperpage` encapsulators and `|(`...`|)`
page ranges are supported because real papers use them.

## 2026-08-07: no browser dialogs, because there is no browser

**Context.** "New file", "New folder" and "New paper" were built on
`window.prompt`, deletes on `window.confirm`. The Tauri webview implements
neither: `prompt` returns null, so every menu item silently did nothing.

**Decision.** Naming happens in an inline row in the tree, where the file will
appear. Destructive actions go through a shared `ConfirmDialog`.

**Consequences.** They work. A second defect hid behind the first: the context
menu closed on a capture-phase `pointerdown`, unmounting the button before its
own `click` landed, so even a working `prompt` would not have been reached. The
dialog is shared because this was about to be the third in the codebase -- and
`if (!confirm(...)) return` is worse than useless when `confirm` returns
undefined: the guard either blocks forever or deletes without asking.

## 2026-08-07: the page subtitle became an "i"

**Context.** Every screen carried a title and a sentence explaining the feature.
The sentence is worth reading once and then holds a strip of the window forever
-- and Scribe wants that strip so the editor and the PDF have half the height
each.

**Decision.** The title and its brush-slash stay. The sentence moves behind an
"i" in the bottom-left corner, on the brand accent, declared once per feature in
`frontend/src/features.js`.

**Consequences.** LitGraph already did this for its canvas controls, so this
generalises something that worked rather than inventing it; its private copy is
gone. The guide floats rather than pushes, so opening it never reflows an editor
mid-sentence and it costs no height closed.

## 2026-08-06: the shell watches for use; features do not report it

**Context.** Opening a paper, a node or a project wants the width the sidebar is
occupying. The first build of this hooked the handler for each of those, in each
feature.

**Decision.** The shell listens for a pointer or key press anywhere inside its
own content area and collapses the sidebar itself. Features call nothing and
import nothing.

**Consequences.** Every control on every screen counts, including ones nobody
enumerated and ones not written yet. The per-feature version was green in tests
and still felt broken, because everything absent from the list did nothing --
"any action" is not a list that can be kept complete across four screens of
buttons, fields, canvas drags and keystrokes. The listener is on the content
element only, so the nav and theme toggle are not "use". It is a capture-phase
`pointerdown`: several rows stop propagation on their own buttons, and the
canvas lasso is a drag that may never produce a click.

## 2026-08-06: an automatic collapse is not a saved preference

**Context.** The sidebar's collapsed state is persisted, like the theme. Once
actions could also collapse it, both wrote to the same flag.

**Decision.** Two flags. The one the logo sets persists; the one an action sets
lives for the session only. The sidebar hides when either is set, and the logo
clears both.

**Consequences.** Opening one paper no longer teaches the app to launch
collapsed forever -- a setting the user never chose, changed by something
unrelated to settings, with nothing on screen explaining it. Clearing both from
the logo is what stops it appearing dead: with one flag still held by a feature,
clicking it moved nothing.

## 2026-08-06: features are declared once, in a registry

**Context.** Each feature was written out as a nav entry and again as a route,
and the brand mark was inline SVG pasted in twice.

**Decision.** `frontend/src/features.js` holds id, path, label, icon, mark and
component. Nav, routes and the logo all render from it.

**Consequences.** Adding a feature is one entry and the shell needs no edit. The
mark follows the active feature, which is what makes the collapsed peek button
say where you are when nothing else on screen can. The two logo copies could
drift and no longer exist. The registry is data and knows nothing about a
sidebar, so it survives the interface refactor that reads it.

## 2026-08-05: Hugging Face download URLs are constructed, never accepted

**Context.** The local API is reachable from the webview, which Tauri treats as
remote content.

**Decision.** `/api/hf/download` takes a repository id and a filename and builds
the URL itself. It never accepts a URL.

**Consequences.** Only huggingface.co can be fetched from. Traversal sequences
and non-`.gguf` paths are refused before a socket opens. An endpoint that
fetched whatever address it was handed would be a general-purpose downloader
aimed by anything able to reach the local API.
## 2026-08-31: no bundled SLM weights
**decision:** ship no GGUF/SLM weights in desktop installers. Bench is the
explicit consent boundary for model downloads and can also reuse compatible
Ollama or LM Studio models already on the machine.
**rationale:** model weights made release artifacts unnecessarily large and
confused a user-managed model workflow with a mandatory installer dependency.
A fresh install must still support extraction, reading, embeddings/search, and
PDF writing offline; therefore the embedding model and Tectonic remain bundled.
**implementation:** `release.config.json` has an empty `models` array; the
packaging validator asserts that no LLM is present while it still exercises all
non-inference features on Linux, macOS, and Windows.
**status:** accepted.
