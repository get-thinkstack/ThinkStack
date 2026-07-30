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
    python3 - <<'PY'
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
    source .venv/bin/activate
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

    WANTED=$(python3 -c "
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

    # build add-data flags. an array, not a string: an unquoted string expansion
    # relies on word splitting (SC2086) and breaks on any path containing a space.
    ADD_DATA_FLAGS=(--add-data "frontend/dist:frontend/dist")
    if [ -n "$(ls -A "$STAGE_DIR" 2>/dev/null)" ]; then
        ADD_DATA_FLAGS+=(--add-data "$STAGE_DIR:data/models")
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
        "${ADD_DATA_FLAGS[@]}" \
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

    # Ship the self-tests next to the installers. A tester on another OS should
    # need one folder, not a repo checkout -- and "does it work?" answered by a
    # script beats a screenshot of a spinner.
    cp -f scripts/selftest.sh scripts/selftest.ps1 "$LOCAL_DIR/" 2>/dev/null || true
    chmod +x "$LOCAL_DIR/selftest.sh" 2>/dev/null || true

    cat > "$LOCAL_DIR/TESTING.md" <<'GUIDE'
# Testing this build

Everything here is one build. Install it, run it, then run the self-test.

## 1. Install

| OS | File | Notes |
|----|------|-------|
| Linux | `*.AppImage` | `chmod +x` then double-click. Or `sudo dnf install ./*.rpm` / `sudo apt install ./*.deb` |
| macOS | `*.dmg` | Open, drag to Applications. **macOS will block the first launch** -- see below |
| Windows | `*.msi` | Run it. SmartScreen: **More info** -> **Run anyway** |

### macOS will refuse the first launch

You will see *"Apple could not verify ThinkStack is free of malware."* The build
is not notarized (that needs a paid Apple Developer account). The app is fine;
macOS just has no Apple signature to check.

**macOS 15 (Sequoia) and newer** -- the old right-click -> Open trick was removed:

1. Try to open ThinkStack, let it fail.
2. **System Settings -> Privacy & Security**
3. Scroll to Security, click **Open Anyway**, confirm.

**macOS 14 and earlier**: right-click the app -> **Open** -> **Open**.

Terminal alternative: `xattr -d com.apple.quarantine /Applications/ThinkStack.app`

## 2. Launch and watch the loading screen

It names every startup step. Note two things:

- how long a **cold** start takes (first run after install, not a second launch)
- the `spawn: Backend:` line. It must name a path ending in `api/thinkstack-api`.
  If it says *"falling back to a system python"*, stop and report it -- that is a
  packaging bug and the app will not work.

## 3. Run the self-test

With the app open:

```bash
# macOS / Linux
bash selftest.sh

# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File selftest.ps1
```

It checks the backend, which backend launched, hardware detection, the language
model, the embedding model, and pdflatex. It prints a report to paste into the
bug thread. Nothing is uploaded.

## 4. Try it by hand

- **Ingest a PDF.** The only thing that exercises the embedding model. Must work
  with no internet.
- **Ask one chat question.** Slow is fine (~20s on CPU); wrong or empty is not.
- **Run one analysis.** Rougher than you might expect -- with only the bundled
  0.5B model that is intended.
- **Paper writer.** The live preview works everywhere. The **Compiled PDF** tab
  needs a system TeX engine, which ThinkStack does not bundle yet:
  macOS `brew install --cask mactex-no-gui`, Windows MiKTeX, Linux
  `texlive-scheme-basic`. Missing TeX is a known gap, not a bug worth reporting.

## 5. If something fails

Send the self-test output **and** the log:

| OS | Log |
|----|-----|
| Linux | `~/.local/share/com.thinkstack.app/logs/backend.log` |
| macOS | `~/Library/Logs/com.thinkstack.app/backend.log` |
| Windows | `%LOCALAPPDATA%\com.thinkstack.app\logs\backend.log` |

The log holds the full startup trace and all backend output.
GUIDE
    echo -e "  ${GREEN}selftest.sh, selftest.ps1, TESTING.md${NC} -> ${LOCAL_DIR}/"
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
