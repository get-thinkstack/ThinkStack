#!/bin/bash
# thinkstack: pre-flight checks - run what CI runs, before you push.
#
# The point: a green run here means a green run in CI. Everything below mirrors
# .github/workflows/ci.yml exactly. When you add a job there, add it here.
#
# Two things make this fast enough to run on every push:
#
#   1. CHANGE-SCOPED. Only checks whose files actually changed are run. Touching
#      a markdown file does not compile Rust.
#   2. BRANCH-SCOPED. `dev` is for experimenting, so it runs the fast gate.
#      `beta`/`main` gate real builds and releases, so they run everything.
#
# usage:
#   scripts/preflight.sh              # auto: scope by branch + changed files
#   scripts/preflight.sh --full       # everything, regardless of what changed
#   scripts/preflight.sh --fast       # lint + tests only
#   scripts/preflight.sh --fix        # auto-fix what can be fixed, then check
#   scripts/preflight.sh --no-fetch   # skip the staleness check (offline)
set -uo pipefail

# no `set -e` here: checks are meant to run to completion and report every
# failure at once, so `cd` needs its own guard.
cd "$(dirname "$0")/.." || exit 1

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'

MODE="auto"
FIX=false
FETCH=true
for arg in "$@"; do
    case "$arg" in
        --full)     MODE="full" ;;
        --fast)     MODE="fast" ;;
        --fix)      FIX=true ;;
        --no-fetch) FETCH=false ;;
        -h|--help)  sed -n '2,20p' "$0"; exit 0 ;;
    esac
done

BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
ERRORS=0
WARNINGS=0

echo -e "${CYAN}────────────────────────────────────────────${NC}"
echo -e "${CYAN}  pre-flight  ${NC}branch: ${GREEN}${BRANCH}${NC}"
echo -e "${CYAN}────────────────────────────────────────────${NC}"

# ── branch policy ───────────────────────────────────────────
# dev  : experiment freely, fast gate
# beta : bundles + tests installers, full gate
# main : official releases, full gate
case "$BRANCH" in
    main|master|beta) LEVEL="full" ;;
    *)                LEVEL="fast" ;;
esac
[ "$MODE" = "full" ] && LEVEL="full"
[ "$MODE" = "fast" ] && LEVEL="fast"
echo -e "  gate: ${GREEN}${LEVEL}${NC}$([ "$MODE" = auto ] && echo " (from branch)" || echo " (forced)")"

# ── are we behind the remote? ───────────────────────────────
# pushing from a stale branch is the most common cause of "it passed locally but
# broke on main": you validated against code that is no longer what you'd merge.
if $FETCH && git remote get-url origin >/dev/null 2>&1; then
    echo ""
    echo -e "${CYAN}[staleness]${NC} checking against origin..."
    if git fetch --quiet origin 2>/dev/null; then
        UPSTREAM="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo "")"
        # no upstream yet (new branch) -> compare against the integration branch
        if [ -z "$UPSTREAM" ]; then
            for cand in origin/dev origin/main origin/master; do
                if git rev-parse --verify --quiet "$cand" >/dev/null; then UPSTREAM="$cand"; break; fi
            done
        fi
        if [ -n "$UPSTREAM" ]; then
            BEHIND="$(git rev-list --count "HEAD..$UPSTREAM" 2>/dev/null || echo 0)"
            AHEAD="$(git rev-list --count "$UPSTREAM..HEAD" 2>/dev/null || echo 0)"
            if [ "$BEHIND" -gt 0 ]; then
                echo -e "  ${YELLOW}!${NC} ${BEHIND} commit(s) behind ${UPSTREAM} (you are ${AHEAD} ahead)"
                echo -e "    you are validating against stale code. rebase first:"
                echo -e "      ${CYAN}git pull --rebase origin ${UPSTREAM#origin/}${NC}"
                WARNINGS=$((WARNINGS+1))
            else
                echo -e "  ${GREEN}✓${NC} up to date with ${UPSTREAM} (${AHEAD} ahead)"
            fi
        else
            echo -e "  ${YELLOW}!${NC} no upstream to compare against"
        fi
    else
        echo -e "  ${YELLOW}!${NC} could not reach origin (offline?) - skipping"
    fi
