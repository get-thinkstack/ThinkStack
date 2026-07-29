# Contributing to ThinkStack

ThinkStack is an offline research assistant: a Python backend, a React UI, and a
Rust (Tauri) desktop shell, shipped as installers for Linux, macOS and Windows.

This guide is the practical one — how to get set up, what the branches mean, and
what will block your push. For *why* things are built the way they are, read
[docs/ADR.md](docs/ADR.md). For the release runbook, see
[scripts/README.md](scripts/README.md).

---

## Getting set up

```bash
git clone git@github.com:get-thinkstack/ThinkStack.git && cd ThinkStack
./scripts/setup.sh          # system deps, rust, python venv, node, latex
./scripts/install-hooks.sh  # activate the shared git hooks  <- don't skip this
```

`install-hooks.sh` points git at the version-controlled `.githooks/`, so everyone
runs the same checks and updates arrive with a normal `git pull`. It also audits
your local tooling and tells you what's missing.

**Install `shellcheck`.** Without it, `actionlint` silently skips its shell
checks, a broken `run:` block passes locally, and CI catches it instead. That has
already cost us a release build.

```bash
sudo dnf install ShellCheck      # fedora
sudo apt install shellcheck      # debian / ubuntu
brew install shellcheck          # macos
```

Then grab a model and run it:

```bash
mkdir -p data/models
huggingface-cli download Qwen/Qwen2.5-0.5B-Instruct-GGUF \
  qwen2.5-0.5b-instruct-q4_k_m.gguf --local-dir data/models

./scripts/dev.sh          # backend + vite, hot reload
./scripts/dev.sh --tauri  # ... plus the desktop window
```

---

## Branches

| Branch | What it's for | Push gate | Ships installers? |
|--------|---------------|-----------|-------------------|
| `dev`  | day-to-day work, experiments | **fast** — lint + tests on what changed | no |
| `beta` | integration; bundle and test real installers | **full** — everything CI runs | on a `vX.Y.Z-beta.N` tag |
| `main` | official releases | **full** | on a `vX.Y.Z` tag |

**Work on `dev`.** Branch from it, and merge back into it. `beta` and `main` are
promoted into, never developed on.

**Branches never build installers — tags do.** Merging to `beta` costs nothing;
you only pay the ~45 minute three-OS build when someone deliberately tags. If you
need a real installer without releasing, run a build on demand:

```bash
gh workflow run dev-build.yml -f platform=linux-x86_64
gh workflow run dev-build.yml -f platform=all -f skip_models=true
```

That produces downloadable artifacts and publishes nothing.

---

## Before you push

The pre-push hook runs [`scripts/preflight.sh`](scripts/preflight.sh), which
mirrors `.github/workflows/ci.yml` exactly. **Green locally means green in CI.**
You can run it yourself at any time:

```bash
scripts/preflight.sh            # scope by branch + what changed
scripts/preflight.sh --full     # everything, regardless of what changed
scripts/preflight.sh --fix      # auto-fix what can be fixed, then check
```

It's quick because it's **change-scoped** (editing a markdown file doesn't
compile Rust) and **branch-scoped** (`dev` gets the fast gate). It also warns
when your branch is behind its remote — validating against stale code is the most
common cause of "it passed locally but broke on main".

What the hooks block:

| Hook | Checks |
|------|--------|
| `pre-commit` (<2s) | committed keys/`.env`, Python syntax **against CI's 3.12**, JSON/YAML validity, merge-conflict markers |
| `pre-push` | ruff, pytest, actionlint + shellcheck, `cargo fmt`/`check` at the level your target branch demands |

Bypass once with `--no-verify` if you must. If you find yourself doing it often,
the gate is wrong — fix the gate.

> **Python version matters.** CI freezes the backend with **3.12**. If your local
> Python is newer, syntax it accepts may be a hard `SyntaxError` there. A stray
> `t"""` (valid in 3.14, fatal in 3.12) once shipped a build whose backend could
> not start. `preflight.sh` uses `python3.12` when it's installed — please have it.

