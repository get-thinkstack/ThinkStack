#!/bin/bash
# thinkstack: production build pipeline
# freezes the python backend with pyinstaller, builds the react frontend,
# places the sidecar binary, and compiles the tauri desktop application.
#
# usage: ./scripts/build.sh [--skip-pyinstaller] [--skip-tauri]
set -e

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

# ── colors ──
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}────────────────────────────────────${NC}"
echo -e "${CYAN}  thinkstack: production build${NC}"
echo -e "${CYAN}────────────────────────────────────${NC}"

# ── parse flags ──
SKIP_PYINSTALLER=false
SKIP_TAURI=false
for arg in "$@"; do
    case "$arg" in
        --skip-pyinstaller) SKIP_PYINSTALLER=true ;;
        --skip-tauri)       SKIP_TAURI=true ;;
    esac
done

# ── ensure cargo is on PATH ──
if [ -f "$HOME/.cargo/env" ]; then
    source "$HOME/.cargo/env"
fi

# ── detect target triple ──
ARCH=$(uname -m)
OS=$(uname -s)
case "$OS" in
    Linux)  TRIPLE="${ARCH}-unknown-linux-gnu" ;;
    Darwin) TRIPLE="${ARCH}-apple-darwin" ;;
    *)      TRIPLE="${ARCH}-pc-windows-msvc" ;;
esac
echo -e "  target triple: ${GREEN}${TRIPLE}${NC}"

# ── step 1: build the react frontend ──
echo ""
echo -e "${CYAN}[1/4] building react frontend...${NC}"
if [ -f "frontend/package.json" ]; then
    npm --prefix frontend run build
    echo -e "  ${GREEN}frontend built to frontend/dist/${NC}"
else
    echo -e "  ${RED}error: frontend/package.json not found${NC}"
    exit 1
fi

# ── step 2: freeze python backend ──
echo ""
echo -e "${CYAN}[2/4] freezing python backend with pyinstaller...${NC}"
if [ "$SKIP_PYINSTALLER" = true ]; then
    echo -e "  ${YELLOW}skipped (--skip-pyinstaller)${NC}"
else
    source .venv/bin/activate
    export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1

    # verify at least one gguf model exists for bundling
    MODEL_COUNT=$(find data/models -name "*.gguf" 2>/dev/null | wc -l)
    if [ "$MODEL_COUNT" -eq 0 ]; then
        echo -e "  ${YELLOW}warning: no gguf model found in data/models/${NC}"
        echo -e "  ${YELLOW}the bundled app will require a model to be placed manually${NC}"
    else
        echo -e "  ${GREEN}found ${MODEL_COUNT} gguf model(s) to bundle${NC}"
    fi

    # build add-data flags
    ADD_DATA_FLAGS="--add-data frontend/dist:frontend/dist"
    if [ "$MODEL_COUNT" -gt 0 ]; then
        ADD_DATA_FLAGS="$ADD_DATA_FLAGS --add-data data/models:data/models"
    fi

    # --onedir (NOT --onefile): the backend is shipped as a Tauri *resource*
    # dir (tauri.conf.json bundle.resources -> "api/"), which lib.rs launches.
    # a onefile build would re-extract its multi-GB payload to a temp dir on
    # every launch; onedir unpacks once at install.
    # --collect-all llama_cpp / sentence_transformers are REQUIRED (neither has a
    # PyInstaller hook): without them the frozen build omits llama_cpp's lib/*.so
    # and sentence_transformers' data, breaking chat/gap-analysis and search.
    pyinstaller --name thinkstack-api --onedir --clean --noconfirm \
        --hidden-import uvicorn \
        --hidden-import uvicorn.logging \
        --hidden-import uvicorn.loops \
        --hidden-import uvicorn.loops.auto \
        --hidden-import uvicorn.protocols \
        --hidden-import uvicorn.protocols.http \
        --hidden-import uvicorn.protocols.http.auto \
        --hidden-import uvicorn.protocols.websockets \
        --hidden-import uvicorn.protocols.websockets.auto \
        --hidden-import uvicorn.lifespan \
        --hidden-import uvicorn.lifespan.on \
        --hidden-import psutil \
        --collect-all llama_cpp \
        --collect-all sentence_transformers \
        $ADD_DATA_FLAGS \
        main.py

    echo -e "  ${GREEN}backend frozen to dist/thinkstack-api/ (onedir)${NC}"
fi

# ── step 3: verify the onedir backend for tauri to bundle ──
# no sidecar copy needed: tauri.conf.json bundles dist/thinkstack-api/ directly
# as the "api/" resource. this step just sanity-checks the build.
echo ""
echo -e "${CYAN}[3/4] verifying onedir backend...${NC}"
if [ -x "dist/thinkstack-api/thinkstack-api" ] || [ -x "dist/thinkstack-api/thinkstack-api.exe" ]; then
    echo -e "  ${GREEN}backend dir ready: dist/thinkstack-api/ (tauri bundles it as api/)${NC}"
elif [ "$SKIP_PYINSTALLER" = true ]; then
    echo -e "  ${YELLOW}skipped pyinstaller — expecting an existing dist/thinkstack-api/${NC}"
else
    echo -e "  ${RED}error: dist/thinkstack-api/thinkstack-api not found after freeze${NC}"
    exit 1
fi

# ── step 4: compile tauri desktop app ──
echo ""
echo -e "${CYAN}[4/4] compiling tauri desktop application...${NC}"
if [ "$SKIP_TAURI" = true ]; then
    echo -e "  ${YELLOW}skipped (--skip-tauri)${NC}"
elif [ ! -d "src-tauri" ] || [ ! -f "src-tauri/tauri.conf.json" ]; then
    echo -e "  ${YELLOW}tauri not scaffolded — skipping${NC}"
    echo -e "  frozen backend available at: dist/thinkstack-api"
elif ! command -v cargo &>/dev/null; then
    echo -e "  ${RED}error: cargo not found. run: source \"\$HOME/.cargo/env\"${NC}"
    exit 1
else
    npm run tauri build
    echo -e "  ${GREEN}desktop binary compiled${NC}"
fi

# ── summary ──
echo ""
echo -e "${CYAN}────────────────────────────────────${NC}"
echo -e "${GREEN}  build complete.${NC}"
echo ""
echo -e "  artifacts:"
[ -d "dist/thinkstack-api" ] && echo -e "    frozen backend: ${GREEN}dist/thinkstack-api/ (onedir)${NC}"
if [ -d "src-tauri/target/release/bundle" ]; then
    echo -e "    desktop app:    ${GREEN}src-tauri/target/release/bundle/${NC}"
fi
echo -e "${CYAN}────────────────────────────────────${NC}"