fi

# ── what changed? ───────────────────────────────────────────
# compare against the upstream when there is one, else the working tree. this is
# what lets us skip whole toolchains that the change cannot possibly affect.
BASE="$(git rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || echo "")"
if [ -z "$BASE" ]; then
    # A branch that has never been pushed has no upstream, which is every
    # feat/ and fix/ branch on its first run -- the workflow CONTRIBUTING
    # tells people to use. Falling through to the working-tree diff meant
    # that once the work was COMMITTED there was nothing left to see, so
    # "0 changed files" skipped every toolchain and preflight reported
    # "CI should be green" without having run anything at all.
    #
    # Compare against the branch this one merges back into instead.
    for cand in refs/remotes/origin/dev refs/remotes/origin/main; do
        if git rev-parse --verify --quiet "$cand" >/dev/null; then
            BASE="$cand"
            break
        fi
    done
fi
if [ -n "$BASE" ] && git rev-parse --verify --quiet "$BASE" >/dev/null; then
    CHANGED="$(git diff --name-only "$BASE"...HEAD 2>/dev/null; git diff --name-only HEAD 2>/dev/null; git diff --cached --name-only 2>/dev/null)"
else
    CHANGED="$(git diff --name-only HEAD 2>/dev/null; git diff --cached --name-only 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null)"
fi
CHANGED="$(echo "$CHANGED" | sort -u | grep -v '^$' || true)"

changed_matches() {  # $1 = grep -E pattern
    [ "$LEVEL" = "full" ] && return 0          # full gate checks everything
    [ -z "$CHANGED" ] && return 1
    echo "$CHANGED" | grep -qE "$1"
}

if [ "$LEVEL" = "fast" ]; then
    N="$(echo "$CHANGED" | grep -c . || true)"
    echo -e "  scope: ${N} changed file(s)"
fi

run_check() {  # name, command...
    local name="$1"; shift
    echo ""
    echo -e "${CYAN}[${name}]${NC}"
    if "$@"; then
        echo -e "  ${GREEN}✓${NC} ${name} passed"
    else
        echo -e "  ${RED}✗${NC} ${name} FAILED - CI will fail on this"
        ERRORS=$((ERRORS+1))
    fi
}

# ── activate the venv if present ────────────────────────────
if [ -f .venv/bin/activate ]; then
    # shellcheck disable=SC1091
    source .venv/bin/activate
fi

# ── 1. python lint (CI: "Lint (ruff)") ──────────────────────
if changed_matches '\.py$|ruff\.toml'; then
    if command -v ruff >/dev/null 2>&1; then
        if $FIX; then ruff check --fix . >/dev/null 2>&1 || true; fi
        run_check "ruff" ruff check .
    else
        echo -e "\n${YELLOW}!${NC} ruff not installed (pip install -r requirements-dev.txt)"
        WARNINGS=$((WARNINGS+1))
    fi
fi

# ── 2. unit tests (CI: "Test (pytest)") ─────────────────────
if changed_matches '\.py$|pytest\.ini|requirements.*\.txt'; then
    if python3 -m pytest --version >/dev/null 2>&1; then
        run_check "pytest" python3 -m pytest -q
    else
        echo -e "\n${YELLOW}!${NC} pytest not installed (pip install -r requirements-dev.txt)"
        WARNINGS=$((WARNINGS+1))
    fi
fi

