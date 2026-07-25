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
