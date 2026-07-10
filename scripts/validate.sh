#!/bin/bash
# thinkstack: pre-commit validation
# checks python, frontend, and rust for issues before pushing.
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

# ── [1/5] python syntax check ──
echo ""
echo -e "${CYAN}[1/5] checking python syntax...${NC}"
PY_FAIL=0
for f in config.py main.py api/*.py domain/**/*.py infrastructure/*.py; do
    if [ -f "$f" ]; then
        if python3 -m py_compile "$f" 2>/dev/null; then
            echo -e "  ${GREEN}✓${NC} $f"
        else
            echo -e "  ${RED}✗${NC} $f"
            ERRORS=$((ERRORS+1))
            PY_FAIL=$((PY_FAIL+1))
        fi
    fi
done
[ $PY_FAIL -eq 0 ] && echo -e "  ${GREEN}all python files passed${NC}"

# ── [2/5] import resolution check ──
echo ""
echo -e "${CYAN}[2/5] checking critical imports...${NC}"
python3 -c "from config import settings" 2>/dev/null \
    && echo -e "  ${GREEN}✓${NC} config.settings" \
    || { echo -e "  ${RED}✗${NC} config.settings"; ERRORS=$((ERRORS+1)); }

python3 -c "from infrastructure.local_vector_store import get_vector_store" 2>/dev/null \
    && echo -e "  ${GREEN}✓${NC} local_vector_store" \
    || { echo -e "  ${RED}✗${NC} local_vector_store"; ERRORS=$((ERRORS+1)); }

python3 -c "from infrastructure.ollama_client import ollama_client" 2>/dev/null \
    && echo -e "  ${GREEN}✓${NC} ollama_client" \
    || { echo -e "  ${RED}✗${NC} ollama_client"; ERRORS=$((ERRORS+1)); }

# ── [3/5] stale reference check ──
echo ""
echo -e "${CYAN}[3/5] checking for stale references...${NC}"
if grep -rn "chromadb_client" --include="*.py" . 2>/dev/null; then
    echo -e "  ${RED}✗${NC} stale chromadb_client references found"
    ERRORS=$((ERRORS+1))
else
    echo -e "  ${GREEN}✓${NC} no stale references"
fi

# ── [4/5] frontend lint ──
echo ""
echo -e "${CYAN}[4/5] frontend lint...${NC}"
if [ -f "frontend/package.json" ]; then
    if npm --prefix frontend run lint 2>/dev/null; then
        echo -e "  ${GREEN}✓${NC} frontend lint passed"
    else
        echo -e "  ${YELLOW}△${NC} frontend lint warnings (non-blocking)"
    fi
else
    echo -e "  ${YELLOW}skipped — no frontend/package.json${NC}"
fi

# ── [5/5] rust check ──
echo ""
echo -e "${CYAN}[5/5] rust (tauri shell) check...${NC}"
if [ -f "src-tauri/Cargo.toml" ] && command -v cargo &>/dev/null; then
    if cargo check --manifest-path src-tauri/Cargo.toml 2>&1 | tail -5; then
        echo -e "  ${GREEN}✓${NC} rust check passed"
    else
        echo -e "  ${RED}✗${NC} rust check failed"
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
