#!/bin/bash
# thinkstack: rename CHANGELOG's [Unreleased] to <version> on beta, and carry
# the same commit to dev. Run by ship.sh before it merges beta into main.
#
#   scripts/_ship_changelog.sh <version>
#
# The commit reaches dev by CHERRY-PICK, never by merging beta back (the flow
# is dev -> beta -> main only). Markdown only, so the pushes build nothing.
# Nothing under [Unreleased] = no commit. Known cost: an entry added on dev
# between this and the next dev -> beta merge conflicts there (resolve by hand).
set -euo pipefail

VERSION="${1:?usage: _ship_changelog.sh <version>}"
HERE="$(cd "$(dirname "$0")" && pwd)"

git fetch --quiet origin "+refs/heads/beta:refs/remotes/origin/beta" \
                         "+refs/heads/dev:refs/remotes/origin/dev"

git checkout --quiet -B beta refs/remotes/origin/beta
python3 "$HERE/_promote_changelog.py" "$VERSION"
git add -- CHANGELOG.md
if git diff --cached --quiet; then
    exit 0
fi
git commit --quiet -m "docs(changelog): v${VERSION}"
git push --quiet origin "HEAD:refs/heads/beta"
COMPILED="$(git rev-parse HEAD)"

git checkout --quiet -B dev refs/remotes/origin/dev
if git cherry-pick -x "$COMPILED" >/dev/null 2>&1; then
    git push --quiet origin "HEAD:refs/heads/dev"
else
    # dev's [Unreleased] moved on. The release is not blocked over a docs file;
    # the fix is one manual cherry-pick.
    git cherry-pick --abort
    echo "  changelog: compiled on beta, but ${COMPILED:0:7} did not cherry-pick onto dev;"
    echo "  do it by hand: git switch dev && git cherry-pick -x ${COMPILED}"
fi
git checkout --quiet beta