---

## Tests

```bash
pytest                    # the whole suite (~300 tests, a few seconds)
pytest tests/test_x.py    # one file
pytest -m heavy           # tests that load real models / hit the network
```

Tests live in `tests/`, mirroring the module they cover. They must be:

- **Isolated** — no network, no real model loads, no writes outside `tmp_path`.
  Anything that needs a real GGUF is marked `heavy` and skipped by default.
- **About behaviour, not implementation** — assert what a caller observes.
- **Explicit about edge cases** — the negative paths are usually the valuable
  ones. Most bugs we've caught were "what happens when this is missing/empty/
  malformed", not the happy path.

When you fix a bug, add the test that would have caught it, and say so in the
docstring. `tests/test_ollama_client.py` has examples.

---

## Code style

Enforced automatically, so there's little to memorise:

- **Python** — `ruff` with `E9` + `F` only (real bugs: syntax errors, undefined
  names, unused imports). No cosmetic rules; the gate never blocks on formatting
  opinions.
- **Rust** — `cargo fmt` (checked) and `cargo check`. Clippy runs non-blocking.
- **Shell** — `shellcheck`, excluding `SC1091`/`SC2015` (unfollowable `source`,
  and the `a && b || c` echo idiom used throughout).
- **Workflows** — `actionlint`. Keep `.github/workflows/*.yml` **ASCII-only**; the
  VSCode GitHub Actions extension misparses non-ASCII and floods the Problems
  panel. Use `--` not an em dash.

**Comments should explain *why*, not *what*.** The code already says what it
does. Reserve comments for the non-obvious: a constraint, a failure mode, a
decision someone would otherwise undo. Every guard in this codebase exists
because something broke — say which thing.

---

## Commits

Conventional-ish prefixes: `feat:`, `fix:`, `ci:`, `docs:`, `chore:`,
`test:`, `refactor:`.

User-visible changes go under `## [Unreleased]` in
[CHANGELOG.md](CHANGELOG.md) in the same PR. `release.sh` promotes that section
to the new version when you tag, so the changelog is never reconstructed from
memory afterwards.

Write the body for whoever hits this in six months. State the problem, the cause,
and why the fix is right — not a restatement of the diff. If a teammate found the
bug, credit them.

---

## Merging

Day to day you only ever touch `dev`. Nothing you merge reaches a user until
someone deliberately tags a release, so this loop is safe to run fast.

```bash
git switch dev && git pull            # always start from the latest dev
git switch -c feat/short-description  # or fix/…
# ... work, commit ...
scripts/preflight.sh                  # optional: the hook runs it anyway
git push -u origin feat/short-description
gh pr create --base dev
```

Merge it once **CI OK** is green. On `dev` you don't need anyone's approval —
review each other's work when it's worth reviewing, not as a ritual.

### What each branch will let you do

| | `dev` | `beta` | `main` |
|---|---|---|---|
| Push directly | yes | yes | **no — PR only** |
| Pull request required | no | no | **yes** |
| `CI OK` must be green | no (hook still gates you) | **yes** | **yes** |
| Branch must be up to date to merge | — | no | **yes** |
| Force-push / delete | allowed | blocked | blocked |

`main` and `beta` are **promoted into, never developed on** — use
`scripts/promote.sh`, which does the branch-and-tag dance for you. A PR straight
into `main` is for the rare case where a promotion isn't the right shape; it
still can't merge red.

**If a merge into `dev` breaks something**, fix forward on `dev`. Nothing has
shipped — no installers were built and no user is running that code.

---

## Releasing

### Who can do it

All three of us have **write** access, and a release is triggered by pushing a
`vX.Y.Z` tag. There is **no tag protection**, so — as things stand — any of us
can publish a release that auto-updates every installed app.

