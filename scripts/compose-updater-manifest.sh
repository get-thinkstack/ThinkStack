#!/bin/bash
# thinkstack: compose the tauri auto-updater manifest (latest.json)
#
# reads the per-platform updater signatures (*.sig) that `tauri build` emits
# next to each installer and produces the latest.json manifest the desktop app
# polls (the endpoint configured in src-tauri/tauri.conf.json). the app compares
# its own version to `version` here and, if older, downloads the matching
# platform `url`, verifies it against the `signature`, installs, and relaunches.
#
# usage:
#   scripts/compose-updater-manifest.sh <version> <artifacts_dir> <owner/repo> [download_tag] > latest.json
#
# download_tag is the release tag the installers actually live under, used to
# build the `url` each platform downloads from. it defaults to v<version> (the
# stable channel's versioned release); pass a rolling channel tag (e.g. "beta"
# or "nightly") when the installers are published to a rolling release instead.
#
# example:
#   scripts/compose-updater-manifest.sh 0.2.0 all-artifacts Rithesh077/ThinkStack > latest.json
#   scripts/compose-updater-manifest.sh 0.2.0-beta.1 all-artifacts Rithesh077/ThinkStack beta > latest.json
#
# emits nothing (exit 1) when no *.sig files are found, so an unsigned build
# does not publish a broken manifest. the release job treats that as "skip".
set -euo pipefail

VERSION="${1:?usage: compose-updater-manifest.sh <version> <artifacts_dir> <owner/repo> [download_tag]}"
ARTIFACTS_DIR="${2:?missing artifacts_dir}"
REPO="${3:?missing owner/repo}"
DOWNLOAD_TAG="${4:-v${VERSION}}"

BASE="https://github.com/${REPO}/releases/download/${DOWNLOAD_TAG}"
PUB_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# find the updater target file for a platform by extension, return its basename.
find_asset() {
    local pattern="$1"
    # `|| true`: a missing platform asset must yield an empty string, not fail the
    # pipeline under `set -e`/`pipefail` (ls exits non-zero when nothing matches).
    # shellcheck disable=SC2012
    ls "$ARTIFACTS_DIR"/$pattern 2>/dev/null | head -1 | xargs -r basename || true
}

# emit a "platform" entry if both the asset and its .sig exist.
platform_entry() {
    local key="$1" asset="$2"
    [ -z "$asset" ] && return 1
    local sig_file="$ARTIFACTS_DIR/${asset}.sig"
    [ -f "$sig_file" ] || return 1
    local sig
    sig="$(cat "$sig_file")"
    printf '    "%s": { "signature": "%s", "url": "%s/%s" }' \
        "$key" "$sig" "$BASE" "$asset"
}

# resolve each platform's updater target (matches tauri v2 bundle naming).
LINUX_APPIMAGE="$(find_asset '*.AppImage')"
MAC_TARGZ="$(find_asset '*.app.tar.gz')"
WIN_MSI="$(find_asset '*.msi')"
[ -z "$WIN_MSI" ] && WIN_MSI="$(find_asset '*-setup.exe')"

entries=()
if e=$(platform_entry "linux-x86_64"   "$LINUX_APPIMAGE"); then entries+=("$e"); fi
if e=$(platform_entry "darwin-x86_64"  "$MAC_TARGZ");      then entries+=("$e"); fi
if e=$(platform_entry "darwin-aarch64" "$MAC_TARGZ");      then entries+=("$e"); fi
if e=$(platform_entry "windows-x86_64" "$WIN_MSI");        then entries+=("$e"); fi

if [ "${#entries[@]}" -eq 0 ]; then
    echo "no signed updater artifacts (*.sig) found in $ARTIFACTS_DIR" >&2
    exit 1
fi

# join entries with a comma+newline BETWEEN them (no trailing comma)
joined=""
for e in "${entries[@]}"; do
    if [ -n "$joined" ]; then
        joined="${joined},"$'\n'
    fi
    joined="${joined}${e}"
done

cat <<EOF
{
  "version": "${VERSION}",
  "notes": "See the release notes at https://github.com/${REPO}/releases/tag/v${VERSION}",
  "pub_date": "${PUB_DATE}",
  "platforms": {
${joined}
  }
}
EOF
