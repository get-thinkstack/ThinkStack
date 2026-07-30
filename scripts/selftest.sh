#!/bin/bash
# thinkstack: validate an INSTALLED build. macOS and Linux.
#
# Run this with ThinkStack already open. It checks the things that have actually
# broken in shipped builds -- not the source tree, which CI already covers:
#
#   * the backend is reachable at all
#   * WHICH backend launched (a packaged build must never fall back to a system
#     python; that bug shipped in v1.0.0 and looked like an endless spinner)
#   * the language model resolved to a real file
#   * the embedding model came from inside the bundle, not HuggingFace
#   * pdflatex exists, or the paper writer's PDF tab will fail
#
# It prints a report you can paste into a bug thread. Nothing is uploaded.
#
# usage:  bash selftest.sh            (Windows testers: use selftest.ps1)
set -uo pipefail

API="http://127.0.0.1:8000"
GREEN=$'\033[0;32m'; RED=$'\033[0;31m'; YEL=$'\033[1;33m'; CYA=$'\033[0;36m'; NC=$'\033[0m'
PASS=0; FAIL=0; WARN=0

ok()   { echo "  ${GREEN}PASS${NC}  $1"; PASS=$((PASS+1)); }
bad()  { echo "  ${RED}FAIL${NC}  $1"; FAIL=$((FAIL+1)); }
warn() { echo "  ${YEL}WARN${NC}  $1"; WARN=$((WARN+1)); }
info() { echo "        $1"; }

# jq is not installed on a typical tester's machine; python3 is on macOS by
# default and on every Linux we target. Fall back to grep if neither exists.
jget() {  # jget <json> <python-expression-on-d>
    python3 -c "
import json,sys
try:
    d=json.loads(sys.argv[1])
    print($2)
except Exception:
    print('')
" "$1" 2>/dev/null || echo ""
}

case "$(uname -s)" in
    Darwin) OSNAME="macOS $(sw_vers -productVersion 2>/dev/null)"; LOGDIR="$HOME/Library/Logs/com.thinkstack.app" ;;
    Linux)  OSNAME="Linux $(uname -r)"; LOGDIR="${XDG_DATA_HOME:-$HOME/.local/share}/com.thinkstack.app/logs" ;;
    *)      OSNAME="$(uname -s)"; LOGDIR="" ;;
esac

echo "${CYA}────────────────────────────────────────────${NC}"
echo "${CYA}  ThinkStack self-test${NC}"
echo "  $OSNAME  |  $(uname -m)"
echo "${CYA}────────────────────────────────────────────${NC}"
echo ""

# ── 1. is the app running? ──
echo "${CYA}[1] backend${NC}"
HEALTH="$(curl -fsS -m 10 "$API/api/system/health" 2>/dev/null)"
if [ -z "$HEALTH" ]; then
    bad "no backend on 127.0.0.1:8000"
    info "Start ThinkStack first, wait for the window, then re-run this."
    info "If it never finishes starting, the loading screen shows a log path --"
    info "send that file."
    echo ""
    echo "  ${RED}Cannot continue without a running app.${NC}"
    exit 1
fi
ok "backend reachable"

# ── 2. which backend launched? ──
echo ""
echo "${CYA}[2] startup${NC}"
LOG="$LOGDIR/backend.log"
if [ -f "$LOG" ]; then
    ok "startup log: $LOG"
    SPAWN="$(grep -m1 'spawn: Backend:' "$LOG" 2>/dev/null | sed 's/.*spawn: //')"
    if [ -n "$SPAWN" ]; then
        info "$SPAWN"
        ok "launched the bundled backend"
    elif grep -q 'falling back to a system python' "$LOG" 2>/dev/null; then
        bad "fell back to a SYSTEM PYTHON -- the bundled backend was not found"
        info "This is the v1.0.0 bug on a new platform. Send the log."
    else
        warn "could not tell which backend launched (older build?)"
    fi
    READY="$(grep -m1 'ready: Engine ready' "$LOG" 2>/dev/null | grep -o '^\[ *[0-9]*ms\]')"
    [ -n "$READY" ] && info "ready at $READY"
else
    warn "no startup log at $LOG"
    info "Expected on builds older than v1.0.1."
fi

