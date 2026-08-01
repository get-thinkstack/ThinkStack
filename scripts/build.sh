#!/bin/bash
# thinkstack: production build pipeline
# freezes the python backend with pyinstaller, builds the react frontend,
# places the sidecar binary, and compiles the tauri desktop application.
#
# usage: ./scripts/build.sh [--skip-pyinstaller] [--skip-tauri] [--fetch-embeddings]
#
# Always builds from the current tree: previous outputs are cleared first, and
# the finished installers are copied into local/, replacing whatever was there.
# local/ is what you install and validate before running scripts/promote.sh.
set -e

cd "$(dirname "$0")/.."

# `python3` on Windows is a Microsoft Store stub that does not run, and inside
# an activated venv `python` always exists. Prefer `python`, fall back to
# `python3` for the bare-Linux case where only the versioned name is on PATH.
PY=python
command -v python >/dev/null 2>&1 || PY=python3

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
FETCH_EMBEDDINGS=false
for arg in "$@"; do
    case "$arg" in
        --skip-pyinstaller) SKIP_PYINSTALLER=true ;;
        --skip-tauri)       SKIP_TAURI=true ;;
        --fetch-embeddings) FETCH_EMBEDDINGS=true ;;
    esac
done

# ── optionally fetch the embedding model so the bundle works offline ──
# One-time, ~90 MB. Needs network; everything after this point does not.
if [ "$FETCH_EMBEDDINGS" = true ]; then
    echo -e "${CYAN}fetching the embedding model (one time, ~90MB)...${NC}"
    [ -f .venv/bin/activate ] && source .venv/bin/activate
    [ -f .venv/Scripts/activate ] && source .venv/Scripts/activate
    $PY - <<'PY'
from pathlib import Path
target = Path("data/models/all-MiniLM-L6-v2")
if target.is_dir():
    print(f"  already present at {target}")
else:
    from sentence_transformers import SentenceTransformer
    target.parent.mkdir(parents=True, exist_ok=True)
    SentenceTransformer("all-MiniLM-L6-v2", device="cpu").save(str(target))
    print(f"  saved to {target}")
PY
    echo ""
fi

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

# ── step 0: guarantee this build reflects the current tree ──
#
# Every output directory is cleared first. The bundle dir is the one that
# actually bites: Tauri does not remove installers from previous versions, so it
# accumulates them, and anything copying "the installers" out of there picks up
# a mix of old and new. A stale binary in local/ is worse than none -- you
# validate it, it passes, and you ship something else.
echo ""
echo -e "${CYAN}[0] clearing previous build outputs...${NC}"
rm -rf src-tauri/target/release/bundle
if [ "$SKIP_PYINSTALLER" = true ]; then
    # --skip-pyinstaller means "reuse the backend I already froze". Clearing it
    # here would delete the very thing the flag says to keep, and the build
    # would then fail at step 3 with a missing binary.
    echo -e "  ${GREEN}cleared${NC} src-tauri/target/release/bundle (kept dist/thinkstack-api)"
else
    rm -rf dist/thinkstack-api
    echo -e "  ${GREEN}cleared${NC} src-tauri/target/release/bundle, dist/thinkstack-api"
fi

# Warn (never block) when the checkout is behind its remote. Building an
# artifact for release validation from stale code wastes the whole cycle.
if git rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    git fetch --quiet 2>/dev/null || true
    BEHIND=$(git rev-list --count 'HEAD..@{u}' 2>/dev/null || echo 0)
    if [ "$BEHIND" -gt 0 ]; then
        echo -e "  ${YELLOW}warning: branch is ${BEHIND} commit(s) behind its remote${NC}"
        echo -e "  ${YELLOW}you are about to build code that is not the latest${NC}"
    fi
fi
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
    echo -e "  ${YELLOW}note: working tree has uncommitted changes (they WILL be built in)${NC}"
