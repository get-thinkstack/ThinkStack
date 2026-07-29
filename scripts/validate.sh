#!/bin/bash
# thinkstack: pre-push validation
#
# mirrors the CI quality gate (.github/workflows/ci.yml) so a green run here
# means a green run there. the four CI jobs are reproduced below:
#   actionlint (+shellcheck) | ruff | pytest | cargo fmt+check
#
# anything CI checks that this script skips is a trap: it produces a green
# local run and a red CI run. when you add a job to ci.yml, add it here too.
#
# usage: ./scripts/validate.sh [--fix]
set -e

cd "$(dirname "$0")/.."

# ── colors ──
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}────────────────────────────────────${NC}"
echo -e "${CYAN}  thinkstack: validation${NC}"
echo -e "${CYAN}────────────────────────────────────${NC}"

ERRORS=0
FIX_MODE=false
[ "$1" = "--fix" ] && FIX_MODE=true

# ── ensure cargo is on PATH ──
if [ -f "$HOME/.cargo/env" ]; then
    source "$HOME/.cargo/env"
fi

source .venv/bin/activate

# CI freezes and tests with this interpreter. syntax accepted by a newer local
# python (e.g. 3.14 template strings) can be a hard SyntaxError there, so prefer
# the matching version when it is installed.
CI_PYTHON="python3"
if command -v python3.12 &>/dev/null; then
    CI_PYTHON="python3.12"
fi

