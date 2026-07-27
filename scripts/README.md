# scripts/

DevOps scripts only — bootstrap, run, validate, build, release. Anything that
isn't part of getting the app built, tested, or shipped lives elsewhere (`tools/`
for developer/GPU utilities, `tests/` for the pytest suite).

## First thing after cloning

```bash
./scripts/setup.sh          # system deps, toolchains, packages
./scripts/install-hooks.sh  # activate the shared git hooks
```

`install-hooks.sh` points git at the version-controlled `.githooks/`, so the
whole team gets the same hooks and updates arrive with a normal `git pull`.

## The branch model

| Branch | Purpose | Push gate | Ships installers? |
|--------|---------|-----------|-------------------|
| `dev`  | day-to-day work, experiments | **fast** — lint + tests on what changed | no |
| `beta` | integration; bundle and test real installers | **full** — everything CI runs | on a `vX.Y.Z-beta.N` tag |
| `prod` | official releases | **full** | on a `vX.Y.Z` tag |

**Branches don't build installers — tags do.** Merging to `beta` costs nothing;
you only pay the ~20 minute three-OS build when you deliberately tag. That keeps
`dev` fast and loose while `prod` stays deliberate.

Typical flow:

```bash
# 1. work on dev
git switch dev && git pull --rebase
#    ... commit, push (fast gate runs automatically)

# 2. ready to test real binaries -> beta
git switch beta && git merge dev && git push
scripts/release.sh 0.2.0 --beta 1 --push     # builds + publishes the beta

# 3. beta looks good -> prod
git switch prod && git merge beta && git push
scripts/release.sh 0.2.0 --push              # the stable release users get
```

Rollback: a bad beta is just a new beta tag. A bad stable is fixed by tagging the
next patch — installed apps auto-update to whatever `latest` points at.

## Scripts

| script | what it does |
|--------|--------------|
| `setup.sh` | one-time environment bootstrap |
| `install-hooks.sh` | activate the shared git hooks (run once per clone) |
| `preflight.sh` | **run what CI runs, before pushing** — see below |
| `dev.sh` | run the FastAPI backend + Vite frontend locally |
| `validate.sh` | the full local gate (superset of preflight's fast mode) |
| `build.sh` | local production build (freeze backend, build frontend, compile Tauri) |
| `package-appimage.sh` | package the Tauri AppDir into an AppImage |
| `compose-updater-manifest.sh` | build the signed `latest.json` updater manifest |
| `release.sh` | cut a release: bump version, tag the channel, push |
| `set-repo.sh` | retarget the project at a different GitHub owner/repo |

## preflight.sh

Mirrors `.github/workflows/ci.yml` exactly, so a green run here means a green run
in CI. It runs automatically on `git push` via the pre-push hook.

```bash
scripts/preflight.sh            # auto: scope by branch + changed files
scripts/preflight.sh --full     # everything, regardless of what changed
scripts/preflight.sh --fix      # auto-fix what can be fixed, then check
scripts/preflight.sh --no-fetch # skip the staleness check (offline)
```

It is fast because it is **change-scoped** (editing a markdown file does not
compile Rust) and **branch-scoped** (`dev` gets the fast gate). It also warns
when your branch is behind its remote — validating against stale code is the most
common cause of "it passed locally but broke on main".

**Install `shellcheck`.** Without it `actionlint` silently skips its shell checks
and a broken `run:` block sails through locally, then fails in CI — that has
already happened once.

```
fedora: sudo dnf install ShellCheck      debian/ubuntu: sudo apt install shellcheck
```

## Hooks

| hook | when | does |
|------|------|------|
| `pre-commit` | every commit, <2s | blocks committed secrets/keys, checks Python syntax against CI's interpreter, validates JSON/YAML, catches conflict markers |
| `pre-push` | every push | runs `preflight.sh` at the level the target branch demands; blocks the push if CI would fail |

Bypass once with `git commit --no-verify` / `git push --no-verify`.

---

Non-devops utilities live in `tools/`: `finetune.py`, `verify_gpu.py`,
`fix_gpu_dlls.py`, and `test_paper_writer.py` (a manual end-to-end check).
Automated tests are in `tests/` and run with `pytest`.
