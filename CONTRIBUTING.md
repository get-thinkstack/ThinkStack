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
| `beta` | integration; bundle and test real installers | **full** — everything CI runs | on a merge into `beta` |
| `main` | official releases | **full** | on merge |

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

### Rolling release tags are suffixed on purpose

The beta and nightly channels publish to *rolling* tags, named `beta-latest`
and `nightly-latest` in [`release.config.json`](release.config.json). The suffix
is not decoration: git resolves `refs/tags/` before `refs/heads/`, so when the
tag was called plain `beta` a bare `beta` meant the **release**, not the branch,
and `git checkout beta` detached onto a published build while `git pull`
reported a divergence that did not exist.

Nothing special is needed now. `git checkout beta`, `git pull`, and
`git pull origin beta` all mean the branch. **Never name a rolling tag after a
branch.**

If you cloned before this change, `./scripts/install-hooks.sh` deletes the two
stale tags.

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
pytest                    # the whole suite (<!-- autodoc:test_count -->348<!-- /autodoc --> tests, a few seconds)
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

### Step 1 — validate the actual installer, locally, first

**Required before any beta or stable release.** A green CI run says the code
compiles and the unit tests pass. It does not say the app *starts*. We shipped a
build whose startup screen spun for 200 seconds because nothing in the gate ever
launched the packaged application.

```bash
./scripts/build.sh          # builds, then copies installers into local/
```

`build.sh` deletes the old installers from `local/` and puts the fresh ones
there, so `local/` always holds exactly the build you are about to release. A
validation pass against last week's binary tells you nothing.

Now **install and run it from `local/`** — not `npm run tauri dev`, not the
`dist/` backend on its own. The packaged artifact is the only thing that
exercises the resource paths, the frozen imports and the startup handshake.

Check, at minimum:

- [ ] It launches, and the loading screen **names each step** as it happens.
- [ ] It reaches the UI. Note how long it took **from a cold start** (first run
      after install, not a second launch — the difference is minutes).
- [ ] Ingest one PDF. This is the first thing to touch the embedding model, and
      the first thing that would reveal a missing bundled model.
- [ ] Ask one chat question and run one analysis.
- [ ] If anything fails, the screen shows a **real error and a log path** —
      never an endless spinner.

If startup fails, the log is at the path shown on screen
(`~/.local/share/com.thinkstack.app/logs/backend.log` on Linux). Backend stdout and
stderr are captured there.

### Step 2 — promote

Only once the installer in `local/` has been validated:

```bash
scripts/promote.sh feature     # dev -> beta,   next MINOR
scripts/promote.sh fix         # dev -> beta AND main, next PATCH
scripts/promote.sh major       # dev -> beta,   next MAJOR
scripts/promote.sh release     # beta -> main,  what beta validated
```

**You do not pass a version.** It is derived from the newest published stable
tag, so nobody has to remember the rule or look it up:

| Kind | Bump | Example |
|------|------|---------|
| `fix` | patch | `1.0.0` -> `1.0.1` |
| `feature` | minor | `1.0.0` -> `1.1.0` |
| `major` | major | `1.0.0` -> `2.0.0` |
| `release` | none | promotes exactly what beta has been testing |

### Branch names carry the version

Name your branch for what it is, and the number follows:

| Branch | Counts as | Effect on `X.Y.Z` |
|--------|-----------|-------------------|
| `feat/short-description` | a feature | **Y+1**, and Z resets to 0 |
| `fix/short-description` | a fix | **Z+1** |
| `chore/...`, `docs/...` | neither | nothing |
| merging `beta` into `main` | a release | **nothing** — main publishes the number beta validated |

```bash
scripts/next_version.py --next --explain   # replay the merges, show each one
scripts/next_version.py --current          # the newest version, any channel
```

The base is the **newest tag across every channel**, stable or beta. It is not
the newest *stable* tag: beta was testing 1.6.7 while stable was 1.0.0, so a
patch bump computed from stable gave 1.0.1 — below what testers already had
installed. `release.sh` refuses to publish below what is out, and the updater
would have shown installed apps an "update" that moved them backwards.

From that base, every `feat/` and `fix/` branch merged since is replayed **in
the order it landed**, one bump each. Order matters and is not cosmetic: a fix
then a feature gives `X.(Y+1).0`, while a feature then a fix gives `X.(Y+1).1`.

> **Merges into `dev`, `beta` and `main` must be `--no-ff`.** A fast-forward
> creates no merge commit, so the branch name never enters the history and the
> landing is invisible to the replay. The release number would then depend on
> whether a merge happened to be fast-forwardable, which is not a property of
> the work. `promote.sh` passes `--no-ff` for you; pass it yourself when you
> merge by hand, and prefer a merge commit when merging a PR on GitHub.

