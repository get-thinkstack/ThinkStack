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

# Keep the rolling release tags out of the clone.
#
# The beta and nightly CHANNELS publish under rolling git tags named "beta" and
# "nightly" -- the same names as our branches. Git resolves refs/tags/ before
# refs/heads/, so with both present a bare `beta` means the TAG, and every
# ordinary command silently operates on a release instead of the branch:
#
#   git checkout beta        checks out a detached release
#   git pull                 reports a divergence that does not exist
#   git rev-parse --abbrev-ref HEAD   answers "heads/beta", not "beta"
#
# This has already caused two real bugs (promote.sh failing to fast-forward,
# and a phantom divergence on pull). The tags only need to exist on GitHub, for
# the permanent /releases/download/beta/ URLs -- nothing local reads them. So we
# refuse them on the way in, and both mechanisms are needed:
#   --no-tags            stops auto-following during a normal fetch/pull
#   ^refs/tags/<name>    stops an explicit `git fetch --tags` from pulling them
# Version tags (v*) are unaffected, which promote.sh depends on for its beta
# counter.
git config remote.origin.tagOpt --no-tags
for rolling in beta nightly; do
    if ! git config --get-all remote.origin.fetch | grep -qx "\^refs/tags/${rolling}"; then
        git config --add remote.origin.fetch "^refs/tags/${rolling}"
    fi
    git tag -d "$rolling" >/dev/null 2>&1 || true
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

echo ""
echo -e "${CYAN}  rolling tags blocked${NC} (beta / nightly stay on GitHub only)"
echo -e "  use ${GREEN}git pull${NC} on a tracking branch. ${YELLOW}git pull origin beta${NC} is resolved by"
echo -e "  the SERVER, which still prefers the tag, so spell it out when you need it:"
echo -e "    ${GREEN}git pull origin refs/heads/beta${NC}"

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