fi

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
    # Activate whichever build venv this machine has. Windows lays a venv out
    # as Scripts/ and names the interpreter python.exe; the POSIX-only
    # `source .venv/bin/activate` meant the documented build path could not run
    # on Windows at all, so the Windows build was done by hand instead -- which
    # is how .venv-build drifted out of sync with requirements.txt.
    VENV=""
    for candidate in .venv-build .venv; do
        if [ -f "$candidate/bin/activate" ]; then
            # shellcheck disable=SC1090
            source "$candidate/bin/activate"; VENV="$candidate"; break
        elif [ -f "$candidate/Scripts/activate" ]; then
            # shellcheck disable=SC1090
            source "$candidate/Scripts/activate"; VENV="$candidate"; break
        fi
    done
    if [ -n "$VENV" ]; then
        echo -e "  ${GREEN}using build venv:${NC} $VENV"
    else
        echo -e "  ${YELLOW}no .venv-build/.venv found - freezing from the ambient python${NC}"
    fi

    # PyInstaller separates source from destination with ':' on POSIX and ';'
    # on Windows. Using the wrong one silently produces a bundle with no
    # frontend and no models.
    case "$(uname -s)" in
        MINGW*|MSYS*|CYGWIN*) DATA_SEP=";" ;;
        *)                    DATA_SEP=":" ;;
    esac

    export PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1

    # Stage only the models release.config.json says we ship.
    #
    # data/models is a developer's scratch directory -- it accumulates every
    # model you have ever tried. Bundling the directory wholesale made a local
    # build ~1.8 GB larger than the installer CI publishes, so "validated
    # locally" and "what users download" were different artifacts. The config is
    # the single source of truth CI already uses; read it here too.
    STAGE_DIR="dist/.models-stage"
    rm -rf "$STAGE_DIR"; mkdir -p "$STAGE_DIR"

    WANTED=$($PY -c "
import json
for u in json.load(open('release.config.json')).get('models', []):
    print(u.rsplit('/', 1)[-1])
" 2>/dev/null || true)

    MODEL_COUNT=0
    MISSING=""
    for name in $WANTED; do
        if [ -f "data/models/$name" ]; then
            cp -f "data/models/$name" "$STAGE_DIR/"
            MODEL_COUNT=$((MODEL_COUNT + 1))
            echo -e "  ${GREEN}bundling${NC} $name ($(du -h "data/models/$name" | cut -f1))"
        else
            MISSING="$MISSING $name"
        fi
    done

    if [ -n "$MISSING" ]; then
        echo -e "  ${YELLOW}missing from data/models:${MISSING}${NC}"
        echo -e "  ${YELLOW}download it, or the installer ships without it${NC}"
    fi
    if [ "$MODEL_COUNT" -eq 0 ]; then
        echo -e "  ${YELLOW}warning: no gguf model staged -- the app cannot infer offline${NC}"
    fi

    # The embedding model powers ingestion and search. It is NOT a gguf and is
    # not in release.config.json; without it a packaged build reaches for
    # HuggingFace on the first document, which an offline app cannot do.
    if [ -d "data/models/all-MiniLM-L6-v2" ]; then
        cp -r "data/models/all-MiniLM-L6-v2" "$STAGE_DIR/"
        echo -e "  ${GREEN}bundling${NC} all-MiniLM-L6-v2 (embeddings)"
    else
        echo -e "  ${RED}embedding model absent${NC} - ingestion will try to reach huggingface."
        echo -e "  fetch it first: ${CYAN}scripts/build.sh --fetch-embeddings${NC}"
    fi

    # The TeX engine. The product's premise is that the user has nothing
    # installed, so the paper writer cannot depend on a system LaTeX.
    if [ ! -x "data/tex/tectonic" ] && [ ! -x "data/tex/tectonic.exe" ]; then
        bash scripts/fetch-tex.sh data/tex || \
            echo -e "  ${YELLOW}TeX fetch failed - the PDF tab will need a system LaTeX${NC}"
    fi
    if [ -d "data/tex" ]; then
        echo -e "  ${GREEN}bundling${NC} tectonic + warm package cache ($(du -sh data/tex | cut -f1))"
    fi

    # build add-data flags. an array, not a string: an unquoted string expansion
    # relies on word splitting (SC2086) and breaks on any path containing a space.
    ADD_DATA_FLAGS=(--add-data "frontend/dist${DATA_SEP}frontend/dist")
    if [ -n "$(ls -A "$STAGE_DIR" 2>/dev/null)" ]; then
        ADD_DATA_FLAGS+=(--add-data "${STAGE_DIR}${DATA_SEP}data/models")
    fi
    if [ -d "data/tex" ]; then
        ADD_DATA_FLAGS+=(--add-data "data/tex${DATA_SEP}data/tex")
    fi

    # ── preflight: every hidden import must actually be installed ──
    #
    # --hidden-import tells PyInstaller to bundle a module it cannot see being
    # imported. It does NOT install it. When psutil was missing from the build
    # venv, PyInstaller shipped without it, hardware.py caught the ImportError,
    # and every packaged install reported 0.0 GB RAM and pinned itself to the
    # "low" tier. The flag being present in the build command is exactly what
    # made that cause look impossible. So check, and fail loudly.
    MISSING_IMPORTS=""
    for mod in uvicorn psutil llama_cpp sentence_transformers fitz pdfplumber; do
        python -c "import $mod" 2>/dev/null || MISSING_IMPORTS="$MISSING_IMPORTS $mod"
    done
    if [ -n "$MISSING_IMPORTS" ]; then
        echo -e "  ${RED}error: these are required at runtime but not installed in the build venv:${NC}"
        echo -e "  ${RED}  ${MISSING_IMPORTS}${NC}"
        echo -e "  a --hidden-import flag does not install anything. fix with:"
        echo -e "    ${CYAN}pip install -r requirements.txt${NC}"
        exit 1
    fi
    echo -e "  ${GREEN}preflight ok${NC} - every runtime import resolves in the build venv"

    # --onedir (NOT --onefile): the backend is shipped as a Tauri *resource*
    # dir (tauri.conf.json bundle.resources -> "api/"), which lib.rs launches.
    # a onefile build would re-extract its multi-GB payload to a temp dir on
    # every launch; onedir unpacks once at install.
    # --collect-all llama_cpp / sentence_transformers are REQUIRED (neither has a
    # PyInstaller hook): without them the frozen build omits llama_cpp's lib/*.so
    # and sentence_transformers' data, breaking chat/gap-analysis and search.
    #
    # The --exclude-module list is only what has been TESTED to be unused: the
    # app was run with each blocked at import time and every runtime path
    # (routes, embedding, search, graph, hardware) still passed. sklearn and
    # scipy are deliberately NOT excluded despite the app never importing them
    # directly -- sentence_transformers pulls sklearn.metrics at runtime, so
    # dropping them yields a build with no embeddings and no search.
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
        --exclude-module tkinter \
        --exclude-module nltk \
        --exclude-module pytest \
        "${ADD_DATA_FLAGS[@]}" \
        main.py

    # ── the frozen bundle must contain the UI it was built from ──
    #
    # Vite writes content-hashed filenames, so rebuilding the frontend while
    # PyInstaller is running changes them underneath it: Analysis records
    # index-<oldhash>.js, COLLECT cannot find it, and PyInstaller only WARNS.
    # The result is a bundle whose index.html references assets that are not in
    # it -- a blank screen at runtime, from a build that reported success.
    #
    # So verify rather than trust: every asset index.html references must exist
    # inside the frozen bundle.
    FE="dist/thinkstack-api/_internal/frontend/dist"
    [ -d "$FE" ] || FE="dist/thinkstack-api/frontend/dist"
    if [ -f "$FE/index.html" ]; then
        MISSING_ASSETS=""
        for asset in $(grep -oE '(src|href)="[^"]*/assets/[^"]+"' "$FE/index.html" \
                       | sed 's/.*assets\///; s/"$//'); do
            [ -f "$FE/assets/$asset" ] || MISSING_ASSETS="$MISSING_ASSETS $asset"
        done
        if [ -n "$MISSING_ASSETS" ]; then
            echo -e "  ${RED}error: the frozen bundle is missing assets its index.html needs:${NC}"
            echo -e "  ${RED} ${MISSING_ASSETS}${NC}"
            echo -e "  this happens when frontend/dist is rebuilt while pyinstaller runs."
            echo -e "  re-run the build and do not touch the frontend while it works."
            exit 1
        fi
        echo -e "  ${GREEN}bundled ui verified${NC} - index.html's assets are all present"
    else
        echo -e "  ${YELLOW}warning: no bundled index.html found under $FE${NC}"
    fi

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

# Boot the frozen backend and require a healthy response, exactly as CI does.
# A binary that exists is not a binary that runs: a single bad import makes the
# freeze succeed and the app fail at launch, and that is invisible until the
# desktop shell sits on a loading screen. Catch it here, before spending
# minutes on the cargo build.
BIN="dist/thinkstack-api/thinkstack-api"
[ -x "$BIN" ] || BIN="dist/thinkstack-api/thinkstack-api.exe"
if [ -x "$BIN" ]; then
    echo -e "  smoke test: booting the frozen backend on :8765..."
    SMOKE_LOG="dist/.smoke.log"
    "$BIN" --host 127.0.0.1 --port 8765 > "$SMOKE_LOG" 2>&1 &
    SMOKE_PID=$!
    SMOKE_OK=false
    for _ in $(seq 1 60); do
        if curl -fsS -m 3 "http://127.0.0.1:8765/api/system/health" >/dev/null 2>&1; then
            SMOKE_OK=true; break
        fi
        kill -0 "$SMOKE_PID" 2>/dev/null || break
        sleep 1
    done
    kill "$SMOKE_PID" 2>/dev/null || true
    wait "$SMOKE_PID" 2>/dev/null || true

    if [ "$SMOKE_OK" = true ]; then
        echo -e "  ${GREEN}frozen backend answered /api/system/health${NC}"
    else
        echo -e "  ${RED}frozen backend never became healthy${NC}"
        echo -e "  ${RED}last 20 lines of $SMOKE_LOG:${NC}"
        tail -20 "$SMOKE_LOG" 2>/dev/null | sed 's/^/    /'
        exit 1
    fi
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
    # On Linux the AppImage bundler runs linuxdeploy, which ALWAYS fails on our
    # PyInstaller backend: it tries to resolve every wheel-vendored .so (hashed
    # names like libbrotlicommon-<hash>.so.1) and errors on "Could not find
    # dependency". PyInstaller has already bundled them, so that resolution is
    # both redundant and broken. linuxdeploy still leaves a complete AppDir
    # behind, which appimagetool packages directly.
    #
    # This mirrors .github/workflows/_build-desktop.yml. It did not, once, and
    # `set -e` turned the expected failure into an aborted build that never
    # reached the copy-to-local step -- so a Fedora machine got a .deb it could
    # not install and no AppImage at all.
    export APPIMAGE_EXTRACT_AND_RUN=1   # linuxdeploy is itself an AppImage; skip FUSE
    export NO_STRIP=true                # stripping breaks PyInstaller's payload

    if [ "$(uname -s)" = "Linux" ]; then
        npm run tauri build || echo -e "  ${YELLOW}linuxdeploy failed (expected) - packaging the AppDir directly${NC}"
        if [ -d src-tauri/target/release/bundle/appimage ]; then
            bash scripts/package-appimage.sh
        fi
    else
        npm run tauri build
    fi
    echo -e "  ${GREEN}desktop binary compiled${NC}"
fi

# ── step 5: publish installers to local/ ──
# local/ is the one place to look for "the build I am about to release". It is
# gitignored and always holds the LATEST installers only: stale binaries here
# are worse than none, because a validation pass against last week's build tells
# you nothing about the one you are tagging.
LOCAL_DIR="local"
if [ -d "src-tauri/target/release/bundle" ]; then
    echo ""
    echo -e "${CYAN}[5/5] publishing installers to ${LOCAL_DIR}/...${NC}"
    mkdir -p "$LOCAL_DIR"
    # clear old installers first -- same reason release.sh refuses a dirty tree
    find "$LOCAL_DIR" -maxdepth 1 -type f \
        \( -name '*.AppImage' -o -name '*.deb' -o -name '*.rpm' \
           -o -name '*.dmg' -o -name '*.msi' -o -name '*.exe' \) -delete 2>/dev/null || true

    COPIED=0
    while IFS= read -r artifact; do
        cp -f "$artifact" "$LOCAL_DIR/" && COPIED=$((COPIED + 1))
        echo -e "    ${GREEN}$(basename "$artifact")${NC} ($(du -h "$artifact" | cut -f1))"
    done < <(find src-tauri/target/release/bundle -maxdepth 2 -type f \
        \( -name '*.AppImage' -o -name '*.deb' -o -name '*.rpm' \
           -o -name '*.dmg' -o -name '*.msi' -o -name '*.exe' \) 2>/dev/null)

    if [ "$COPIED" -eq 0 ]; then
        echo -e "  ${YELLOW}no installers found to copy${NC}"
    else
        echo -e "  ${GREEN}${COPIED} installer(s) in ${LOCAL_DIR}/${NC}"
    fi

    # Developer tooling only. local/ is the maintainer's own build output --
    # beta testers are early USERS: they download an installer from the beta
    # page and use the app. Handing them a test checklist was a category error.
    cp -f scripts/validate_bundle.py "$LOCAL_DIR/" 2>/dev/null || true
    echo -e "  ${GREEN}validate_bundle.py${NC} -> run it against the installed app"
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
if [ -d "$LOCAL_DIR" ] && [ -n "$(ls -A "$LOCAL_DIR" 2>/dev/null)" ]; then
    echo -e "    installers:     ${GREEN}${LOCAL_DIR}/${NC}  <- validate THIS before releasing"
fi
echo -e "${CYAN}────────────────────────────────────${NC}"
