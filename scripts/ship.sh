#!/bin/bash
# thinkstack: ship what beta has been testing, to production, in one command.
#
# This existed as two steps -- `promote.sh release` to merge, then a separate
# `gh workflow run release.yml` to actually publish -- and the gap between them
# is not theoretical: a merge to main was done, the dispatch was not, and main
# sat un-released while everyone assumed it had shipped. Merging and publishing
# are one intention, so they are one command.
#
# usage:
#   scripts/ship.sh              # version derived from what landed on beta
#   scripts/ship.sh 2.2.0        # or state it
#   scripts/ship.sh --dry-run    # show every step, change nothing
#   scripts/ship.sh --yes        # skip the confirmation
#
# What it refuses to do, and why each one has happened:
#
#   * ship from a dirty tree           -- you cannot reproduce what you shipped
#   * ship when beta == main           -- there is nothing to release
#   * ship when beta's build is red    -- promoting a failed build to users
#   * ship a version <= the published  -- the updater only moves forward, so a
#                                         lower number is invisible to everyone
#                                         who already has the higher one, and
#                                         nothing about the release says so
#   * ship a tag that already exists   -- a second dispatch of the same version
#
# The last one matters most. release.yml accepts any version handed to it with
# no ordering check at all, so `-f version=1.0.0` today would tag it, publish
# it as "latest", and quietly present every user with a downgrade.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'

BETA_BRANCH="beta"
MAIN_BRANCH="main"

REPO="$(jq -r '.repo // empty' release.config.json 2>/dev/null)"
[ -n "$REPO" ] || { echo "cannot read .repo from release.config.json" >&2; exit 1; }

VERSION=""
DRY_RUN=false
ASSUME_YES=false

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) DRY_RUN=true; shift ;;
        --yes|-y)  ASSUME_YES=true; shift ;;
        -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
        -*)        echo -e "${RED}unknown flag: $1${NC}"; exit 1 ;;
        *)         VERSION="$1"; shift ;;
    esac
done

run()  { echo -e "  ${CYAN}\$${NC} $*"; $DRY_RUN || "$@"; }
fail() { echo -e "${RED}✗ $*${NC}"; exit 1; }
ok()   { echo -e "  ${GREEN}✓${NC} $*"; }

echo -e "${CYAN}────────────────────────────────────────────${NC}"
echo -e "${CYAN}  ship: ${BETA_BRANCH} -> ${MAIN_BRANCH} -> production${NC}"
echo -e "${CYAN}────────────────────────────────────────────${NC}"

# ── preflight ───────────────────────────────────────────────
echo ""
echo -e "${CYAN}[preflight]${NC}"

[ -z "$(git status --porcelain)" ] || fail "working tree is dirty - commit or stash first"
ok "working tree clean"

# Fatal, not a warning. Every check below reads origin/* refs, so a failed
# fetch does not mean "carry on carefully" -- it means the answers to "is beta
# ahead", "does this tag exist" and "what is published" are all about a state
# that may be hours old. Shipping the wrong tree to users on stale refs is the
# exact failure this script exists to prevent.
# --force, because `beta` and `nightly` are ROLLING tags: each build
# republishes them at a new commit so that releases/download/beta/... stays a
# permanent URL. Git will not move a tag it already has, so without this the
# fetch exits non-zero with "would clobber existing tag" the second time anyone
# runs it -- and every script here read that as the network being down.
git fetch --quiet --tags --force origin \
    || fail "could not reach origin - refusing to ship from stale refs.
    Check the network, then re-run."
ok "fetched origin"

AHEAD="$(git rev-list --count "origin/${MAIN_BRANCH}..origin/${BETA_BRANCH}" 2>/dev/null || echo 0)"
[ "$AHEAD" -gt 0 ] || fail "${BETA_BRANCH} is not ahead of ${MAIN_BRANCH} - nothing to ship"
ok "${BETA_BRANCH} is ${AHEAD} commit(s) ahead of ${MAIN_BRANCH}"

# Never promote a build that did not build. The beta channel publishes on every
# push, so its newest run is the evidence that what is about to reach users
# actually compiles into installers on all three platforms.
BETA_RUN="$(gh run list -w release.yml -b "$BETA_BRANCH" -L 1 \
              --json conclusion,status,databaseId 2>/dev/null || echo '[]')"