# ── [1/8] python syntax check (against CI's interpreter) ──
echo ""
echo -e "${CYAN}[1/8] checking python syntax (${CI_PYTHON})...${NC}"
PY_FAIL=0
for f in config.py main.py api/*.py domain/**/*.py infrastructure/*.py; do
    if [ -f "$f" ]; then
        if $CI_PYTHON -m py_compile "$f" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} $f"
        else
            echo -e "  ${RED}✗${NC} $f"
            ERRORS=$((ERRORS+1))
            PY_FAIL=$((PY_FAIL+1))
        fi
    fi
done
[ $PY_FAIL -eq 0 ] && echo -e "  ${GREEN}all python files passed${NC}"
if [ "$CI_PYTHON" = "python3" ]; then
    echo -e "  ${YELLOW}△${NC} python3.12 not installed - CI uses 3.12, so a"
    echo -e "     version-specific syntax error could still slip through"
fi

# ── [2/8] import resolution check ──
echo ""
echo -e "${CYAN}[2/8] checking critical imports...${NC}"
python3 -c "from config import settings" 2>/dev/null \
    && echo -e "  ${GREEN}✓${NC} config.settings" \
    || { echo -e "  ${RED}✗${NC} config.settings"; ERRORS=$((ERRORS+1)); }

python3 -c "from infrastructure.local_vector_store import get_vector_store" 2>/dev/null \
    && echo -e "  ${GREEN}✓${NC} local_vector_store" \
    || { echo -e "  ${RED}✗${NC} local_vector_store"; ERRORS=$((ERRORS+1)); }

python3 -c "from infrastructure.ollama_client import ollama_client" 2>/dev/null \
    && echo -e "  ${GREEN}✓${NC} ollama_client" \
    || { echo -e "  ${RED}✗${NC} ollama_client"; ERRORS=$((ERRORS+1)); }

# ── [3/8] stale reference check ──
echo ""
echo -e "${CYAN}[3/8] checking for stale references...${NC}"
if grep -rn "chromadb_client" --include="*.py" . 2>/dev/null; then
    echo -e "  ${RED}✗${NC} stale chromadb_client references found"
    ERRORS=$((ERRORS+1))
else
    echo -e "  ${GREEN}✓${NC} no stale references"
fi

# ── [4/8] ruff lint (CI job: "Lint (ruff)") ──
echo ""
echo -e "${CYAN}[4/8] ruff lint...${NC}"
if command -v ruff &>/dev/null; then
    if $FIX_MODE; then
        ruff check --fix . && echo -e "  ${GREEN}✓${NC} ruff passed (fixes applied)"
    elif ruff check .; then
        echo -e "  ${GREEN}✓${NC} ruff passed"
    else
        echo -e "  ${RED}✗${NC} ruff failed (CI will fail) - try: ./scripts/validate.sh --fix"
        ERRORS=$((ERRORS+1))
    fi
else
    echo -e "  ${RED}✗${NC} ruff not installed - CI runs it, so this is a blind spot"
    echo -e "     install: pip install -r requirements-dev.txt"
    ERRORS=$((ERRORS+1))
fi

# ── [5/8] unit tests (CI job: "Test (pytest)") ──
echo ""
echo -e "${CYAN}[5/8] unit tests...${NC}"
if python3 -m pytest --version &>/dev/null; then
    if python3 -m pytest -q; then
        echo -e "  ${GREEN}✓${NC} tests passed"
    else
        echo -e "  ${RED}✗${NC} tests failed (CI will fail)"
        ERRORS=$((ERRORS+1))
    fi
else
    echo -e "  ${RED}✗${NC} pytest not installed - CI runs it, so this is a blind spot"
    echo -e "     install: pip install -r requirements-dev.txt"
    ERRORS=$((ERRORS+1))
fi

# ── [6/8] workflow lint (CI job: "Workflows (actionlint)") ──
# actionlint runs its shell checks ONLY when shellcheck is on PATH; without it
# they are silently skipped and a broken `run:` block reaches CI green-lit. that
# exact gap has bitten before, so a missing shellcheck is reported loudly rather
# than passing quietly.
echo ""
echo -e "${CYAN}[6/8] workflow lint (actionlint)...${NC}"
ACTIONLINT=""
if command -v actionlint &>/dev/null; then
    ACTIONLINT="actionlint"
elif [ -x "./actionlint" ]; then
    ACTIONLINT="./actionlint"
fi

if [ -n "$ACTIONLINT" ]; then
    if ! command -v shellcheck &>/dev/null; then
        echo -e "  ${YELLOW}△${NC} shellcheck NOT installed - actionlint will SKIP all"
        echo -e "     shell checks (CI has it and will still catch them)."
        echo -e "     install: sudo dnf install ShellCheck  |  apt install shellcheck"
    fi
    if $ACTIONLINT .github/workflows/*.yml; then
        echo -e "  ${GREEN}✓${NC} workflows passed"
    else
        echo -e "  ${RED}✗${NC} workflow lint failed (CI will fail)"
        ERRORS=$((ERRORS+1))
    fi
else
    echo -e "  ${YELLOW}△${NC} actionlint not installed - CI runs it, so this is a blind spot"
    echo -e "     install: bash <(curl -fsSL https://raw.githubusercontent.com/rhysd/actionlint/main/scripts/download-actionlint.bash)"
fi

# the devops scripts themselves. CI does not lint these (actionlint only reads
# the workflows' inline `run:` blocks), but they share the same failure modes --
# an unquoted expansion here silently breaks a release build.
# SC1091: cannot follow `source .venv/...` (not checked in). SC2015: the
# `a && b || c` echo idiom used throughout, intentional.
if command -v shellcheck &>/dev/null; then
    if shellcheck -e SC1091,SC2015 scripts/*.sh; then
        echo -e "  ${GREEN}✓${NC} scripts/*.sh passed shellcheck"
    else
        echo -e "  ${RED}✗${NC} scripts/*.sh failed shellcheck"
        ERRORS=$((ERRORS+1))
    fi
fi

# ── [7/8] frontend lint ──
echo ""
echo -e "${CYAN}[7/8] frontend lint...${NC}"
if [ -f "frontend/package.json" ]; then
    if npm --prefix frontend run lint 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} frontend lint passed"
    else
        echo -e "  ${YELLOW}△${NC} frontend lint warnings (non-blocking)"
    fi
else
    echo -e "  ${YELLOW}skipped — no frontend/package.json${NC}"
fi

# ── [8/8] rust check (CI job: "Rust (check + fmt)") ──
echo ""
echo -e "${CYAN}[8/8] rust (tauri shell) fmt + check...${NC}"
if [ -f "src-tauri/Cargo.toml" ] && command -v cargo &>/dev/null; then
    # tauri.conf.json bundles ../dist/thinkstack-api/ as a resource and its build
    # script fails when that path is missing. CI stands in an empty dir for the
    # check job; do the same here so a clean tree validates without a 2.6 GB
    # PyInstaller freeze. never touches an existing real bundle.
    mkdir -p dist/thinkstack-api

    if cargo fmt --manifest-path src-tauri/Cargo.toml --check; then
        echo -e "  ${GREEN}✓${NC} rust formatting passed"
    else
        echo -e "  ${RED}✗${NC} rust formatting failed (CI will fail) - fix: cargo fmt --manifest-path src-tauri/Cargo.toml"
        ERRORS=$((ERRORS+1))
    fi

    if cargo check --manifest-path src-tauri/Cargo.toml; then
        echo -e "  ${GREEN}✓${NC} rust check passed"
    else
        echo -e "  ${RED}✗${NC} rust check failed (CI will fail)"
        ERRORS=$((ERRORS+1))
    fi
else
    echo -e "  ${YELLOW}skipped — cargo or src-tauri not found${NC}"
fi

# ── summary ──
echo ""
echo -e "${CYAN}────────────────────────────────────${NC}"
if [ $ERRORS -gt 0 ]; then
    echo -e "${RED}  validation failed — ${ERRORS} error(s)${NC}"
    exit 1
else
    echo -e "${GREEN}  validation passed ✓${NC}"
fi
echo -e "${CYAN}────────────────────────────────────${NC}"
