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
