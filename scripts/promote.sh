#!/bin/bash
# thinkstack: move work between branches and ship the binaries for it.
#
# Encodes the two release paths so nobody has to remember the branch/tag dance:
#
#   feature -> beta first, main later, because a feature should be tested on real
#              installers before users get it.
#   fix     -> beta AND main together, because a bug fix is worth nothing sitting
#              in beta while users still hit the bug.
#
# usage:
#   scripts/promote.sh feature <version>   # dev  -> beta   , tag vX.Y.Z-beta.N
#   scripts/promote.sh release <version>   # beta -> main   , tag vX.Y.Z  (stable)
#   scripts/promote.sh fix     <version>   # dev  -> beta AND main, tags both
#
#   --dry-run   show every step, change nothing
#   --yes       skip the confirmation prompt
#
# Each tag triggers the matching channel workflow, which rebuilds and republishes
# the installers for that channel. Installed apps then auto-update to it, so
# "swap the binaries" is the automatic consequence of promoting.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'

DEV_BRANCH="dev"
BETA_BRANCH="beta"
MAIN_BRANCH="main"

KIND=""
VERSION=""
DRY_RUN=false
ASSUME_YES=false
while [ $# -gt 0 ]; do
    case "$1" in
        feature|release|fix) KIND="$1"; shift ;;
        --dry-run) DRY_RUN=true; shift ;;
        --yes|-y)  ASSUME_YES=true; shift ;;
        -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
        -*)        echo -e "${RED}unknown flag: $1${NC}"; exit 1 ;;
        *)         VERSION="$1"; shift ;;
    esac
done

if [ -z "$KIND" ] || [ -z "$VERSION" ]; then
    echo -e "${RED}usage: scripts/promote.sh {feature|release|fix} <version> [--dry-run] [--yes]${NC}"
    exit 1
fi
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo -e "${RED}version must look like 1.2.3 (got '$VERSION')${NC}"; exit 1
fi

run() {  # echo + execute, or just echo under --dry-run
    echo -e "  ${CYAN}\$${NC} $*"
    $DRY_RUN || "$@"
}

fail() { echo -e "${RED}✗ $*${NC}"; exit 1; }

# ── preconditions ───────────────────────────────────────────
# a promotion rewrites shared branches; doing that from a dirty or stale tree is
# how half-finished work reaches users.
[ -n "$(git status --porcelain)" ] && fail "working tree is dirty - commit or stash first"
git fetch --quiet --tags origin 2>/dev/null || echo -e "  ${YELLOW}!${NC} could not reach origin"

START_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
restore_branch() { git checkout --quiet "$START_BRANCH" 2>/dev/null || true; }
trap restore_branch EXIT

# next beta counter for this version: v1.2.3-beta.1, .2, ...
next_beta() {
    local v="$1" last
    last="$(git tag -l "v${v}-beta.*" | sed "s/^v${v}-beta\.//" | sort -n | tail -1)"
    echo $(( ${last:-0} + 1 ))
}

# merge $1 into $2, refusing to leave a conflicted tree behind
merge_into() {
    local src="$1" dst="$2"
    echo ""
    echo -e "${CYAN}[merge]${NC} ${src} -> ${dst}"
    run git checkout --quiet "$dst"
    run git pull --quiet --ff-only origin "$dst" || fail "could not fast-forward $dst from origin"
    if ! $DRY_RUN; then
        if ! git merge --no-edit "origin/${src}"; then
            git merge --abort 2>/dev/null || true
            fail "merge conflict ${src} -> ${dst}. resolve it manually, then re-run."
        fi
    else
        echo -e "  ${CYAN}\$${NC} git merge --no-edit origin/${src}"
    fi
    run git push origin "$dst"
}

# cut the tag that rebuilds + republishes that channel's installers
tag_channel() {
    local channel="$1"
    if [ "$channel" = "beta" ]; then
        local n; n="$(next_beta "$VERSION")"
        echo ""
        echo -e "${CYAN}[tag]${NC} beta -> v${VERSION}-beta.${n}"
        run ./scripts/release.sh "$VERSION" --beta "$n" --push
    else
        echo ""
        echo -e "${CYAN}[tag]${NC} stable -> v${VERSION}"
        run ./scripts/release.sh "$VERSION" --push
    fi
}

# ── plan ────────────────────────────────────────────────────
echo -e "${CYAN}────────────────────────────────────────────${NC}"
echo -e "${CYAN}  promote: ${GREEN}${KIND}${NC} ${VERSION}"
echo -e "${CYAN}────────────────────────────────────────────${NC}"
case "$KIND" in
    feature)
        echo -e "  ${DEV_BRANCH} -> ${BETA_BRANCH}, then tag a beta."
        echo -e "  main is untouched: promote it with"
        echo -e "    ${CYAN}scripts/promote.sh release ${VERSION}${NC}  once the beta checks out."
        ;;
    release)
        echo -e "  ${BETA_BRANCH} -> ${MAIN_BRANCH}, then tag the stable release."
        echo -e "  ${YELLOW}this is what real users receive.${NC}"
        ;;
    fix)
        echo -e "  ${DEV_BRANCH} -> ${BETA_BRANCH} and ${DEV_BRANCH} -> ${MAIN_BRANCH}, tagging both."
        echo -e "  ${YELLOW}a fix ships to users immediately - no beta soak.${NC}"
        ;;
esac
$DRY_RUN && echo -e "  ${YELLOW}(dry run - nothing will change)${NC}"

if ! $DRY_RUN && ! $ASSUME_YES; then
    echo ""
    printf "  proceed? [y/N] "
    read -r ans
    case "$ans" in y|Y|yes) ;; *) echo "  aborted."; exit 0 ;; esac
fi

# ── execute ─────────────────────────────────────────────────
case "$KIND" in
    feature)
        merge_into "$DEV_BRANCH" "$BETA_BRANCH"
        tag_channel beta
        ;;
    release)
        merge_into "$BETA_BRANCH" "$MAIN_BRANCH"
        tag_channel stable
        ;;
    fix)
        merge_into "$DEV_BRANCH" "$BETA_BRANCH"
        tag_channel beta
        merge_into "$DEV_BRANCH" "$MAIN_BRANCH"
        tag_channel stable
        ;;
esac

echo ""
echo -e "${CYAN}────────────────────────────────────────────${NC}"
echo -e "${GREEN}  promoted.${NC} CI is rebuilding the installers for the tagged"
echo -e "  channel(s); installed apps auto-update once it publishes."
echo -e "  watch: ${CYAN}gh run list --limit 3${NC}"
echo -e "${CYAN}────────────────────────────────────────────${NC}"