# ── 3. hardware diagnosis ──
echo ""
echo "${CYA}[3] hardware diagnosis${NC}"
TIER="$(jget "$HEALTH" "d['hardware']['tier']")"
RAM="$(jget "$HEALTH" "d['hardware']['total_ram_gb']")"
GPU="$(jget "$HEALTH" "d['hardware']['gpu']")"
if [ -n "$TIER" ] && [ "$RAM" != "0" ] && [ -n "$RAM" ]; then
    ok "detected: ${RAM} GB RAM, tier '${TIER}', gpu '${GPU}'"
    info "GPU is reported but NOT used: the shipped llama.cpp is CPU-only, so"
    info "Metal/AMD offload would crash at model load. CPU is expected here."
else
    bad "hardware not detected (tier='$TIER' ram='$RAM')"
fi

# ── 4. language model ──
echo ""
echo "${CYA}[4] language model${NC}"
LSTAT="$(jget "$HEALTH" "d['llm']['status']")"
LAVAIL="$(jget "$HEALTH" "d['llm']['target_available']")"
LPATH="$(jget "$HEALTH" "d['llm']['model_path']")"
LCOUNT="$(jget "$HEALTH" "d['llm']['models_available']")"
if [ "$LSTAT" = "connected" ] && [ "$LAVAIL" = "True" ]; then
    ok "model resolved ($LCOUNT available)"
    info "$LPATH"
else
    bad "model NOT resolved (status='$LSTAT', available='$LAVAIL')"
    info "path it looked at: $LPATH"
    info "If that path looks relative or wrong, this is the model-path bug."
fi

# ── 5. embedding model (must be local) ──
echo ""
echo "${CYA}[5] embedding model${NC}"
if [ -f "$LOG" ] && grep -q 'loading embedding model' "$LOG" 2>/dev/null; then
    ESRC="$(grep -m1 'loading embedding model' "$LOG" | sed 's/.*loading embedding model: //')"
    case "$ESRC" in
        /*|[A-Za-z]:*) ok "loaded from a real path (bundled)"; info "$ESRC" ;;
        *)             bad "resolved to a BARE NAME -- it will try HuggingFace"; info "$ESRC" ;;
    esac
else
    warn "not loaded yet -- ingest one PDF, then re-run this"
    info "That is the only action that exercises the embedding model."
fi

# ── 6. pdflatex (paper writer PDF tab) ──
echo ""
echo "${CYA}[6] paper writer${NC}"
if command -v pdflatex >/dev/null 2>&1; then
    ok "pdflatex found: $(command -v pdflatex)"
else
    warn "pdflatex NOT installed -- the live preview works, the PDF tab will not"
    case "$(uname -s)" in
        Darwin) info "install: brew install --cask mactex-no-gui" ;;
        Linux)  info "install: sudo dnf install texlive-scheme-basic   (fedora)" ;
                info "         sudo apt install texlive-latex-recommended  (debian/ubuntu)" ;;
    esac
    info "ThinkStack does not bundle a TeX engine yet (roadmap: Tectonic)."
fi

# ── 7. model setup / consent ──
echo ""
echo "${CYA}[7] model setup${NC}"
SETUP="$(curl -fsS -m 10 "$API/api/models/setup" 2>/dev/null)"
if [ -n "$SETUP" ]; then
    NEEDS="$(jget "$SETUP" "d['needs_permission']")"
    SUGG="$(jget "$SETUP" "(d.get('suggested_upgrade') or {}).get('name','none')")"
    ok "reachable (needs_permission=$NEEDS, suggests=$SUGG)"
else
    bad "/api/models/setup did not respond"
fi

# ── summary ──
echo ""
echo "${CYA}────────────────────────────────────────────${NC}"
if [ "$FAIL" -eq 0 ]; then
    echo "  ${GREEN}${PASS} passed${NC}, ${WARN} warning(s), 0 failed"
    echo "  This build works on $OSNAME."
else
    echo "  ${RED}${FAIL} FAILED${NC}, ${WARN} warning(s), ${PASS} passed"
    echo "  Paste this output and $LOG into the bug thread."
fi
echo "${CYA}────────────────────────────────────────────${NC}"
[ "$FAIL" -eq 0 ]
