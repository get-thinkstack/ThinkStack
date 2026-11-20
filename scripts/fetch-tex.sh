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

# 0.15.0, not the newest. The 0.17.0 Linux build requires GLIBC_2.39, which
# is newer than Ubuntu 22.04 (2.35) and newer than a great many user machines:
# it failed to load at all on the CI runner, taking 15ms to not run, which is
# what left the shipped engine without a package cache. 0.15.0 needs only
# GLIBC_2.35 and links no OpenSSL 1.1 (which 0.14.1 does, and which modern
# distributions no longer ship). It supports every flag used here and produces
# a cache half the size.
#
# Before bumping this, check: objdump -T tectonic | grep -o "GLIBC_[0-9.]*" | sort -uV | tail -1
TECTONIC_VERSION="0.15.0"
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
# What the starter templates load must be in a warm document below, or the
# first user to compile one needs a network we promised they would not.
# tests/test_fetch_tex.py compares the two lists.
CACHE="$DEST/cache"

# Written only after a compile has actually produced a PDF, and checked instead
# of "is the directory non-empty".
#
# A throttled run leaves the packages it managed to fetch behind, so a partial
# cache is not an empty one. Treating non-empty as warm meant a second build on
# the same machine skipped warming and bundled a cache missing everything after
# the file that was throttled -- the failure would then surface on a user's
# machine, on their first compile, with no network to recover from.
STAMP="$DEST/.cache-warmed"

# How hard to try before giving up. The packages come from one CDN, and the
# three platform builds in CI hit it within seconds of each other; on
# 2026-08-14 Linux warmed at 18:53:42, macOS started at 18:53:52 and was
# answered 429 Too Many Requests until hyperref gave up. Nothing about that was
# macOS: it lost a race the matrix creates on every run.
#
# The engine retries an individual file a few times and then stops, so the
# retry has to be here, around the whole compile. The cache is deliberately NOT
# cleared between attempts -- whatever arrived is still good, so each attempt
# asks for less than the one before.
WARM_ATTEMPTS="${TEX_WARM_ATTEMPTS:-4}"
WARM_RETRY_DELAY="${TEX_WARM_RETRY_DELAY:-15}"

# The stamp records WHICH warm documents proved the cache: a checksum of this
# script, which contains them. A cache proved by an older version of them is
# warmed again rather than trusted.
WARM_KEY="warm-docs $(cksum < "$0" | cut -d' ' -f1-2)"

if [ -f "$STAMP" ] && grep -qF "$WARM_KEY" "$STAMP" 2>/dev/null \
   && [ -d "$CACHE" ] && [ -n "$(ls -A "$CACHE" 2>/dev/null)" ]; then
    echo -e "  ${GREEN}cache already warm${NC} ($(du -sh "$CACHE" | cut -f1))"
else
    if [ -d "$CACHE" ] && [ -n "$(ls -A "$CACHE" 2>/dev/null)" ]; then
        echo "  cache is present but was never proved -- warming it again"
    fi
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
\usetikzlibrary{arrows.meta, positioning, shapes.geometric}
\newcommand\warmshapes{\rmfamily a\textbf{a}\textit{a}\textsl{a}\textsc{a}\textbf{\textit{a}}%
 \sffamily a\textbf{a}\textit{a}\ttfamily a\textbf{a}\textit{a}\rmfamily $x^2_i\sum\alpha$}
\begin{document}
% Tectonic caches one font file per size and shape, and only those a warm
% document typesets. Every standard size, every family and shape, with maths.
\foreach \s in {5,6,7,8,9,10,10.95,12,14.4,17.28,20.74,24.88}{%
  {\fontsize{\s}{\s}\selectfont\warmshapes}\par}
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
    # The Slides starter. A class cannot share a document with article.
    cat > "$WARM/warm-beamer.tex" <<'TEX'
\documentclass{beamer}
\usepackage[utf8]{inputenc}
\begin{document}
\begin{frame}{Warm}\begin{itemize}\item one\end{itemize}\end{frame}
\end{document}
TEX
    # LaTeX's default size is 10pt (size10.clo), and every warm document above
    # is 12pt or Beamer, so a plain \documentclass{article} failed offline.
    # One small document per class and base size, plus the index package.
    # Without fontenc, XeTeX-based Tectonic uses the OpenType Latin Modern
    # files: one per shape and design size. Each document below typesets
    # all of them, so a plain document's \emph or \textbf is cached too.
    cat > "$WARM/warm-fonts.tex" <<'TEX'
