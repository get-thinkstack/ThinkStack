#!/bin/bash
# thinkstack: development server
# starts the fastapi backend and the vite frontend dev server.
# the frontend proxies /api → localhost:8000 automatically.
#
# usage:
#   ./scripts/dev.sh            # web-only (backend + vite)
#   ./scripts/dev.sh --tauri    # web + tauri desktop window
set -e

cd "$(dirname "$0")/.."

# ── colors ──
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}────────────────────────────────────${NC}"
echo -e "${CYAN}  thinkstack: development mode${NC}"
echo -e "${CYAN}────────────────────────────────────${NC}"

# ── ensure cargo is on PATH (may have been installed this session) ──
if [ -f "$HOME/.cargo/env" ]; then
    source "$HOME/.cargo/env"
fi

# ── activate python venv ──
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif command -v python3 &>/dev/null; then
    echo -e "${YELLOW}warning: no .venv found, using system python3${NC}"
else
    echo -e "${RED}error: python3 not found. run ./scripts/setup.sh first.${NC}"
    exit 1
fi

# ── check for port conflicts ──
if command -v lsof &>/dev/null; then
    if lsof -i :8000 -sTCP:LISTEN &>/dev/null; then
        echo -e "${YELLOW}warning: port 8000 is already in use${NC}"
    fi
    if lsof -i :3000 -sTCP:LISTEN &>/dev/null; then
        echo -e "${YELLOW}warning: port 3000 is already in use${NC}"
    fi
fi

# ── start the backend ──
echo -e "${GREEN}starting fastapi backend on port 8000...${NC}"
uvicorn main:app --reload --host 127.0.0.1 --port 8000 &
BACKEND_PID=$!

# ── start the frontend dev server ──
echo -e "${GREEN}starting vite frontend on port 3000...${NC}"
npm --prefix frontend run dev &
FRONTEND_PID=$!

# ── optionally start tauri desktop window ──
TAURI_PID=""
if [ "$1" = "--tauri" ]; then
    echo -e "${GREEN}starting tauri desktop window...${NC}"

    # Move a real frozen backend aside for the duration.
    #
    # tauri.conf.json declares dist/thinkstack-api/ as a bundled resource. In a
    # dev build tauri still walks that tree to emit rerun-if-changed entries,
    # and on a real ~2.6 GB onedir bundle that walk fails with
    # "Not a directory (os error 20)", so `tauri dev` never starts. The desktop
    # window is unusable on exactly the machines that have built the app.
    #
    # Restored on ANY exit, including an interrupt: losing a multi-gigabyte
    # build to a Ctrl-C would be far worse than the problem being worked around.
    DEV_STASH=""
    if [ -d dist/thinkstack-api ] && [ -n "$(ls -A dist/thinkstack-api 2>/dev/null)" ]; then
        DEV_STASH="dist/.thinkstack-api.dev"
        rm -rf "$DEV_STASH"
        mv dist/thinkstack-api "$DEV_STASH"
        mkdir -p dist/thinkstack-api
        echo -e "  ${YELLOW}frozen backend moved aside so tauri dev can start${NC}"
    fi
    restore_dev_bundle() {
        if [ -n "${DEV_STASH:-}" ] && [ -d "$DEV_STASH" ]; then
            rmdir dist/thinkstack-api 2>/dev/null || rm -rf dist/thinkstack-api
            mv "$DEV_STASH" dist/thinkstack-api
            echo -e "  ${GREEN}frozen backend restored${NC}"
        fi
    }
    trap restore_dev_bundle EXIT INT TERM

    # give vite a moment to bind port 3000
    sleep 2
    npm run tauri dev &
    TAURI_PID=$!
fi

echo ""
echo -e "  backend:  ${GREEN}http://localhost:8000/docs${NC}"
echo -e "  frontend: ${GREEN}http://localhost:3000${NC}"
if [ -n "$TAURI_PID" ]; then
    echo -e "  desktop:  ${GREEN}tauri window (pid $TAURI_PID)${NC}"
fi
echo ""
echo -e "  press ${YELLOW}ctrl-c${NC} to stop all processes."
echo -e "${CYAN}────────────────────────────────────${NC}"

cleanup() {
    echo ""
    echo -e "${YELLOW}shutting down...${NC}"
    [ -n "$TAURI_PID" ] && kill $TAURI_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    kill $BACKEND_PID 2>/dev/null
    wait 2>/dev/null
    exit 0
}

trap cleanup SIGINT SIGTERM EXIT
wait
