#!/bin/bash
# thinkstack: fetch the TeX engine we ship, and pre-warm its package cache.
#
# The paper writer needs a TeX engine. Requiring users to install MacTeX or
# MiKTeX made the flagship feature fail on every machine that was not a
# developer's -- that is a missing dependency, not a documentation problem.
#
# Tectonic is a single self-contained binary (~58 MB) that fetches LaTeX
# packages on demand. Fetching at runtime would break the offline promise, so
# this compiles a document using every package the writer's preamble loads and
# ships the resulting cache (~47 MB). A user's first compile then needs no
# network.
#
# Used by BOTH scripts/build.sh and .github/workflows/_build-desktop.yml, so a
# local build and a CI build bundle the same thing. Needs network; everything
# it produces is offline.
#
# usage: scripts/fetch-tex.sh [dest]        (default: data/tex)
set -euo pipefail

cd "$(dirname "$0")/.."

TECTONIC_VERSION="0.17.0"
DEST="${1:-data/tex}"
GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'

# ── which build do we need? ──
OS="$(uname -s)"; ARCH="$(uname -m)"
case "$OS/$ARCH" in
    Linux/x86_64)   TARGET="x86_64-unknown-linux-gnu"; ARCHIVE="tar.gz"; BIN="tectonic" ;;
    Darwin/arm64)   TARGET="aarch64-apple-darwin";     ARCHIVE="tar.gz"; BIN="tectonic" ;;
    Darwin/x86_64)  TARGET="x86_64-apple-darwin";      ARCHIVE="tar.gz"; BIN="tectonic" ;;
    MINGW*|MSYS*|CYGWIN*|*/x86_64)
        # the windows runners report MINGW64_NT-... for uname -s
        if [ "${OS#MINGW}" != "$OS" ] || [ "${OS#MSYS}" != "$OS" ] || [ "${OS#CYGWIN}" != "$OS" ]; then
            TARGET="x86_64-pc-windows-msvc"; ARCHIVE="zip"; BIN="tectonic.exe"
        else
            echo -e "${RED}unsupported platform: $OS/$ARCH${NC}"; exit 1
        fi ;;
    *) echo -e "${RED}unsupported platform: $OS/$ARCH${NC}"; exit 1 ;;
esac

echo -e "${CYAN}────────────────────────────────────${NC}"
echo -e "${CYAN}  TeX engine: tectonic ${TECTONIC_VERSION} (${TARGET})${NC}"
echo -e "${CYAN}────────────────────────────────────${NC}"

mkdir -p "$DEST"

# ── 1. the binary ──
if [ -x "$DEST/$BIN" ]; then
    echo -e "  ${GREEN}already present${NC} $DEST/$BIN"
else
    URL="https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-${TARGET}.${ARCHIVE}"
    echo "  downloading $URL"
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    curl -fsSL --retry 3 --retry-delay 5 -o "$TMP/tectonic.$ARCHIVE" "$URL"
    if [ "$ARCHIVE" = "zip" ]; then
        unzip -q -o "$TMP/tectonic.$ARCHIVE" -d "$TMP"
    else
        tar xzf "$TMP/tectonic.$ARCHIVE" -C "$TMP"
    fi
    # the archive layout has varied between releases; find the binary rather
    # than assuming it sits at the root.
    FOUND="$(find "$TMP" -type f -name "$BIN" | head -1)"
    [ -n "$FOUND" ] || { echo -e "${RED}no $BIN inside the archive${NC}"; exit 1; }
    cp "$FOUND" "$DEST/$BIN"
    chmod +x "$DEST/$BIN"
    echo -e "  ${GREEN}installed${NC} $DEST/$BIN ($(du -h "$DEST/$BIN" | cut -f1))"
fi

# ── 2. warm the package cache ──
# Every package the paper writer's preamble loads. If you add one to
# domain/paper_writer/compiler.py's _PREAMBLE, add it here too -- otherwise the
# first user to trigger it needs a network connection we promised they would
# not need.
CACHE="$DEST/cache"
if [ -d "$CACHE" ] && [ -n "$(ls -A "$CACHE" 2>/dev/null)" ]; then
    echo -e "  ${GREEN}cache already warm${NC} ($(du -sh "$CACHE" | cut -f1))"
else
    echo "  warming the package cache (needs network, one time)..."
    WARM="$(mktemp -d)"
    cat > "$WARM/warm.tex" <<'TEX'
\documentclass[12pt,a4paper]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{tabularx}
\usepackage{array}
\usepackage{multirow}
\usepackage{caption}
\usepackage{float}
\usepackage{geometry}
\usepackage{hyperref}
\usepackage{xcolor}
\usepackage{tikz}
\usepackage{pgfplots}
\pgfplotsset{compat=1.18}
\begin{document}
\section{Warm}\label{sec:warm}
$E=mc^2$\quad$\alpha\beta\gamma$\quad\textcolor{blue}{colour}
\begin{table}[h]\centering
\begin{tabular}{@{}ll@{}}\toprule a & b \\\midrule 1 & 2 \\\bottomrule\end{tabular}
\caption{table}\end{table}
\begin{figure}[h]\centering
\begin{tikzpicture}\draw (0,0)--(1,1);\end{tikzpicture}
\caption{tikz}\end{figure}
\begin{figure}[h]\centering
\begin{tikzpicture}\begin{axis}\addplot {x^2};\end{axis}\end{tikzpicture}
\caption{pgfplots}\end{figure}
\end{document}
TEX
    mkdir -p "$CACHE"
    CACHE_ABS="$(cd "$CACHE" && pwd)"

    # Do NOT hide the engine's output. An earlier version sent it to /dev/null
    # and only printed "warm-up failed", so when this failed in CI the build
    # shipped an installer with an empty cache and the PDF compilation in it
    # simply did not work. The error has to be visible, and the failure has to
    # stop the build.
    # The capture file lives OUTSIDE the compile directory and is not named
    # <jobname>.out. hyperref writes the PDF outline to warm.out for jobname
    # "warm", so capturing stdout there made LaTeX read this log as TeX source
    # and fail with "Missing $ inserted" on a download progress line.
    ENGINE_OUT="$(mktemp)"
    set +e
    TECTONIC_CACHE_DIR="$CACHE_ABS" "$DEST/$BIN" -X compile "$WARM/warm.tex" \
        --outdir "$WARM" > "$ENGINE_OUT" 2>&1
    WARM_RC=$?
    set -e

    if [ "$WARM_RC" -ne 0 ] || [ ! -f "$WARM/warm.pdf" ]; then
        echo -e "${RED}TeX cache warm-up FAILED (exit ${WARM_RC})${NC}"
        echo "  the engine said:"
        sed 's/^/    /' "$ENGINE_OUT" 2>/dev/null | tail -40
        echo ""
        echo -e "${RED}Refusing to continue.${NC} Shipping an installer whose TeX cache is"
        echo "  empty means the paper writer cannot compile a PDF on a user's machine,"
        echo "  which is the entire reason this engine is bundled."
        rm -rf "$WARM" "$ENGINE_OUT"
        exit 1
    fi

    rm -f "$ENGINE_OUT"
    echo -e "  ${GREEN}cache warm${NC} ($(du -sh "$CACHE" | cut -f1)) - compiles offline from here"
    rm -rf "$WARM"
fi

echo -e "  ${GREEN}TeX engine ready in ${DEST}/${NC}"
