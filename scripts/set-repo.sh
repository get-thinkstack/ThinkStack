#!/bin/bash
# thinkstack: point the project at a different GitHub owner/repo.
#
# The repo slug is baked into several places, most importantly the auto-updater
# endpoint that ships inside every installer. Changing it by hand means missing
# one and shipping binaries that check the wrong URL for updates, so this script
# rewrites all of them in one shot.
#
# usage: ./scripts/set-repo.sh <owner>/<repo>
#   e.g. ./scripts/set-repo.sh thinkstack-app/ThinkStack
#
# After running: commit the diff, update the git remote, and (if the repo moved)
# transfer it in GitHub's UI. GitHub redirects the old URLs, so already-installed
# apps keep updating.
set -e

cd "$(dirname "$0")/.."

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

NEW_SLUG="$1"
if [ -z "$NEW_SLUG" ]; then
    echo -e "${RED}usage: ./scripts/set-repo.sh <owner>/<repo>${NC}"
    echo -e "  e.g. ./scripts/set-repo.sh thinkstack-app/ThinkStack"
    exit 1
fi
if ! echo "$NEW_SLUG" | grep -qE '^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$'; then
    echo -e "${RED}error: expected <owner>/<repo>, got '${NEW_SLUG}'${NC}"
    exit 1
fi

# current slug is the single source of truth in release.config.json
OLD_SLUG=$(jq -r '.repo' release.config.json)
if [ -z "$OLD_SLUG" ] || [ "$OLD_SLUG" = "null" ]; then
    echo -e "${RED}error: could not read .repo from release.config.json${NC}"
    exit 1
fi

echo -e "${CYAN}────────────────────────────────────${NC}"
echo -e "${CYAN}  repo slug: ${OLD_SLUG} -> ${NEW_SLUG}${NC}"
echo -e "${CYAN}────────────────────────────────────${NC}"

if [ "$OLD_SLUG" = "$NEW_SLUG" ]; then
    echo -e "${YELLOW}already set to ${NEW_SLUG} - nothing to do${NC}"
    exit 0
fi

# every tracked file that mentions the slug (docs, configs, workflows, landing).
# -l lists names; git ls-files keeps it to tracked files only.
FILES=$(git ls-files | xargs grep -l "$OLD_SLUG" 2>/dev/null || true)
if [ -z "$FILES" ]; then
    echo -e "${YELLOW}no tracked file mentions ${OLD_SLUG}${NC}"
    exit 0
fi

echo -e "${CYAN}rewriting:${NC}"
for f in $FILES; do
    count=$(grep -c "$OLD_SLUG" "$f" || true)
    # '#' delimiter: the slug contains '/', which would terminate a s/// pattern
    sed -i "s#${OLD_SLUG}#${NEW_SLUG}#g" "$f"
    echo -e "  ${GREEN}✓${NC} $f (${count})"
done

echo ""
echo -e "${CYAN}verifying no stale references remain...${NC}"
STALE=$(git ls-files | xargs grep -l "$OLD_SLUG" 2>/dev/null || true)
if [ -n "$STALE" ]; then
    echo -e "  ${RED}✗ still referenced in:${NC}"
    while IFS= read -r line; do
        echo "      $line"
    done <<< "$STALE"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} clean"

# the updater endpoint is the one that ships inside binaries - show it explicitly
echo ""
echo -e "${CYAN}updater endpoint now:${NC}"
jq -r '.plugins.updater.endpoints[]' src-tauri/tauri.conf.json 2>/dev/null | sed 's/^/  /'

echo ""
echo -e "${CYAN}────────────────────────────────────${NC}"
echo -e "${GREEN}  done.${NC} next steps:"
echo -e "    1. review:  git diff"
echo -e "    2. commit:  git commit -am 'chore: move to ${NEW_SLUG}'"
echo -e "    3. transfer the repo to the new owner in GitHub's UI (Settings -> General -> Transfer)"
echo -e "    4. update the remote:  git remote set-url origin git@github.com:${NEW_SLUG}.git"
echo -e "${CYAN}────────────────────────────────────${NC}"
