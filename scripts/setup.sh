#!/bin/bash
# thinkstack: full environment bootstrap
# installs all system dependencies, language toolchains, and project packages.
# a new developer clones the repo, runs this once, and is ready to build.
#
# usage: ./scripts/setup.sh [--skip-system] [--skip-rust]
set -e

cd "$(dirname "$0")/.."

# ── colors ──
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${CYAN}────────────────────────────────────${NC}"
echo -e "${CYAN}  thinkstack: setup${NC}"
echo -e "${CYAN}────────────────────────────────────${NC}"

# ── parse flags ──
SKIP_SYSTEM=false
SKIP_RUST=false
for arg in "$@"; do
    case "$arg" in
        --skip-system) SKIP_SYSTEM=true ;;
        --skip-rust)   SKIP_RUST=true ;;
    esac
done

# ── detect package manager ──
if command -v dnf &>/dev/null; then
    PKG_MGR="dnf"
elif command -v apt-get &>/dev/null; then
    PKG_MGR="apt-get"
elif command -v pacman &>/dev/null; then
    PKG_MGR="pacman"
elif command -v brew &>/dev/null; then
    PKG_MGR="brew"
else
    echo -e "${YELLOW}warning: unsupported package manager. install system deps manually.${NC}"
    PKG_MGR="none"
fi
echo -e "  detected package manager: ${GREEN}${PKG_MGR}${NC}"

# ── [1/6] system dependencies for tauri ──
echo ""
echo -e "${CYAN}[1/6] system dependencies (tauri prerequisites)${NC}"
if [ "$SKIP_SYSTEM" = true ]; then
    echo -e "  ${YELLOW}skipped (--skip-system)${NC}"
else
    case "$PKG_MGR" in
        dnf)
            sudo dnf install -y \
                webkit2gtk4.1-devel \
                openssl-devel \
                curl \
                wget \
                file \
                libappindicator-gtk3-devel \
                librsvg2-devel \
                pango-devel \
                gcc \
                gcc-c++ \
                make \
                2>/dev/null || echo -e "  ${YELLOW}some packages may already be installed${NC}"
            ;;
        apt-get)
            sudo apt-get update -qq
            sudo apt-get install -y \
                libwebkit2gtk-4.1-dev \
                libssl-dev \
                curl \
                wget \
                file \
                libayatana-appindicator3-dev \
                librsvg2-dev \
                libpango1.0-dev \
                build-essential \
                2>/dev/null || echo -e "  ${YELLOW}some packages may already be installed${NC}"
            ;;
        pacman)
            sudo pacman -S --needed --noconfirm \
                webkit2gtk-4.1 \
                openssl \
                curl \
                wget \
                file \
                libappindicator-gtk3 \
                librsvg \
                pango \
                base-devel \
                2>/dev/null || echo -e "  ${YELLOW}some packages may already be installed${NC}"
            ;;
        brew)
            # macOS — xcode command line tools provide most build deps
            xcode-select --install 2>/dev/null || true
            echo -e "  ${GREEN}macOS: xcode CLT provides build essentials${NC}"
            ;;
        none)
            echo -e "  ${YELLOW}skipped — install manually${NC}"
            ;;
    esac
    echo -e "  ${GREEN}system dependencies installed${NC}"
fi

# ── [2/6] rust toolchain ──
echo ""
echo -e "${CYAN}[2/6] rust toolchain${NC}"
if [ "$SKIP_RUST" = true ]; then
    echo -e "  ${YELLOW}skipped (--skip-rust)${NC}"
elif command -v rustc &>/dev/null; then
    echo -e "  ${GREEN}rust already installed: $(rustc --version)${NC}"
else
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    source "$HOME/.cargo/env"
    echo -e "  ${GREEN}rust installed: $(rustc --version)${NC}"
fi
# always ensure cargo is on PATH for subsequent steps
if [ -f "$HOME/.cargo/env" ]; then
    source "$HOME/.cargo/env"
fi

# ── [3/6] python virtual environment ──
echo ""
echo -e "${CYAN}[3/6] python virtual environment${NC}"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo -e "  ${GREEN}created .venv${NC}"
else
    echo -e "  ${GREEN}.venv already exists${NC}"
