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