\newcommand\warmshapes{\rmfamily a\textbf{a}\textit{a}\textsl{a}\textsc{a}\textbf{\textit{a}}%
 \sffamily a\textbf{a}\textit{a}\ttfamily a\textbf{a}\textit{a}\rmfamily $x^2_i\sum\alpha$}
\foreach \s in {5,6,7,8,9,10,10.95,12,14.4,17.28,20.74,24.88}{%
  {\fontsize{\s}{\s}\selectfont\warmshapes}\par}
TEX
    cat > "$WARM/warm-10.tex" <<'TEX'
\documentclass{article}
\usepackage{graphicx}
\usepackage{pgffor}
\usepackage{imakeidx}
\usepackage{hyperref}
\makeindex
\begin{document}
\input{warm-fonts}
\section{Warm}x\index{x}\index{x!y}\newpage z\index{z}
\printindex
\end{document}
TEX
    cat > "$WARM/warm-11.tex" <<'TEX'
\documentclass[11pt]{article}
\usepackage{pgffor}
\begin{document}
\input{warm-fonts}
\section{Warm}x
\end{document}
TEX
    cat > "$WARM/warm-report.tex" <<'TEX'
\documentclass{report}
\usepackage{pgffor}
\begin{document}
\input{warm-fonts}
\chapter{Warm}x
\end{document}
TEX
    cat > "$WARM/warm-book.tex" <<'TEX'
\documentclass{book}
\usepackage{pgffor}
\begin{document}
\input{warm-fonts}
\chapter{Warm}x
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
    # Every document here is compiled; tests/test_fetch_tex.py fails if a
    # starter template (domain/paper_writer/templates.py) loads anything that
    # none of them do.
    ENGINE_OUT="$(mktemp)"
    for DOC in warm warm-beamer warm-10 warm-11 warm-report warm-book; do
    attempt=1
    while : ; do
        set +e
        TECTONIC_CACHE_DIR="$CACHE_ABS" "$DEST/$BIN" -X compile "$WARM/$DOC.tex" \
            --outdir "$WARM" > "$ENGINE_OUT" 2>&1
        WARM_RC=$?
        set -e

        [ "$WARM_RC" -eq 0 ] && [ -f "$WARM/$DOC.pdf" ] && break

        if [ "$attempt" -ge "$WARM_ATTEMPTS" ]; then
            echo -e "${RED}TeX cache warm-up FAILED (exit ${WARM_RC}) after ${attempt} attempts${NC}"
            echo "  the engine said:"
            sed 's/^/    /' "$ENGINE_OUT" 2>/dev/null | tail -40
            echo ""
            echo -e "${RED}Refusing to continue.${NC} Shipping an installer whose TeX cache is"
            echo "  empty means the paper writer cannot compile a PDF on a user's machine,"
            echo "  which is the entire reason this engine is bundled."
            rm -rf "$WARM" "$ENGINE_OUT"
            exit 1
        fi

        # Say what happened at the time it happens. A silent retry that later
        # succeeds hides a CDN that is throttling us, and the next person to
        # see this fail has no idea it had been happening for weeks.
        echo -e "  ${CYAN}attempt ${attempt} failed${NC} - $(grep -c '429 Too Many Requests' "$ENGINE_OUT" 2>/dev/null || echo 0) throttled request(s); retrying in ${WARM_RETRY_DELAY}s"
        [ "$WARM_RETRY_DELAY" -gt 0 ] && sleep "$WARM_RETRY_DELAY"
        # back off further each time; a rate limit that is still on does not
        # care how eager we are
        WARM_RETRY_DELAY=$((WARM_RETRY_DELAY * 2))
        attempt=$((attempt + 1))
    done
    done

    rm -f "$ENGINE_OUT"
    # only now is the cache known to be complete enough to compile the preamble
    echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $WARM_KEY" > "$STAMP"
    echo -e "  ${GREEN}cache warm${NC} ($(du -sh "$CACHE" | cut -f1)) - compiles offline from here"
    rm -rf "$WARM"
fi

echo -e "  ${GREEN}TeX engine ready in ${DEST}/${NC}"