fi
source .venv/bin/activate
export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
pip install --quiet pyinstaller
echo -e "  ${GREEN}python dependencies installed${NC}"

# ── [4/6] node / frontend dependencies ──
echo ""
echo -e "${CYAN}[4/6] frontend dependencies${NC}"
if [ -f "package.json" ]; then
    echo -e "  installing root node modules (tauri cli)..."
    npm install --silent
else
    echo -e "  ${YELLOW}no root package.json found, skipping${NC}"
fi

if [ -f "frontend/package.json" ]; then
    echo -e "  installing frontend node modules..."
    npm --prefix frontend install --silent
    echo -e "  ${GREEN}frontend node modules installed${NC}"
else
    echo -e "  ${YELLOW}no frontend/package.json found, skipping${NC}"
fi

# ── [5/6] latex compiler ──
echo ""
echo -e "${CYAN}[5/6] latex compiler${NC}"
if command -v pdflatex &>/dev/null; then
    echo -e "  ${GREEN}pdflatex already installed${NC}"
elif command -v tectonic &>/dev/null; then
    echo -e "  ${GREEN}tectonic already installed: $(tectonic --version)${NC}"
else
    case "$PKG_MGR" in
        dnf)
            sudo dnf install -y texlive-scheme-basic texlive-collection-latexrecommended \
                2>/dev/null || echo -e "  ${YELLOW}install texlive manually${NC}"
            ;;
        apt-get)
            sudo apt-get install -y texlive-latex-recommended \
                2>/dev/null || echo -e "  ${YELLOW}install texlive manually${NC}"
            ;;
        pacman)
            sudo pacman -S --needed --noconfirm texlive-basic texlive-latexrecommended \
                2>/dev/null || echo -e "  ${YELLOW}install texlive manually${NC}"
            ;;
        brew)
            brew install --cask mactex-no-gui 2>/dev/null || echo -e "  ${YELLOW}install MacTeX manually: https://tug.org/mactex/${NC}"
            ;;
        *)
            echo -e "  ${YELLOW}install a latex distribution manually${NC}"
            ;;
    esac
fi

# ── [6/6] verify installation ──
echo ""
echo -e "${CYAN}[6/6] verifying installation${NC}"
ERRORS=0

command -v python3 &>/dev/null && echo -e "  ${GREEN}✓${NC} python3" || { echo -e "  ${RED}✗${NC} python3"; ERRORS=$((ERRORS+1)); }
command -v node &>/dev/null    && echo -e "  ${GREEN}✓${NC} node $(node --version)" || { echo -e "  ${RED}✗${NC} node"; ERRORS=$((ERRORS+1)); }
command -v npm &>/dev/null     && echo -e "  ${GREEN}✓${NC} npm $(npm --version)" || { echo -e "  ${RED}✗${NC} npm"; ERRORS=$((ERRORS+1)); }
command -v rustc &>/dev/null   && echo -e "  ${GREEN}✓${NC} rustc $(rustc --version 2>/dev/null | awk '{print $2}')" || { echo -e "  ${RED}✗${NC} rustc"; ERRORS=$((ERRORS+1)); }
command -v cargo &>/dev/null   && echo -e "  ${GREEN}✓${NC} cargo" || { echo -e "  ${RED}✗${NC} cargo"; ERRORS=$((ERRORS+1)); }
(command -v pdflatex &>/dev/null || command -v tectonic &>/dev/null) && echo -e "  ${GREEN}✓${NC} latex compiler" || echo -e "  ${YELLOW}△${NC} latex compiler (optional)"

echo ""
echo -e "${CYAN}────────────────────────────────────${NC}"
if [ $ERRORS -gt 0 ]; then
    echo -e "${YELLOW}  setup complete with ${ERRORS} missing tool(s).${NC}"
else
    echo -e "${GREEN}  setup complete.${NC}"
fi
echo ""
echo -e "  ${CYAN}development:${NC}  ./scripts/dev.sh"
echo -e "  ${CYAN}desktop dev:${NC}  ./scripts/dev.sh --tauri"
echo -e "  ${CYAN}validation:${NC}   ./scripts/validate.sh"
echo -e "  ${CYAN}production:${NC}   ./scripts/build.sh"
echo -e "${CYAN}────────────────────────────────────${NC}"