# ── 3. workflows (CI: "Workflows (actionlint)") ─────────────
# actionlint silently SKIPS its shell checks when shellcheck is missing - that is
# exactly how a broken `run:` block once reached CI green-lit locally.
if changed_matches '^\.github/workflows/'; then
    AL=""
    command -v actionlint >/dev/null 2>&1 && AL="actionlint"
    [ -z "$AL" ] && [ -x ./actionlint ] && AL="./actionlint"
    if [ -n "$AL" ]; then
        command -v shellcheck >/dev/null 2>&1 || {
            echo -e "\n${YELLOW}!${NC} shellcheck missing - actionlint will SKIP shell checks (CI won't)"
            WARNINGS=$((WARNINGS+1))
        }
        # actionlint takes files, not a directory
        run_check "actionlint" "$AL" .github/workflows/*.yml
    else
        echo -e "\n${YELLOW}!${NC} actionlint not installed - workflow changes unverified"
        WARNINGS=$((WARNINGS+1))
    fi
fi

# ── 4. shell scripts ────────────────────────────────────────
if changed_matches '\.sh$'; then
    if command -v shellcheck >/dev/null 2>&1; then
        # SC1091: cannot follow sourced venv. SC2015: the a && b || c echo idiom.
        run_check "shellcheck" shellcheck -e SC1091,SC2015 scripts/*.sh
    fi
fi

# ── 5. rust (CI: "Rust (check + fmt)") ──────────────────────
if changed_matches '^src-tauri/'; then
    if command -v cargo >/dev/null 2>&1; then
        run_check "cargo fmt" cargo fmt --manifest-path src-tauri/Cargo.toml --check

        # tauri bundles ../dist/thinkstack-api as a resource and its build script
        # fails when that path is missing. CI checks against an EMPTY stub, so do
        # the same: a real local PyInstaller build (30k+ files) makes the build
        # script fail with "Not a directory", which CI never sees. Swap the real
        # bundle out for the duration, and restore it on ANY exit so an
        # interrupted run can never lose a multi-GB build.
        STASHED=""
        if [ -d dist/thinkstack-api ] && [ -n "$(ls -A dist/thinkstack-api 2>/dev/null)" ]; then
            STASHED="dist/.thinkstack-api.preflight"
            rm -rf "$STASHED"
            mv dist/thinkstack-api "$STASHED"
        fi
        restore_bundle() {
            if [ -n "${STASHED:-}" ] && [ -d "$STASHED" ]; then
                rm -rf dist/thinkstack-api
                mv "$STASHED" dist/thinkstack-api
            fi
        }
        trap restore_bundle EXIT INT TERM
        mkdir -p dist/thinkstack-api

        run_check "cargo check" cargo check --manifest-path src-tauri/Cargo.toml --quiet

        rmdir dist/thinkstack-api 2>/dev/null || true
        restore_bundle
        trap - EXIT INT TERM
    else
        echo -e "\n${YELLOW}!${NC} cargo not found - rust changes unverified"
        WARNINGS=$((WARNINGS+1))
    fi
fi

# ── 6. frontend (non-blocking: CI does not gate on it) ──────
if [ "$LEVEL" = "full" ] && echo "$CHANGED" | grep -qE '^frontend/'; then
    echo ""
    echo -e "${CYAN}[frontend lint]${NC}"
    if npm --prefix frontend run lint >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} frontend lint passed"
    else
        echo -e "  ${YELLOW}!${NC} frontend lint warnings (non-blocking)"
        WARNINGS=$((WARNINGS+1))
    fi
fi

# ── summary ─────────────────────────────────────────────────
echo ""
echo -e "${CYAN}────────────────────────────────────────────${NC}"
if [ "$ERRORS" -gt 0 ]; then
    echo -e "${RED}  pre-flight FAILED - ${ERRORS} error(s), ${WARNINGS} warning(s)${NC}"
    echo -e "  fix these or CI will fail. bypass once with: ${CYAN}git push --no-verify${NC}"
    echo -e "${CYAN}────────────────────────────────────────────${NC}"
    exit 1
fi
if [ "$WARNINGS" -gt 0 ]; then
    echo -e "${GREEN}  pre-flight passed${NC} ${YELLOW}(${WARNINGS} warning(s))${NC}"
else
    echo -e "${GREEN}  pre-flight passed - CI should be green ✓${NC}"
fi
echo -e "${CYAN}────────────────────────────────────────────${NC}"
