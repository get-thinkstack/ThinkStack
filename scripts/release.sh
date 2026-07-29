#!/bin/bash
# thinkstack: cut a release
#
# creates the annotated git tag that triggers the matching channel workflow:
#   stable  → tag v<X.Y.Z>        → .github/workflows/release-stable.yml
#   beta    → tag v<X.Y.Z>-beta.N → .github/workflows/release-beta.yml
# (nightly needs no tag — it runs on a schedule; see nightly.yml.)
#
# for a stable release it also bumps the version everywhere it is hard-coded and
# commits that bump. a beta tag is cut at the current HEAD without a version-file
# bump: the ci stamps the numeric bundle version at build time, and the landing
# page must keep pointing at the stable download.
#
# usage:
#   scripts/release.sh <version> [--beta N] [--push]
#
# examples:
#   scripts/release.sh 0.2.0              # bump + commit + tag v0.2.0 (stable)
#   scripts/release.sh 0.2.0 --push       # ... and push (triggers stable ci)
#   scripts/release.sh 0.2.0 --beta 1     # tag v0.2.0-beta.1 (beta channel)
#   scripts/release.sh 0.2.0 --beta 2 --push
#
# see docs/RELEASE_GUIDE.md for the full release + auto-update flow.
set -euo pipefail

cd "$(dirname "$0")/.."

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'

# ── parse args ──
VERSION=""
BETA=""
PUSH=false
while [ $# -gt 0 ]; do
    case "$1" in
        --beta) BETA="${2:-}"; shift 2 ;;
        --push) PUSH=true; shift ;;
        -*)     echo -e "${RED}unknown flag: $1${NC}"; exit 1 ;;
        *)      VERSION="$1"; shift ;;
    esac
done

if [ -z "$VERSION" ]; then
    echo -e "${RED}usage: scripts/release.sh <version> [--beta N] [--push]${NC}"; exit 1
fi
# validate semver-ish core (X.Y.Z)
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo -e "${RED}version must look like 1.2.3 (got '$VERSION')${NC}"; exit 1
fi

CHANNEL="stable"
FULL_VERSION="$VERSION"
if [ -n "$BETA" ]; then
    if ! echo "$BETA" | grep -qE '^[0-9]+$'; then
        echo -e "${RED}--beta takes an integer counter (got '$BETA')${NC}"; exit 1
    fi
    CHANNEL="beta"
    FULL_VERSION="${VERSION}-beta.${BETA}"
fi
TAG="v${FULL_VERSION}"

# repo comes from the single source of truth so this script and ci agree.
REPO="$(python3 -c "import json;print(json.load(open('release.config.json'))['repo'])" 2>/dev/null || echo 'get-thinkstack/ThinkStack')"

echo -e "${CYAN}────────────────────────────────────${NC}"
echo -e "${CYAN}  thinkstack: ${CHANNEL} release ${TAG}${NC}"
echo -e "${CYAN}────────────────────────────────────${NC}"

# ── refuse to release from a dirty tree ──
if [ -n "$(git status --porcelain)" ]; then
    echo -e "${RED}working tree is dirty — commit or stash first.${NC}"; exit 1
fi
if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo -e "${RED}tag ${TAG} already exists.${NC}"; exit 1
fi

# ── refuse to release a version older than what users already have ──
# The updater serves whatever `latest` points at. Publishing a lower version
# after a higher one makes installed apps see an "update" that moves them
# backwards, and there is no clean way to undo that once it has shipped.
if command -v gh >/dev/null 2>&1; then
    LATEST="$(gh release view --repo "$REPO" --json tagName -q .tagName 2>/dev/null | sed 's/^v//' || true)"
    if [ -n "$LATEST" ]; then
        # sort -V puts the lower version first; if that is not the published one,
        # the new version is going backwards.
        LOWEST="$(printf '%s\n%s\n' "$LATEST" "$VERSION" | sort -V | head -1)"
        if [ "$VERSION" != "$LATEST" ] && [ "$LOWEST" = "$VERSION" ]; then
            echo -e "${RED}refusing to release ${VERSION}: ${LATEST} is already published.${NC}"
            echo -e "  releasing backwards would push installed apps to an older build."
            echo -e "  bump past ${LATEST} instead."
            exit 1
        fi
    fi
fi

