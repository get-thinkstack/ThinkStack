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
| `main` | official releases | **full** | on a `vX.Y.Z` tag |

**Branches don't build installers — tags do.** Merging to `beta` costs nothing;
you only pay the ~20 minute three-OS build when you deliberately tag. That keeps
`dev` fast and loose while `main` stays deliberate.

### Promoting work (and shipping the binaries for it)

`promote.sh` encodes both paths so nobody has to remember the branch/tag dance.
Every tag it cuts rebuilds and republishes that channel's installers, and
installed apps auto-update to them — so the binaries swap as a consequence of
promoting, with nothing to upload by hand.

```bash
# a feature: soak it on beta first, users later
scripts/promote.sh feature 0.2.0     # dev -> beta,  tags v0.2.0-beta.N
#   ... testers try the beta installers ...
scripts/promote.sh release 0.2.0     # beta -> main, tags v0.2.0 (users get it)

# a bug fix: beta AND main together, no soak
scripts/promote.sh fix 0.1.1         # dev -> beta + main, tags both
```

`--dry-run` prints every git command without running one. `--yes` skips the
prompt. It refuses to start from a dirty tree, fast-forwards each target from
origin first, aborts cleanly on a merge conflict, and picks the next
`-beta.N` counter for you.

Rollback: a bad beta is just a new beta tag. A bad stable is fixed by
`scripts/promote.sh fix <next-patch>` — installed apps auto-update to whatever
`latest` points at. Don't delete a published tag or release: installed apps
follow `latest`, and yanking it strands anyone mid-update.

### Who can cut one

Everyone with write access can push a tag, and a tag is what ships installers —
branch protection covers `main` and `beta` but **not tags**. By convention
**stable releases go through the maintainer**; beta tags are open to anyone.
See [CONTRIBUTING.md](../CONTRIBUTING.md#releasing) for the access table.

Because nothing enforces this, use `release.sh`/`promote.sh` rather than
`git tag` by hand — the guards below only run if you do.

### Release guardrails

A tag ships installers to real users and cannot be un-shipped, so `release.sh`
refuses to cut one when:

| Guard | Why |
|-------|-----|
| working tree is dirty | uncommitted work would not be in the build |
| tag already exists | re-tagging silently changes what a version means |
| **version is older than what's published** | the updater would move installed apps *backwards* |
| **CI is not green for this commit** | the tag is what builds installers; a red commit ships broken |
| no CI results found | the commit isn't pushed, so nothing has been verified (prompts on stable) |

CI adds one more, at publish time: any asset **≥ 2 GiB** fails the release with a
named file, because GitHub rejects it and the upload would otherwise die partway
through after a ~45 minute build. Installers currently sit near 1.9 GiB, so a
warning fires past 90%.

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
| `promote.sh` | move work dev→beta→main and ship that channel's installers |
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
