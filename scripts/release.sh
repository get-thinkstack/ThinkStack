#!/bin/bash
# thinkstack: cut a release
#
# bumps the version everywhere it is hard-coded, commits the bump, and creates
# the annotated git tag that triggers the cross-platform build+release CI
# (.github/workflows/build-release.yml). pushing the tag is what publishes the
# release, so that step is opt-in (--push) and always confirmed.
#
# usage:
#   scripts/release.sh <version> [--push]
#
# example:
#   scripts/release.sh 0.2.0            # bump + commit + tag locally
#   scripts/release.sh 0.2.0 --push     # ... and push the tag (triggers CI)
#
# see docs/RELEASE_GUIDE.md for the full release + auto-update flow.
set -euo pipefail

cd "$(dirname "$0")/.."

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'

VERSION="${1:-}"
PUSH=false
[ "${2:-}" = "--push" ] && PUSH=true

if [ -z "$VERSION" ]; then
    echo -e "${RED}usage: scripts/release.sh <version> [--push]${NC}"; exit 1
fi
# validate semver-ish (X.Y.Z)
if ! echo "$VERSION" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+$'; then
    echo -e "${RED}version must look like 1.2.3 (got '$VERSION')${NC}"; exit 1
fi

TAG="v${VERSION}"
echo -e "${CYAN}────────────────────────────────────${NC}"
echo -e "${CYAN}  thinkstack: release ${TAG}${NC}"
echo -e "${CYAN}────────────────────────────────────${NC}"

# ── refuse to release from a dirty tree ──
if [ -n "$(git status --porcelain)" ]; then
    echo -e "${RED}working tree is dirty — commit or stash first.${NC}"; exit 1
fi
if git rev-parse "$TAG" >/dev/null 2>&1; then
    echo -e "${RED}tag ${TAG} already exists.${NC}"; exit 1
fi

# ── 1. tauri.conf.json version ──
python3 - "$VERSION" <<'PY'
import json, sys
p = "src-tauri/tauri.conf.json"
d = json.load(open(p))
d["version"] = sys.argv[1]
json.dump(d, open(p, "w"), indent=2)
open(p, "a").write("\n")
print(f"  updated {p}")
PY

# ── 2. landing.html download-link VERSION const ──
if grep -q "const VERSION = '" landing.html; then
    sed -i "s/const VERSION = '[^']*'/const VERSION = '${VERSION}'/" landing.html
    echo "  updated landing.html"
fi
# docs/landing kept in sync if still present
if [ -f docs/landing/index.html ] && grep -q "const VERSION = '" docs/landing/index.html; then
    sed -i "s/const VERSION = '[^']*'/const VERSION = '${VERSION}'/" docs/landing/index.html
    echo "  updated docs/landing/index.html"
fi

# ── 3. src-tauri/Cargo.toml package version ──
if grep -qE '^version = ' src-tauri/Cargo.toml; then
    sed -i "0,/^version = .*/s//version = \"${VERSION}\"/" src-tauri/Cargo.toml
    echo "  updated src-tauri/Cargo.toml"
fi

echo ""
echo -e "  ${GREEN}version bumped to ${VERSION}${NC}"
git --no-pager diff --stat

# ── commit + tag ──
git add src-tauri/tauri.conf.json landing.html src-tauri/Cargo.toml docs/landing/index.html 2>/dev/null || true
git commit -q -m "chore(release): ${TAG}"
git tag -a "$TAG" -m "ThinkStack ${TAG}"
echo -e "  ${GREEN}committed + tagged ${TAG}${NC}"

# ── push (opt-in) ──
if [ "$PUSH" = true ]; then
    echo ""
    echo -e "${YELLOW}pushing ${TAG} will trigger the cross-platform build + publish a"
    echo -e "public GitHub Release. this is hard to undo.${NC}"
    read -r -p "  push tag ${TAG} now? [y/N] " ans
    if [ "$ans" = "y" ] || [ "$ans" = "Y" ]; then
        git push origin HEAD
        git push origin "$TAG"
        echo -e "  ${GREEN}pushed. watch: https://github.com/Rithesh077/ThinkStack/actions${NC}"
    else
        echo -e "  ${YELLOW}skipped push. run 'git push origin $TAG' when ready.${NC}"
    fi
else
    echo ""
    echo -e "  next: ${CYAN}git push origin HEAD && git push origin ${TAG}${NC}  (triggers CI)"
    echo -e "  or re-run with ${CYAN}--push${NC}."
fi