BETA_CONCL="$(echo "$BETA_RUN" | jq -r '.[0].conclusion // "none"')"
BETA_STATUS="$(echo "$BETA_RUN" | jq -r '.[0].status // "none"')"
case "$BETA_CONCL:$BETA_STATUS" in
    success:*)   ok "beta's last release build succeeded" ;;
    none:none)   echo -e "  ${YELLOW}!${NC} no beta release run found - cannot confirm beta builds" ;;
    *:in_progress|*:queued)
                 fail "beta's release build is still running - wait for it" ;;
    *)           fail "beta's last release build did not succeed (${BETA_CONCL})" ;;
esac

# ── the version ─────────────────────────────────────────────
echo ""
echo -e "${CYAN}[version]${NC}"

if [ -z "$VERSION" ]; then
    VERSION="$(python3 scripts/next_version.py --next 2>/dev/null)"
    [ -n "$VERSION" ] || fail "could not derive a version - pass one explicitly"
    echo -e "  derived from what landed: ${GREEN}${VERSION}${NC}"
else
    echo -e "  stated: ${GREEN}${VERSION}${NC}"
fi

[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "not a version: ${VERSION}"

# The guard release.yml does not have. sort -V puts the lower version first; if
# that is the one being shipped, it is going backwards.
LATEST="$(gh release view --repo "$REPO" --json tagName -q .tagName 2>/dev/null | sed 's/^v//' || true)"
if [ -n "$LATEST" ]; then
    LOWEST="$(printf '%s\n%s\n' "$LATEST" "$VERSION" | sort -V | head -1)"
    if [ "$VERSION" = "$LATEST" ]; then
        fail "${VERSION} is already published"
    elif [ "$LOWEST" = "$VERSION" ]; then
        fail "refusing to ship ${VERSION}: ${LATEST} is already out.
    The updater only moves forward, so nobody on ${LATEST} would ever see it.
    Bump past ${LATEST} instead."
    fi
    ok "${VERSION} is ahead of the published ${LATEST}"
fi

# An existing tag is the NORMAL case for a promotion, not an error.
#
# release.yml states the design in its own header: "merge into beta -> the tag
# is created here; merge into main -> the SAME tag, reused". Beta cuts vX.Y.Z
# when it builds, so by the time anything is worth promoting the tag always
# exists -- and this guard refused every one of them. It was written for a
# different mistake (dispatching the same stable release twice), which the
# published-release check above already catches.
#
# What must not happen is a second STABLE release of a version already out, and
# that is a question about releases, not tags.
if gh release view "v${VERSION}" --repo "$REPO" >/dev/null 2>&1; then
    fail "v${VERSION} is already published as a release"
fi
if git rev-parse "v${VERSION}" >/dev/null 2>&1; then
    ok "tag v${VERSION} exists (cut by beta) - the promotion reuses it"
else
    ok "tag v${VERSION} is free"
fi

# ── confirm ─────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[plan]${NC}"
echo -e "  merge   ${BETA_BRANCH} -> ${MAIN_BRANCH}   (${AHEAD} commits)"
echo -e "  publish ${GREEN}v${VERSION}${NC} to the stable channel"
echo -e "  ${YELLOW}this is what real users receive, and what their apps auto-update to.${NC}"
$DRY_RUN && echo -e "  ${YELLOW}(dry run - nothing will change)${NC}"

if ! $DRY_RUN && ! $ASSUME_YES; then
    echo ""
    printf "  proceed? [y/N] "
    read -r ans
    case "$ans" in y|Y|yes) ;; *) echo "  aborted."; exit 0 ;; esac
fi

# ── merge ───────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[merge]${NC} ${BETA_BRANCH} -> ${MAIN_BRANCH}"
START_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
trap 'git checkout --quiet "$START_BRANCH" 2>/dev/null || true' EXIT

# CHANGELOG [Unreleased] -> this version, committed on beta and carried to
# dev, so the merge below ships the notes. Nothing pending: no commit.
echo -e "  ${CYAN}[changelog]${NC} [Unreleased] -> v${VERSION}"
run bash scripts/_ship_changelog.sh "$VERSION" \
    || fail "could not promote the changelog; nothing was merged"

run git fetch --quiet origin "+refs/heads/${MAIN_BRANCH}:refs/remotes/origin/${MAIN_BRANCH}" \
    || fail "could not fetch ${MAIN_BRANCH}"
