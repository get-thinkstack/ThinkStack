# Changelog

All notable changes to ThinkStack, newest first.

Versions follow [semantic versioning](https://semver.org): `MAJOR.MINOR.PATCH`.
A version exists only once it has been **tagged and published** — every entry
below corresponds to a real release with installers on the
[releases page](https://github.com/get-thinkstack/ThinkStack/releases).

Channels: **stable** (`vX.Y.Z`, what users get), **beta**
(`vX.Y.Z-beta.N`, opt-in testers), **nightly** (rolling, unversioned).
See [scripts/README.md](scripts/README.md) for how releases are cut.

---

## [Unreleased]

Work merged but not yet tagged.

### Fixed
- **The packaged app never started.** v1.0.0's installer showed a loading spinner
  indefinitely. The backend lookup missed the AppImage/deb layout (binary in
  `usr/bin`, resources in `usr/lib/ThinkStack`), so the app silently fell back to
  running a system `python3` -- which the AppImage's own `AppRun` had already
  broken by exporting `PYTHONHOME=$APPDIR/usr`, killing it with "Failed to import
  encodings module" before any of our code ran.
- **The window crashed a second after loading** on Fedora/Mesa: WebKitGTK's
  DMABUF renderer corrupts the heap. Disabled on Linux.
- **The embedding model was never bundled**, so ingesting the first document in a
  packaged build reached for HuggingFace -- impossible offline, and the docstring
  promised the opposite. It is now shipped inside the installer.
- **The model directory was derived from the working directory**, which is wrong
  for every installed app on every OS. The backend now resolves it itself.
- The loading screen polled `localhost`, which resolves to `::1` first while the
  backend binds IPv4 only.
- Declining the model prompt was permanent and irreversible: the flag lived in
  the webview's localStorage, outside the app, so even reinstalling did not clear
  it, and it silenced every future model rather than the one declined.

### Added
- **The loading screen reports every startup step** with timings, names the
  backend it is launching, and fails with a real error plus a log path instead of
  spinning forever. Startup is bounded at 180s.
- Backend output is captured to `backend.log` (Tauri's app log dir) alongside the
  startup trace, so a failed launch can be diagnosed after the window is gone.
- Sidebar: **Add better models**, **Update app**, and the running version.
- A **beta landing page** at `/beta/`, generated from the same `landing.html` and
  pointing at the newest prerelease.
- `scripts/build.sh` copies installers into `local/` (replacing older ones),
  smoke-tests the frozen backend over HTTP, stages only the models
  `release.config.json` declares, and packages the AppImage the way CI does.
- Beta-testing guide in `CONTRIBUTING.md`: what to check on each OS, per-OS log
  paths, and expected unsigned-build friction.

### Changed
- **A TeX engine ships inside the installer.** The paper writer no longer needs
  LaTeX installed on the machine — PDF compilation works out of the box, offline.
  Costs ~25 MB compressed per installer.
- **The compiled PDF is the only preview**, and it rebuilds itself shortly after
  you stop typing. An "Auto" toggle turns that off; the Compile button remains.
  The client-side KaTeX preview is gone: it was a second renderer that disagreed
  with the real PDF.
- **Select plain English and press Ctrl+Enter** to have the local model rewrite
  it as LaTeX in place.
- **The paper writer now uses the larger model when available.** It was routed to
  two fine-tuned models that are never built, so it silently fell through to the
  0.5B — which answered "plot y = x squared" with a reference to an image file
  that does not exist.
- **Updates are user-initiated only.** The check that ran on every launch is
  gone: an offline-first app should not contact the network unprompted. The
  sidebar button reports every outcome, including "Up to date".

---

## [1.0.0] - 2026-07-29

### Added
- First-run model setup: the app detects what your machine can run and offers a
  larger analysis model once, with a progress bar and a cancel button. Declining
  is remembered.
- Model discovery across runtimes — models already installed via **Ollama** or
  **LM Studio** are found and used instead of downloading a second copy.
- `CONTRIBUTING.md`: setup, branch model, what the hooks block, test conventions,
  and the merging + release guides — including who may cut a release and what
  each branch will refuse.
- On-demand modular builds (`dev-build.yml`) — build one OS without cutting a tag.
- Release guardrails: a tag is refused when the version is older than what is
  published or when CI is not green; the publish fails if any asset reaches
  GitHub's 2 GiB limit.
- Local gate (`scripts/preflight.sh`) and shared git hooks that mirror CI.
- `scripts/promote.sh` for the dev → beta → main promotion paths.

### Changed
- **Installers now bundle only the 0.5B baseline model.** Expected to cut every
  installer by roughly 1 GB. The app still works offline immediately; the larger
  analysis model is fetched on consent, or reused from an existing install.
- Documentation restructured: `RELEASE_GUIDE.md` folded into `docs/ADR.md`
  (decisions) and `scripts/README.md` (runbook). `docs/` now holds ABOUT,
  FEATURES, ADR and TEAM.

### Fixed
- Models the user already had could be offered for download again, because
  matching compared filenames and every runtime names the same weights
  differently (`qwen2.5:1.5b` vs `qwen2.5-1.5b-instruct-q4_k_m.gguf`). Matching
  is now on a canonical family/size key. *(Found by Aditya.)*
- The model loader only looked in ThinkStack's own directory, so analysis
  degraded to the base model even when the right weights sat in LM Studio's
  folder.

---

## [0.1.1] — 2026-07-29

First release to build successfully on **all three platforms**.

### Fixed
- **Windows builds failed** at the model-download step: `jq` emits CRLF on the
  Windows runner, leaving a trailing carriage return on the URL that curl
  rejected with "URL rejected: Malformed input to a URL function".
- **macOS builds failed** at code signing: the absent `APPLE_CERTIFICATE` secret
  was passed as an empty string, so Tauri tried to import an empty certificate
  instead of skipping signing.
- `release.sh` staged a path that no longer existed. `git add` is atomic across
  pathspecs, so it staged *nothing* and the version-bump commit aborted.

### Added
- CI smoke test: the frozen backend is booted and must answer
  `/api/system/health` before a build may continue — the only check that
  exercises the bundle rather than the source tree.
- Model and pip caching in CI (the build was re-downloading ~1.5 GB of weights on
  all three runners, every release).

---

## [0.1.0] — 2026-07-27

First public release. Installers for Linux, macOS and Windows, with a signed
auto-updater.

### Added
- PDF ingestion, hybrid search (semantic + BM25 with reciprocal rank fusion),
  summarization, thematic clustering and the gap finder.
- AI-assisted LaTeX paper writer with a live KaTeX preview and an auto-healing
  `pdflatex` compiler that still produces a PDF when a figure is broken.
- Local inference via `llama.cpp`, with task-based routing between a 0.5B and a
  1.5B model and a single resident model to cap memory.
- Paper encryption (Argon2id + AES-256-GCM).
- Native hardware diagnosis in the Tauri shell, replacing a multi-second
  `import torch` on the startup path.
- Automated release pipeline with stable / beta / nightly channels and in-app
  updates.

### Fixed
- A `t"""` typo that only Python 3.12 rejects (valid on the developer's 3.14), so
  every frozen build shipped a backend that could not import.
- Backend startup no longer imports torch/transformers eagerly (~4s → ~0.6s).
- The paper writer's last-resort figure salvage crashed on `re.sub` escapes,
  exactly when it was needed most.