**Direct commits do not move the version**, whatever their prefix. A merge is
what "landing" means; counting the commits inside one as well would bump the
number several times for a single piece of work. If you push `fix: typo`
straight to `dev`, the version does not change — put it on a `fix/` branch if
it should.

Pass a version explicitly to override, e.g. `scripts/promote.sh feature 1.6.7`.

`--dry-run` prints every git command without running one. Use it the first time.

**Merging `beta` into `main` releases automatically.** `release-on-main.yml`
reads the version beta validated, tags it, builds all three platforms and
publishes, so the installers users download are swapped without a manual step.
It does nothing if that version is already tagged.

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

## Beta testing

Beta exists to answer one question CI cannot: **does the packaged app actually
run on a real machine that isn't a developer's?** Every bug that has reached a
user so far was invisible to the test suite, because the suite tests source code
and users run an installer.

### The two landing pages

There is one public site with two channel pages, both deployed by
[`.github/workflows/deploy-pages.yml`](.github/workflows/deploy-pages.yml):

| URL | Built from | Download buttons serve | Audience |
|-----|------------|------------------------|----------|
| `https://get-thinkstack.github.io/ThinkStack/` | `landing.html` on **main** | the newest **stable** release | the public |
| `https://get-thinkstack.github.io/ThinkStack/beta/` | `landing.html` on **beta** | the newest **prerelease** | invited testers |

`dev` has no page. It is ordinary development; nothing it produces is downloadable
by anyone outside the team.

Three things about this are worth understanding before you change it:

- **A repository gets exactly one GitHub Pages site.** A separate site for beta
  is not possible; a subpath is. The upside is that `/beta/` is *generated* from
  the same `landing.html`, so the two channels cannot drift apart.
- **The beta tag is substituted at deploy time.** GitHub resolves
  `/releases/latest/` to the newest *stable* release on purpose and offers no
  equivalent URL for prereleases, so the workflow looks up the newest prerelease
  and rewrites the five download URLs. `/beta/` stays a static file — no
  client-side API call, nothing to rate-limit, no way for the buttons to break in
  a tester's browser.
- **The stable checkout is pinned to the default branch.** A bare `checkout`
  takes the triggering ref, so a push to `beta` would otherwise publish beta's
  page as the *public* one, handing pre-release downloads to everybody.

The deploy runs on: a push to `main` or `beta` touching `landing.html`, any
published release (a new beta tag changes what `/beta/` must point at), or
manually from the Actions tab. Both pages are rebuilt on every run, so a deploy
triggered by one branch can never publish a stale copy of the other.

If no prerelease exists yet, `/beta/` still deploys — its buttons point at the
releases page and the banner says so, rather than 404ing.

### Getting builds to testers

```bash
scripts/promote.sh feature <version>     # dev -> beta, tags vX.Y.Z-beta.N
```

That publishes installers for all three OSes as a **prerelease** and triggers a
Pages deploy, so `/beta/` picks up the new tag automatically. `latest` does not
move, so the public page and everyone's existing install are untouched.

Send testers the **`/beta/` URL**. They should not use the public page — it
serves stable builds, and a tester on the wrong build files bugs against code you
are not shipping. The green banner at the top of `/beta/` names the exact tag so
they can confirm what they are running.

### What a tester must actually check

Not "does it look fine" — these five, in order. Each one has caught a real bug.

1. **It launches.** The loading screen names each step with timings. Note the
   time **from a cold start** (first run after install, not a second launch).
2. **The `spawn:` line names the bundled backend** — a path ending in
   `api/thinkstack-api`. If it says *"falling back to a system python"*, stop:
   the app cannot find its own backend on that platform. That exact bug shipped
   in v1.0.0-beta and presented as a spinner that never ended.
3. **Ingest one PDF.** This is the first thing to touch the embedding model, and
   the only check that proves the weights actually shipped. It must not need a
   network connection.
4. **Ask one chat question.** Slow is fine — the bundled 0.5B on a CPU takes
   ~20s. Wrong or empty is not.
5. **Run one analysis.** With only the baseline model this degrades to the 0.5B
   and will be rougher than a 1.5B. It must still produce something coherent.

Also confirm the first-run model prompt appears **once**, states what it wants to
download and why, and downloads **nothing** if you decline.

### Reporting a failure

Send the screenshot **and** the log. The loading screen shows the log path on
failure; the file holds the full timestamped trace including backend output.

| OS | Log path | Confirmed |
|----|----------|-----------|
| Linux | `~/.local/share/com.thinkstack.app/logs/backend.log` | yes |
| macOS | `~/Library/Logs/com.thinkstack.app/backend.log` | **no — first tester please confirm** |
| Windows | `%LOCALAPPDATA%\com.thinkstack.app\logs\backend.log` | **no — first tester please confirm** |