| | Rithesh (`Rithesh077`) | Aditya (`AdityaMehta2006`) | Jitvan (`jitvanChadha`) |
|---|---|---|---|
| Role | admin | write | write |
| Merge to `dev` / `beta` | yes | yes | yes |
| Merge to `main` (green PR) | yes | yes | yes |
| **Cut a release** | yes | yes | yes |

The convention, not currently enforced by GitHub: **stable releases go through
the maintainer (Rithesh).** Beta tags are fair game for anyone — that's what beta
is for. If you're about to run `promote.sh release`, say so in the group first.

Note that branch protection does **not** cover tags. A tag can be pushed from any
commit, including one that never went through `main`. `release.sh` is what
actually checks that the commit is green (see the guards below) — respect it, and
don't reach for `git tag` by hand.

### The two paths

```bash
# a feature: soak it on beta first, users later
scripts/promote.sh feature 1.1.0     # dev -> beta,  tags v1.1.0-beta.N
#   ... testers install the beta on all three OSes ...
scripts/promote.sh release 1.1.0     # beta -> main, tags v1.1.0

# a bug fix: beta AND main together, no soak
scripts/promote.sh fix 1.0.1
```

`--dry-run` prints every git command without running one. Use it the first time.

Each tag kicks off a **~45 minute three-OS build** that publishes installers and
the signed updater manifest. Installed apps pick the update up on next launch —
nobody re-downloads anything, and there is nothing to upload by hand.

### What can stop you

`release.sh` refuses to tag when:

- the working tree is dirty, or the tag already exists
- the version is **older than what's published** — the updater would drag
  installed apps backwards, and that can't be undone
- **CI isn't green** for the exact commit being tagged

and CI fails the publish if any installer reaches GitHub's **2 GiB** asset limit
(it warns past 90%).

None of this can be un-shipped, which is the whole reason the guards exist. If
one blocks you, it is almost always right.

### If a release goes wrong

A bad **beta** is just another beta tag — bump the counter and re-promote.

A bad **stable** is fixed forward: `scripts/promote.sh fix <next-patch>`. Don't
delete the tag or the release; installed apps follow whatever `latest` points at,
and yanking it strands anyone mid-update.

---

## Repository layout

```text
main.py            fastapi app: serves the react spa and /api
config.py          pydantic-settings config (env prefix: THINKSTACK_)
api/               rest endpoints
domain/            core logic (ingestion, search, analysis, paper_writer,
                   encryption, model_manager, ...)
infrastructure/    llm client, vector store, hardware profiler, file manager
frontend/          react 19 + vite spa
src-tauri/         tauri 2 desktop shell (rust), incl. startup hardware diagnosis
scripts/           devops only — setup, dev, preflight, build, promote, release
tools/             developer utilities (gpu checks, fine-tuning, manual e2e)
tests/             the pytest suite
docs/              ABOUT (users), FEATURES (reference), ADR (decisions), TEAM
```

If you add a script, ask whether it's **devops** (`scripts/`) or a **developer
utility** (`tools/`). `scripts/` stays small enough to read in one sitting.

---

## Adding a model

Models are declared in `domain/model_manager/catalog.py`. The baseline is
**bundled** in the installer so a fresh install works offline; everything else is
optional and fetched only with explicit consent, and only when the machine can
run it.

Adding one to `release.config.json`'s `models` puts it back **inside the
installer** — keep the two in step, and mind the 2 GiB asset ceiling.

Discovery already finds models the user has via Ollama and LM Studio, matching on
a canonical `family/size` key, so we never re-download weights they already have.
If you add a model with unusual naming, check `discovery.model_key()` reduces it
the way you expect and add a case to `tests/test_model_manager.py`.

---

## Questions

Open an issue, or read [docs/ADR.md](docs/ADR.md) — most "why is it like this?"
questions are answered there, with the failure that motivated the decision.
