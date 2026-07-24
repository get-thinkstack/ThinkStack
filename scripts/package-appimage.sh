#!/bin/bash
# package a tauri-created AppDir into an AppImage using appimagetool.
#
# tauri's default appimage bundler runs linuxdeploy, which fails on our
# PyInstaller backend: it tries to resolve every wheel-vendored .so (hashed
# names like libbrotlicommon-<hash>.so.1) and errors on
# "Could not find dependency". PyInstaller already bundles every dependency,
# so linuxdeploy's dependency resolution is both redundant and broken here.
# this packages the completed AppDir directly with appimagetool (no dependency
# resolution) and signs it for the updater if signing env vars are set.
#
# usage: run `tauri build --bundles appimage` first (it creates the AppDir and
# then fails at linuxdeploy, which is expected), then run this script.
set -euo pipefail
cd "$(dirname "$0")/.."

APPIMAGE_DIR="src-tauri/target/release/bundle/appimage"
APPDIR="$(find "$APPIMAGE_DIR" -maxdepth 1 -name '*.AppDir' 2>/dev/null | head -1)"
if [ -z "$APPDIR" ]; then
    echo "error: no *.AppDir in $APPIMAGE_DIR (run 'npm run tauri build -- --bundles appimage' first)" >&2
    exit 1
fi

# the .desktop references its icon by the binary name (tauri-app); appimagetool
# needs a matching icon file at the AppDir root.
ICON="$(find "$APPDIR" -maxdepth 1 -name '*.png' 2>/dev/null | head -1)"
[ -n "$ICON" ] && cp -f "$ICON" "$APPDIR/tauri-app.png"

# fetch appimagetool once (cached under .build-tmp)
TOOL="${APPIMAGETOOL:-$PWD/.build-tmp/appimagetool}"
if [ ! -x "$TOOL" ]; then
    mkdir -p "$(dirname "$TOOL")"
    curl -sSL -o "$TOOL" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi

VERSION="$(python3 -c "import json;print(json.load(open('src-tauri/tauri.conf.json'))['version'])")"
OUT="$APPIMAGE_DIR/ThinkStack_${VERSION}_amd64.AppImage"

# RAM-backed /tmp is often too small for a multi-GB AppDir; use an on-disk temp.
export TMPDIR="${TMPDIR:-$PWD/.build-tmp}"
mkdir -p "$TMPDIR"

echo "packaging $APPDIR -> $OUT"
APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 "$TOOL" "$APPDIR" "$OUT"

# sign for the updater if the signing key is available (matches what tauri's
# own bundler would have produced: an $OUT.sig next to the AppImage).
if [ -n "${TAURI_SIGNING_PRIVATE_KEY:-}" ]; then
    echo "signing $OUT"
    npx --yes @tauri-apps/cli signer sign \
        --private-key "$TAURI_SIGNING_PRIVATE_KEY" \
        --password "${TAURI_SIGNING_PRIVATE_KEY_PASSWORD:-}" \
        "$OUT"
fi

echo "done: $OUT"