# ── refuse to tag a commit whose CI is not green ──
# A tag is what builds and ships installers. Tagging a red commit means the
# broken build reaches users, and the only fix is another release. Checks are
# looked up for the exact commit being tagged.
if command -v gh >/dev/null 2>&1; then
    SHA="$(git rev-parse HEAD)"
    CONCLUSIONS="$(gh api "repos/${REPO}/commits/${SHA}/check-runs" \
        --jq '.check_runs[] | select(.name != "CI OK") | .conclusion' 2>/dev/null || true)"
    if [ -z "$CONCLUSIONS" ]; then
        echo -e "${YELLOW}!${NC} no CI results found for ${SHA:0:8} (not pushed yet?)."
        echo -e "  push the commit and let CI finish before tagging a release."
        if [ "$CHANNEL" = "stable" ]; then
            printf "  release anyway? [y/N] "
            read -r ans
            case "$ans" in y|Y|yes) ;; *) echo "  aborted."; exit 1 ;; esac
        fi
    elif echo "$CONCLUSIONS" | grep -qvE '^(success|skipped|neutral)$'; then
        echo -e "${RED}CI is not green for ${SHA:0:8}:${NC}"
        gh api "repos/${REPO}/commits/${SHA}/check-runs" \
            --jq '.check_runs[] | select(.conclusion != "success" and .conclusion != "skipped" and .conclusion != "neutral") | "    \(.name): \(.conclusion // .status)"' 2>/dev/null || true
        echo -e "  fix these before releasing - a tag ships installers to users."
        exit 1
    else
        echo -e "  ${GREEN}✓${NC} CI green for ${SHA:0:8}"
    fi
fi

# ── stable: bump the hard-coded versions and commit ──
# beta cuts a tag at HEAD with no file bump (ci stamps the bundle version, and
# the landing page keeps pointing at the stable download).
if [ "$CHANNEL" = "stable" ]; then
    # 1. tauri.conf.json version
    python3 - "$VERSION" <<'PY'
import json, sys
p = "src-tauri/tauri.conf.json"
d = json.load(open(p))
d["version"] = sys.argv[1]
json.dump(d, open(p, "w"), indent=2)
open(p, "a").write("\n")
print(f"  updated {p}")
PY

    # 2. landing.html download-link VERSION const
    if grep -q "const VERSION = '" landing.html; then
        sed -i "s/const VERSION = '[^']*'/const VERSION = '${VERSION}'/" landing.html
        echo "  updated landing.html"
    fi
    if [ -f docs/landing/index.html ] && grep -q "const VERSION = '" docs/landing/index.html; then
        sed -i "s/const VERSION = '[^']*'/const VERSION = '${VERSION}'/" docs/landing/index.html
        echo "  updated docs/landing/index.html"
    fi

    # 3. src-tauri/Cargo.toml package version
    if grep -qE '^version = ' src-tauri/Cargo.toml; then
        sed -i "0,/^version = .*/s//version = \"${VERSION}\"/" src-tauri/Cargo.toml
        echo "  updated src-tauri/Cargo.toml"
    fi

    echo ""
    echo -e "  ${GREEN}version bumped to ${VERSION}${NC}"
    git --no-pager diff --stat

    # Stage only paths that exist. `git add` is atomic across its pathspecs: one
    # missing file makes it stage NOTHING, and with the error swallowed the
    # commit then aborts with "no changes added". That is exactly what happened
    # when this listed a docs/ path that no longer exists.
    # Cargo.lock is included because bumping the package version rewrites it.
    for f in src-tauri/tauri.conf.json src-tauri/Cargo.toml src-tauri/Cargo.lock landing.html; do
        [ -f "$f" ] && git add "$f"
    done

    if git diff --cached --quiet; then
        echo -e "  ${YELLOW}nothing to commit - version files already at ${VERSION}${NC}"
    else
        git commit -q -m "chore(release): ${TAG}"
        echo -e "  ${GREEN}committed the version bump${NC}"
    fi
fi

git tag -a "$TAG" -m "ThinkStack ${TAG}"
echo -e "  ${GREEN}tagged ${TAG} (${CHANNEL})${NC}"

# ── push (opt-in) ──
if [ "$PUSH" = true ]; then
    echo ""
    echo -e "${YELLOW}pushing ${TAG} will trigger the ${CHANNEL} build + publish a"
    echo -e "public GitHub Release. this is hard to undo.${NC}"
    read -r -p "  push tag ${TAG} now? [y/N] " ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
        git push origin HEAD
        git push origin "$TAG"
        echo -e "  ${GREEN}pushed. watch: https://github.com/${REPO}/actions${NC}"
    else
        echo -e "  ${YELLOW}skipped push. run 'git push origin $TAG' when ready.${NC}"
    fi
else
    echo ""
    echo -e "  next: ${CYAN}git push origin HEAD && git push origin ${TAG}${NC}  (triggers ci)"
    echo -e "  or re-run with ${CYAN}--push${NC}."
fi
