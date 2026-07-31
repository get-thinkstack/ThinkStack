#!/bin/bash
# thinkstack: activate the shared git hooks. Run once after cloning.
#
#   ./scripts/install-hooks.sh
#
# Points git at the version-controlled .githooks/ directory instead of the
# per-clone .git/hooks/. That means the whole team gets the same hooks from the
# repo, and an update to a hook arrives with a normal git pull -- no copying,
# nothing to keep in sync by hand.
#
# undo with:  git config --unset core.hooksPath
set -euo pipefail

cd "$(dirname "$0")/.."

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'

git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true

# Clear the old colliding rolling tags, once.
#
# The beta and nightly channels used to publish under tags named "beta" and
# "nightly" -- the same names as our branches. Git resolves refs/tags/ before
# refs/heads/, so a bare `beta` meant the TAG: `git checkout beta` detached onto
# a release and `git pull` reported a divergence that did not exist.
#
# The tags are now suffixed (see release.config.json), so nothing collides any
# more. This only cleans up clones made before that change.
for stale in beta nightly; do
    if git rev-parse --verify --quiet "refs/tags/${stale}" >/dev/null; then
        git tag -d "$stale" >/dev/null 2>&1 || true
        echo "  removed the stale '${stale}' tag (it shadowed the branch)"
    fi
done

echo -e "${CYAN}────────────────────────────────────────────${NC}"
echo -e "${GREEN}  git hooks active${NC} (core.hooksPath -> .githooks)"
echo -e "${CYAN}────────────────────────────────────────────${NC}"
echo -e "  ${GREEN}pre-commit${NC}  fast: secrets, syntax, JSON/YAML, conflict markers"
echo -e "  ${GREEN}pre-push${NC}    full: mirrors CI via scripts/preflight.sh"
echo ""
echo -e "  gate by branch:"
echo -e "    ${CYAN}dev${NC}         fast - lint + tests on what changed"
echo -e "    ${CYAN}beta / prod${NC} full - everything CI runs"
echo ""
echo -e "  bypass once: ${YELLOW}git commit --no-verify${NC} / ${YELLOW}git push --no-verify${NC}"


# the checks are only as good as the tools available locally
echo ""
echo -e "${CYAN}  local tooling:${NC}"
for t in ruff pytest shellcheck actionlint cargo npm; do
    case "$t" in
        pytest) if python3 -m pytest --version >/dev/null 2>&1; then S="${GREEN}✓${NC}"; else S="${YELLOW}-${NC}"; fi ;;
        actionlint)
            if command -v actionlint >/dev/null 2>&1 || [ -x ./actionlint ]; then S="${GREEN}✓${NC}"; else S="${YELLOW}-${NC}"; fi ;;
        *) if command -v "$t" >/dev/null 2>&1; then S="${GREEN}✓${NC}"; else S="${YELLOW}-${NC}"; fi ;;
    esac
    echo -e "    $S $t"
done
echo ""
echo -e "  missing any? ${CYAN}pip install -r requirements-dev.txt${NC}"
echo -e "  shellcheck matters most: without it actionlint silently skips shell checks."
echo -e "    fedora: ${CYAN}sudo dnf install ShellCheck${NC}   debian: ${CYAN}sudo apt install shellcheck${NC}"