run git checkout --quiet -B "$MAIN_BRANCH" "refs/remotes/origin/${MAIN_BRANCH}" \
    || fail "could not check out ${MAIN_BRANCH}"

if ! $DRY_RUN; then
    # --no-ff so the landing is visible to the version replay; a fast-forward
    # creates no merge commit and the branch name never enters the history.
    if ! git merge --no-ff --no-edit "refs/remotes/origin/${BETA_BRANCH}"; then
        git merge --abort 2>/dev/null || true
        fail "merge conflict ${BETA_BRANCH} -> ${MAIN_BRANCH}. Resolve it, then re-run."
    fi
else
    echo -e "  ${CYAN}\$${NC} git merge --no-ff --no-edit refs/remotes/origin/${BETA_BRANCH}"
fi

run git push origin "refs/heads/${MAIN_BRANCH}:refs/heads/${MAIN_BRANCH}" \
    || fail "could not push ${MAIN_BRANCH}"

# ── publish ─────────────────────────────────────────────────
echo ""
echo -e "${CYAN}[publish]${NC} v${VERSION}"
run gh workflow run release.yml --repo "$REPO" \
    -f channel=stable -f version="$VERSION" \
    || fail "could not dispatch release.yml"

if $DRY_RUN; then
    echo ""
    echo -e "${YELLOW}  dry run complete - nothing changed.${NC}"
    exit 0
fi

# The dispatch is asynchronous and the run takes a moment to appear.
sleep 8
RUN_ID="$(gh run list -w release.yml --repo "$REPO" -L 1 --json databaseId -q '.[0].databaseId')"
echo -e "  watching run ${RUN_ID}"
echo -e "  ${CYAN}https://github.com/${REPO}/actions/runs/${RUN_ID}${NC}"

if ! gh run watch "$RUN_ID" --repo "$REPO" --exit-status >/dev/null 2>&1; then
    fail "the release build failed. main is merged but v${VERSION} was not published.
    Inspect: gh run view ${RUN_ID} --log-failed
    Nothing reached users; fix and re-run scripts/ship.sh ${VERSION}."
fi

# ── verify ──────────────────────────────────────────────────
# Every one of these has been wrong in a real release. A published release that
# is a draft is invisible and 404s, and the updater reads a 404 as "up to date",
# so a broken release looks exactly like a working one from the outside.
echo ""
echo -e "${CYAN}[verify]${NC}"

REL="$(gh release view "v${VERSION}" --repo "$REPO" --json isDraft,isPrerelease,assets 2>/dev/null)"
[ -n "$REL" ] || fail "v${VERSION} was not created"

[ "$(echo "$REL" | jq -r .isDraft)" = "false" ] || fail "v${VERSION} is a DRAFT - invisible to everyone"
ok "published, not a draft"

[ "$(echo "$REL" | jq -r .isPrerelease)" = "false" ] || fail "v${VERSION} is marked prerelease - /releases/latest will skip it"
ok "not a prerelease"

echo "$REL" | jq -e '.assets[] | select(.name=="latest.json")' >/dev/null \
    || fail "no latest.json - the update button will find nothing"
ok "latest.json attached"

MISSING=""
for ext in msi dmg AppImage deb; do
    echo "$REL" | jq -e --arg e "$ext" '.assets[] | select(.name|endswith($e))' >/dev/null \
        || MISSING="$MISSING $ext"
done
[ -z "$MISSING" ] || fail "installers missing:${MISSING}"
ok "all four installers present"

RESOLVED="$(gh api "repos/${REPO}/releases/latest" -q .tag_name 2>/dev/null)"
[ "$RESOLVED" = "v${VERSION}" ] || fail "/releases/latest resolves to ${RESOLVED}, not v${VERSION}"
ok "/releases/latest -> v${VERSION}"

echo ""
echo -e "${CYAN}────────────────────────────────────────────${NC}"
echo -e "${GREEN}  shipped v${VERSION}.${NC} Installed apps will auto-update."
echo -e "  https://github.com/${REPO}/releases/tag/v${VERSION}"
echo -e "  if it goes wrong: ${CYAN}scripts/rollback.sh${NC}"
echo -e "${CYAN}────────────────────────────────────────────${NC}"
