# Contributing to ThinkStack

ThinkStack is a Python backend, a React interface and a Rust (Tauri) desktop
shell, shipped as installers for Linux, macOS and Windows. This guide is the
practical one: setup, branches, what blocks a push, and how a release reaches
users. *Why* things are built this way is in [docs/ADR.md](docs/ADR.md).

- [Getting set up](#getting-set-up)
- [Branches](#branches)
- [Before you push](#before-you-push)
- [Dependencies](#dependencies)
- [Tests](#tests)
- [Code style](#code-style)
- [Commits and merging](#commits-and-merging)
- [Releasing](#releasing)
- [Beta testing](#beta-testing)
- [Scripts and tools](#scripts-and-tools)
- [Runtime dependencies](#runtime-dependencies)
- [Adding a model to the catalog](#adding-a-model-to-the-catalog)

---

## Getting set up

```bash
git clone git@github.com:get-thinkstack/ThinkStack.git && cd ThinkStack
./scripts/setup.sh          # system deps, rust, python venv, node, latex
./scripts/install-hooks.sh  # activate the shared git hooks  <- don't skip this
./scripts/fetch-tex.sh      # the TeX engine the installers bundle

./scripts/dev.sh            # backend + vite, hot reload
./scripts/dev.sh --tauri    # ... plus the desktop window
```

`install-hooks.sh` points git at the version-controlled `.githooks/`, so everyone
runs the same checks and updates arrive with `git pull`. It also audits your
tooling and says what is missing.

**Use Python 3.12 for the venv.** CI freezes the backend with 3.12, and syntax a
newer Python accepts can be a `SyntaxError` there (a stray `t"""`, valid in 3.14,
once shipped a backend that could not start). `preflight.sh` uses `python3.12`
when installed. If your OS upgrades its Python, a venv built on the old one
breaks silently (no `pip`); rebuild it with `python3.12 -m venv .venv`.

**Install `shellcheck`.** Without it `actionlint` silently skips its shell
checks, a broken `run:` block passes locally, and CI catches it instead.

```bash
sudo dnf install ShellCheck      # fedora
sudo apt install shellcheck      # debian / ubuntu
brew install shellcheck          # macos
```

**A model to test with.** None ships; add one in Bench, or:

```bash
mkdir -p data/models
huggingface-cli download Qwen/Qwen2.5-0.5B-Instruct-GGUF \
  qwen2.5-0.5b-instruct-q4_k_m.gguf --local-dir data/models
```

> **Windows: set the Rust toolchain for your machine, never in the repo.** The
> default Windows host is often `x86_64-pc-windows-gnu`, which needs MinGW's
> `dlltool.exe`. Use MSVC locally:
>
> ```bash
> rustup override set stable-x86_64-pc-windows-msvc   # this directory, untracked
> ```
>
> Never commit a `src-tauri/rust-toolchain.toml` with a host triple: it is
> repo-wide, makes `cargo metadata` fail on Linux and macOS, and `build.sh` once
> reported success over a build that produced no binary because of it.

**NVIDIA via CUDA, from source only (Windows).** The shipped engine is CPU-only
and acceleration is offered through Vulkan (see FEATURES). To try CUDA in a dev
checkout:

```bash
pip install llama-cpp-python \
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
python tools/fix_gpu_dlls.py   # CUDA runtime DLLs + a compatible CPU backend; idempotent
python tools/verify_gpu.py     # tokens/sec, confirms offload
```

`THINKSTACK_LLM_GPU_LAYERS=-1` forces full offload, `0` forces CPU.

---

## Branches

Work flows one way: `dev` → `beta` → `main`. Never merge `main` back into `beta`.

| Branch | For | Protection (GitHub) | Push gate (hooks) | Publishes |
|---|---|---|---|---|
| `dev` | day-to-day work | none | fast: lint + tests on what changed | nothing |
| `beta` | real installers for testers | `CI OK` must pass; no force-push or delete | full | a **beta**, on every push that changes code |
| `main` | releases | PR + 1 approval; `CI OK`; up to date; no force-push or delete | full | **nothing** on push; stable is dispatched (see [Releasing](#releasing)) |

Branch from `dev` and merge back into it; `beta` and `main` are promoted into,
never developed on.

**Need an installer without releasing?**

```bash
gh workflow run dev-build.yml -f platform=linux-x86_64
gh workflow run dev-build.yml -f platform=all -f skip_models=true
```

That produces downloadable artifacts and publishes nothing.

**Rolling tags are named `beta` and `nightly`**, the same as branches, on
purpose (`release.config.json` explains why). So a bare `beta` is ambiguous to
some git commands (`git log beta` reads the tag). `git switch beta` only ever
means the branch; elsewhere write `refs/heads/beta`.

---

## Before you push

The pre-push hook runs [`scripts/preflight.sh`](scripts/preflight.sh), which
mirrors `.github/workflows/ci.yml`. Green locally means green in CI.

```bash
scripts/preflight.sh            # scope by branch + what changed
scripts/preflight.sh --full     # everything
scripts/preflight.sh --fix      # auto-fix what can be fixed, then check
scripts/preflight.sh --no-fetch # skip the "behind your remote" check (offline)
```

It is change-scoped (editing markdown does not compile Rust) and branch-scoped
(`dev` gets the fast gate), and warns when your branch is behind its remote.

| Hook | Checks |
|---|---|
| `pre-commit` (fast) | committed keys / `.env`, Python syntax against CI's 3.12, JSON/YAML validity, conflict markers |
| `pre-push` | ruff, pytest, actionlint + shellcheck, `cargo fmt` / `check`, at the level the target branch demands |

Bypass once with `--no-verify`. If you do that often, fix the gate.

### Quality gates

Users run an installer, so the installer is what gets tested, not only the
source.

| Gate | Runs | Establishes |
|---|---|---|
| `preflight.sh` | your machine, every push | lint, Python + frontend tests, shellcheck, actionlint, cargo |
| CI (`ci.yml`) | every push | the same on a clean machine; `CI OK` is the required check |
| `validate_bundle.py` | Linux, macOS, Windows, every build | the frozen app starts, ingests a PDF, searches, compiles a PDF, embeds a figure, builds an index, reports its graphics hardware, and contains no LLM |
| GUI smoke test | Linux, every build | the launched AppImage is still alive after the point it once died at |

---

## Dependencies

**Every requirement in `requirements.txt` is pinned with `==`.**
`scripts/check_pins.py` refuses a range or a bare name, in CI and in
`preflight.sh`. Why: ADR 2026-08-01, "pin every dependency".

Do not upgrade by editing the file. Dependabot opens one PR per package against
`dev`, weekly; let CI build it, then merge. A new package goes in pinned, with
the reason for that version in the commit.

`requirements-test.txt` is the lean, unpinned set CI's unit tests use (no torch,
no llama.cpp). `requirements-dev.txt` is both.

---

## Tests

```bash
pytest                    # the suite; heavy tests are skipped
pytest tests/test_x.py    # one file
pytest -m heavy           # real models, the network, and offline template compiles
                          #   (the last needs scripts/fetch-tex.sh run first)
cd frontend && npx vitest run --maxWorkers=2   # interface tests; cap workers on a 16 GB machine
```

Tests live in `tests/`, named after the module they cover. They must be:

- **Isolated:** no network, no real model loads, no writes outside `tmp_path`.
  Anything needing a real GGUF is marked `heavy`.
- **About behaviour:** assert what a caller observes.
- **Explicit about edge cases:** most bugs caught here were "missing, empty or
  malformed", not the happy path.

When you fix a bug, add the test that would have caught it, and say so in its
docstring.

What automation cannot see: `jsdom` computes no layout, so a component can be
off-screen with every interface test green. Layout is checked by a person.

---

## Code style

Enforced automatically:

- **Python:** `ruff` with `E9` + `F` only (syntax errors, undefined names, unused
  imports). No cosmetic rules.
- **Rust:** `cargo fmt` (checked) and `cargo check`. Clippy runs non-blocking.
- **Shell:** `shellcheck`, excluding `SC1091` / `SC2015`.
- **Workflows:** `actionlint`. Keep `.github/workflows/*.yml` ASCII-only; the
  VS Code Actions extension misparses non-ASCII. Use `--`, not an em dash.

**Where writing goes:**

| What | Where |
|---|---|
| what a module is for, where it sits in the flow, the trap a maintainer must not break | the module docstring |
| a non-obvious rule beside the code it guards | a `#` comment, one or two lines |
| why it was built this way, what was rejected | `docs/ADR.md`, referenced by date |
| the story of a change | the commit message |

Do not restate type hints in docstrings, and do not narrate history in comments
("this used to..."): state the rule the code now keeps.

---

## Commits and merging

Prefixes: `feat:`, `fix:`, `ci:`, `docs:`, `chore:`, `test:`, `refactor:`. Write
the body for whoever hits this in six months: the problem, the cause, why the
fix is right. Credit a teammate who found the bug.

User-visible changes go under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md)
in the same PR; `ship.sh` renames that section to the version it publishes.

```bash
git switch dev && git pull
git switch -c feat/short-description   # or fix/...
# ... work, commit ...
git push -u origin feat/short-description
gh pr create --base dev
```

**The branch name sets the version.** `feat/` and `fix/` landings each move the
number; `chore/` and `docs/` do not; direct commits never do. The rules live in
one place, the docstring of [`scripts/next_version.py`](scripts/next_version.py):

```bash
scripts/next_version.py --explain --next   # replay what landed, show each bump
scripts/next_version.py --current          # newest published version
```

**Merge with `--no-ff`** (on GitHub, a merge commit). A fast-forward leaves no
merge commit, so the branch name never enters history and the landing is
invisible to the version replay. `promote.sh` does this for you.

If a merge into `dev` breaks something, fix forward on `dev`; nothing has
shipped.

---

## Releasing

Every publish is done by [`.github/workflows/release.yml`](.github/workflows/release.yml).
It derives the version, creates the tag, builds all three platforms, publishes
installers and the signed updater manifest. Tags trigger nothing; never tag by
hand.

| Channel | Published when | How |
|---|---|---|
| beta | a push to `beta` changes code (docs-only pushes are skipped) | `scripts/promote.sh feature` (or `fix`, `major`) merges `dev` → `beta` |
| stable | someone dispatches it | `scripts/ship.sh` |
| nightly | daily cron, only if something was committed that day | automatic |

**Stable is never published by merging.** A push to `main` builds nothing, by
design: "this is a release" must be said out loud (ADR 2026-08-06).
`scripts/ship.sh` does the whole thing:

```bash
scripts/ship.sh              # merge beta -> main, dispatch stable, watch, verify
scripts/ship.sh 2.4.0        # state the version instead of deriving it
scripts/ship.sh --dry-run    # every step, nothing changed
```

It refuses a dirty tree, an unreachable origin, a beta no ahead of main, a beta
whose own build failed, a version not ahead of what is published, and a tag that
already exists. Then it renames CHANGELOG's `[Unreleased]` to the new version
on beta (and cherry-picks that commit to dev), merges, and dispatches.
Afterwards it checks the release is real: not a draft, not a
prerelease, `latest.json` attached, every installer present, `/releases/latest`
pointing at it. Each of those has been wrong once; a broken release looks like a
working one from outside, and the updater reads a 404 as "up to date".

`release.yml` itself also refuses a stable version lower than the published
one, because it can be dispatched from the GitHub UI with no script involved.
`_publish-release.yml` fails any asset at GitHub's 2 GiB limit and warns near it.

**Convention:** stable releases go through the maintainer (Rithesh); say so in
the group before shipping. GitHub enforces only that `v*` tags cannot be moved
or deleted.

### Step 1: validate the real installer, locally

Required before any beta or stable. CI proves the code compiles and the tests
pass; it does not prove the app *starts*. A build once spun on its loading
screen for minutes because nothing in the gate launched the packaged app.

```bash
./scripts/build.sh     # builds, then replaces the installers in local/
```

`build.sh` clears `local/` first, so it always holds exactly the build you are
about to release. **Install and run that**, not `tauri dev` and not the bare
`dist/` backend. Then run the [tester checks](#what-a-tester-checks) yourself.

If startup fails, the screen shows the error and the log path.

### If a release goes wrong

A bad **beta** is fixed by the next push to `beta`.

A bad **stable** cannot be un-shipped: the updater only moves forward, so an app
that already updated never moves back, and deleting the release does not reach
it.

```bash
scripts/rollback.sh            # mark it prerelease; /releases/latest falls back in seconds
scripts/rollback.sh --reship   # also reach people who updated: old code, HIGHER number
scripts/rollback.sh --undo     # false alarm
```

Never delete a published tag or release by hand; installed apps follow
`latest`, and yanking it strands anyone mid-update.

---

## Beta testing

Beta answers the one question CI cannot: does the packaged app run on a machine
that is not a developer's?

### The download pages

One GitHub Pages site (a repository gets exactly one), two pages, both built by
`.github/workflows/deploy-pages.yml` from `landing.html`:

| URL | Built from | Buttons download |
|---|---|---|
| `https://get-thinkstack.github.io/ThinkStack/` | `main` | the newest stable release |
| `https://get-thinkstack.github.io/ThinkStack/beta/` | `beta` | the rolling `beta` release |

- `/beta/` is generated from the same file, with `/releases/latest/download/`
  rewritten to `/releases/download/beta/`. It does not look up "the newest
  prerelease": that once picked up nightly.
- The stable checkout is pinned to the default branch, or a push to `beta` would
  publish beta's page as the public one.
- Both pages rebuild on every run (a push touching `landing.html` or `assets/`,
  a published release, or a manual run).

Send testers the `/beta/` URL; the banner names the exact build.

### What a tester checks

In order; each has caught a real bug.

1. **It launches**, and the loading screen names each step. Note the time from a
   cold start (first run after install).
2. **The `spawn` step names the bundled backend:** `Backend: .../api/thinkstack-api`.
   If it falls back to a system Python, stop: the app cannot find its own backend.
3. **Ingest one PDF, offline.** The first thing to touch the embedding model, and
   the proof it shipped.
4. **Compile a Scribe document**, offline.
5. **Add a model in Bench**, then ask Scribe for one paragraph and run one
   analysis. Slow is fine; wrong or empty is not.

A beta is validated when all three OSes pass. Record who tested what where the
team can see it. Until then, do not ship.

### Reporting a failure

Send the screenshot and the log. The loading screen shows the log path on
failure; the file is `backend.log` in Tauri's `app_log_dir()`:

| OS | Log | Confirmed by running it |
|---|---|---|
| Linux | `~/.local/share/com.thinkstack.app/logs/backend.log` | yes |
| macOS | `~/Library/Logs/com.thinkstack.app/backend.log` | no; first tester please confirm |
| Windows | `%LOCALAPPDATA%\com.thinkstack.app\logs\backend.log` | no; first tester please confirm |

### Not bugs: unsigned-build friction

macOS "could not verify" and Windows SmartScreen are expected until the builds
are signed; the workaround is in the [README](README.md#install). On Linux the
AppImage needs `chmod +x`. Report them only if the workaround fails.

---

## Scripts and tools

`scripts/` is devops only; `tools/` is developer utilities.

| Script | Does |
|---|---|
| `setup.sh` | one-time environment bootstrap |
| `install-hooks.sh` | activate `.githooks/` (once per clone) |
| `dev.sh` | backend + Vite, optionally the desktop window |
| `preflight.sh` | what CI runs, before you push |
| `validate.sh` | the full local gate |
| `fetch-tex.sh` | download Tectonic and warm its package cache |
| `build.sh` | local production build into `local/` |
| `package-appimage.sh` | package the Tauri AppDir into an AppImage |
| `compose-updater-manifest.sh` | build the signed `latest.json` |
| `make_bundled_manifest.py` | write `bundled.json`, what this build ships |
| `validate_bundle.py` | exercise a frozen bundle (see Quality gates) |
| `check_pins.py` | refuse unpinned requirements |
| `next_version.py` | the version rules, and the next number |
| `_ship_changelog.sh`, `_promote_changelog.py` | rename `[Unreleased]` to the shipped version (run by `ship.sh`) |
| `promote.sh` | merge only (`--no-ff`): `feature`, `fix`, `major` dev → beta (which publishes a beta); `release` beta → main, which publishes nothing (use `ship.sh`) |
| `ship.sh` | publish stable: merge, dispatch, verify |
| `rollback.sh` | get users off a bad stable |
| `set-repo.sh` | retarget the project at another GitHub owner/repo |
| `selftest.sh` / `selftest.ps1` | check an installed, running build for what has broken in shipped builds (Unix / Windows) |

| Tool | Does |
|---|---|
| `tools/verify_gpu.py`, `tools/fix_gpu_dlls.py` | CUDA from source (above) |
| `tools/finetune.py` | fine-tune on the collected training pairs |
| `tools/check_paper_writer.py` | manual end-to-end Scribe check; run directly, pytest does not collect it |

---

## Runtime dependencies

What a clean machine needs. Everything is shipped; nothing must be installed.

- **Python packages:** `requirements.txt`, frozen into the backend by PyInstaller.
- **Bundled data:** the embedding model (`all-MiniLM-L6-v2`) and Tectonic with a
  warmed package cache. No language model.
- **External binaries:** `nvidia-smi` (optional GPU probe in the Rust shell,
  timeout-guarded; absent means "no NVIDIA GPU") and `taskkill` (part of
  Windows). A system `pdflatex` / `tectonic` is used only by source checkouts.
- **Optional download:** the Vulkan inference engine, on request (FEATURES).

**If you add a runtime dependency, add it to `requirements.txt` and make
`validate_bundle.py` exercise it.** A dependency that is only installed is
invisible to whoever asks why a fresh install fails; `--hidden-import` names a
module to bundle, it does not install one.

---

## Adding a model to the catalog

The catalog of downloadable models is `domain/model_manager/catalog.py`. Nothing
is bundled: `release.config.json` keeps `"models": []`, and putting a model there
would put it back inside every installer (mind the 2 GiB asset limit). Never make
a reasoning model (Qwen3, DeepSeek-R1, QwQ) a default; see ADR 2026-08-05.

Discovery matches models the user already has on a canonical `family/size` key.
If you add a model with unusual naming, check `discovery.model_key()` reduces it
the way you expect, and add a case to `tests/test_model_manager.py`.