Only the Linux path has been verified by running it. The other two follow
Tauri's documented `app_log_dir()` layout; if the file isn't there, say so and
we'll correct this table.

### Not bugs — expected friction on unsigned builds

Report these only if the workaround fails:

- **macOS** — "Apple could not verify ThinkStack is free of malware." The build
  is not notarized (that needs a paid Apple Developer account). On **macOS 15+
  the right-click → Open trick no longer works**: go **System Settings → Privacy
  & Security → Open Anyway**. On macOS 14 and earlier, right-click → Open. One
  time either way.
- **Windows** — SmartScreen blue box. **More info** → **Run anyway**. One time.
- **Linux** — the AppImage needs `chmod +x` before it will run.

We do not yet pay for Apple/Windows code-signing certificates, so every tester
sees these.

### Sign-off

A beta is validated when **all three OSes** have completed the five checks above.
Record who tested what where the team can see it. Until then, do not run
`scripts/promote.sh release` — a stable tag moves `latest` and auto-updates every
installed app, and cannot be un-shipped.

---

## Repository layout and dependencies

```text
main.py            fastapi app: serves the react spa and /api
config.py          pydantic-settings config (env prefix: THINKSTACK_)
api/               9 routers: documents, search, analysis, gaps, chat,
                   encryption, papers, models, system
domain/            core logic, one package per capability:
                     ingestion/       pdf_parser, chunker, metadata_extractor
                     knowledge_base/  embedding_service, repository
                     search/          semantic, keyword (BM25), hybrid (RRF)
                     analysis/        summarizer, claim_extractor, theme_clusterer
                     gap_finder/      gap_analyzer, suggestion_engine, pipeline
                     chat/            chat_service
                     paper_writer/    compiler (the largest single module)
                     encryption/      kdf (argon2), cipher, envelope, vault
                     model_manager/   catalog, discovery, downloader
                     fine_tuning/     data_collector
infrastructure/    ollama_client (llm runtime), local_vector_store, hardware,
                   file_manager, atomic_io, caches and histories
frontend/          react 19 + vite spa
src-tauri/         tauri 2 desktop shell (rust): lib.rs, diagnosis.rs
scripts/           devops only
tools/             developer utilities
tests/             the pytest suite
```

<!-- autodoc:python_loc -->7,377 lines across 51 modules<!-- /autodoc -->. Small enough to read; do that before guessing.

### Every runtime dependency

This table is the answer to "what does a clean machine need?". It was
compiled by walking every import and every `subprocess`/`Command::new` call,
after we shipped a build whose flagship feature needed a package no user had.

**Python — all frozen into the bundle by PyInstaller:**

`argon2` `cryptography` `fastapi` `fitz` (pymupdf) `httpx` `llama_cpp`
`numpy` `pdfplumber` `psutil` `pydantic` `pydantic_settings` `rank_bm25`
`sentence_transformers` `torch` `uvicorn`

**Model weights — shipped inside the installer:**

| Asset | Purpose | Bundled |
|---|---|---|
| `qwen2.5-0.5b-instruct-q4_k_m.gguf` | chat, search, paper writer | yes |
| `all-MiniLM-L6-v2` | embeddings (ingest + search) | yes |
| `qwen2.5-1.5b-instruct-q4_k_m.gguf` | analysis, gap finder | no — offered on consent |

**External binaries:**

| Binary | Used by | Status |
|---|---|---|
| `tectonic` | paper writer, PDF compilation | **Bundled** (`scripts/fetch-tex.sh`), with a package cache warmed against the writer's whole preamble, so a clean machine compiles offline. A system `pdflatex`/`tectonic` is used only when the bundled one is absent, i.e. source checkouts. |
| `nvidia-smi` | Rust hardware diagnosis | optional, timeout-guarded; absent simply means "no GPU" |
| `taskkill` | Rust, Windows shutdown | ships with Windows |

**Every runtime dependency is now shipped.** `nvidia-smi` and `taskkill` are the
only externals left, and neither is required: one is an optional GPU probe, the
other is part of Windows.

**If you add a dependency, add it here.** A dependency that exists only in
`requirements.txt` is invisible to whoever later asks why a fresh install
fails on someone else's machine.

### Verifying it

`scripts/validate_bundle.py` runs against a built bundle and exercises the
real paths — ingest (embedding model), search (BM25 + vectors), inference
(llama.cpp). CI runs it on macOS, Windows and Linux on every build, so a
dependency that did not ship fails the build rather than reaching a user.

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
