#!/usr/bin/env python3
"""Work out the next version number, so nobody has to remember or guess it.

The rules, stated once:

    anything landing   -> X.Y.Z -> X.Y.(Z+1)      automatic, Z is unbounded
    --bump minor       -> X.Y.Z -> X.(Y+1).0      a decision, taken by a human
    --bump minor at Y=9-> X.9.Z -> (X+1).0.0      Y carries into X at ten
    --bump major       -> X.Y.Z -> (X+1).0.0      a decision, taken by a human

X and Y are never inferred from a branch name. Deciding that a set of landings
amounts to a minor version, or to a release, is editorial, and a script reading
branch prefixes cannot make that judgement -- it can only guess consistently.
Z is automatic precisely because it is not a judgement: something landed, so
the number moves, and the build reaches testers.
    a breaking -> major     X.Y.Z   -> (X+1).0.0

"Current" means the newest published STABLE tag (vX.Y.Z), not whatever happens
to sit in tauri.conf.json, because that file is only bumped as part of cutting a
release and is therefore behind between releases.

The kind can be given, or inferred from the commit subjects since that tag using
the conventional-commit prefixes this project already uses. Inference is
deliberately conservative: anything it cannot classify counts as a fix, so an
unclear history produces a patch bump rather than an inflated one.

The BASE is the newest tag across every channel, stable or beta, so the number
can never go backwards. Basing it on the newest STABLE tag is how it did: beta
was testing 1.6.7 while the newest stable was 1.0.0, so a patch bump computed
from stable produced 1.0.1.

--next replays what has landed: each feat/ or fix/ BRANCH MERGE since that tag
applies one bump, oldest first. Direct commits do not move the version, and
neither do chore/ or docs/ branches.

usage:
    next_version.py --next            # replay the merges since the newest tag
    next_version.py --explain --next  # ... and show each one
    next_version.py --bump minor      # force a specific bump
    next_version.py --infer           # classify the commits, then bump
    next_version.py --current         # the newest version, bare
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

SEMVER_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

# Any published version tag, stable or beta. The BASE for a bump is the newest
# of these across every channel, not the newest stable one.
#
# Basing on the newest STABLE tag is how the number goes backwards: beta has
# been testing 1.6.7 while the newest stable is 1.0.0, so a patch bump computed
# from stable is 1.0.1 -- lower than what testers already run. release.sh
# refuses to publish below what is out, and the updater would show installed
# apps an "update" that moves them backwards.
VERSION_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-beta\.(\d+))?$")

# Branch names as they appear in a merge subject:
#   "Merge pull request #48 from owner/fix/mac-issues"
#   "Merge branch 'feat/thing'"
MERGED_BRANCH = re.compile(
    r"Merge (?:"
    r"pull request #\d+ from [^/]+/"
    r"|branch '"
    r"|remote-tracking branch '(?:origin/)?"
    r")(?P<branch>[\w./-]+)"
)

# A commit is breaking if it says so the way conventional commits say it.
BREAKING = re.compile(r"^\w+(\([^)]*\))?!:|BREAKING[ -]CHANGE", re.M)
FEATURE = re.compile(r"^feat(\([^)]*\))?:", re.I)
FIX = re.compile(r"^fix(\([^)]*\))?:", re.I)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], capture_output=True, text=True, check=False
    ).stdout.strip()


def current_stable() -> tuple[int, int, int]:
    """Newest published stable tag, or 0.0.0 if none exists yet."""
    tags = []
    for line in _git("tag", "--list", "v*").splitlines():
        m = SEMVER_TAG.match(line.strip())
        if m:
            tags.append(tuple(int(g) for g in m.groups()))
    return max(tags) if tags else (0, 0, 0)


def commits_since(tag: str | None) -> list[str]:
    """Commit subjects since that tag, or the whole history if there is none."""
    rng = f"{tag}..HEAD" if tag and _git("rev-parse", "--verify", "--quiet", tag) else "HEAD"
    out = _git("log", "--no-merges", "--pretty=%s%n%b%n---", rng)
    return [c.strip() for c in out.split("\n---") if c.strip()]


def infer_bump(commits: list[str]) -> tuple[str, str]:
    """Classify a set of commits. Returns (bump, human explanation)."""
    if not commits:
        return "patch", "no commits since the last release"

    breaking = [c for c in commits if BREAKING.search(c)]
    if breaking:
        return "major", f"{len(breaking)} breaking change(s)"

    feats = [c for c in commits if FEATURE.match(c)]
    fixes = [c for c in commits if FIX.match(c)]

    if feats:
        return "minor", f"{len(feats)} feature(s), {len(fixes)} fix(es)"
    # Unclassified work counts as a fix. Overstating a release is worse than
    # understating one: a version implies a promise about compatibility.
    return "patch", f"{len(fixes)} fix(es), {len(commits) - len(fixes)} other"


def newest_tag() -> tuple[tuple[int, int, int], str | None]:
    """Newest published version across ALL channels, and the tag it came from.

    Ordering is (major, minor, patch, is_stable, beta_number), so v1.6.7 sorts
    above v1.6.7-beta.3 -- a stable release supersedes the betas that led to it.

    Returns ((0, 0, 0), None) when nothing has been tagged yet.
    """
    best: tuple | None = None
    for line in _git("tag", "--list", "v*").splitlines():
        m = VERSION_TAG.match(line.strip())
        if not m:
            continue
        major, minor, patch = (int(g) for g in m.groups()[:3])
        beta = m.group(4)
        key = (major, minor, patch, 0 if beta else 1, int(beta) if beta else 0)
        if best is None or key > best[0]:
            best = (key, (major, minor, patch), line.strip())
    if best is None:
        return (0, 0, 0), None
    return best[1], best[2]


# Y never reaches 10. A tenth feature carries into X and resets Y, so 1.9.x
# is followed by 2.0.0 rather than 1.10.0.
#
# This is NOT semantic versioning and does not pretend to be. Under semver, X
# means "we broke your code", which is meaningless for a desktop application
# nobody imports. What the number is actually for here is telling a user how
# far their build has drifted from the current one, and a decimal odometer says
# that at a glance: two digits apart is two digits apart, whichever column.
#
# Ordering is preserved either way, which is the property that actually
# matters: the updater compares versions, and a build must never advertise a
# number lower than one already installed. 2.0.0 > 1.9.9 under the same
# comparison that gives 1.10.0 > 1.9.9.
MINOR_RADIX = 10


def bump_minor(major: int, minor: int) -> tuple[int, int, int]:
    """A feature landed: Y+1, carrying into X at ten, and Z resets."""
    minor += 1
    if minor >= MINOR_RADIX:
        major, minor = major + 1, 0
    return major, minor, 0


def promote_to_production(major: int) -> tuple[int, int, int]:
    """Promoting beta into main: X+1, and the lower columns reset.

    An official release is the coarsest event the scheme has, so it moves the
    coarsest column. Everything accumulated on beta since the last promotion --
    features in Y, fixes in Z -- is subsumed into that one number.
    """
    return major + 1, 0, 0


def replay_landings(
    base: tuple[int, int, int], since_tag: str | None
) -> tuple[tuple[int, int, int], list[str]]:
    """Apply one bump per branch merged since `since_tag`, oldest first.

    Only MERGE COMMITS count, and only by the name of the branch they merged:

        feat/... or feature/...  -> minor, and the patch resets
        fix/...  or hotfix/...   -> patch
        anything else            -> ignored (chore/, docs/, release merges)

    Direct commits never move the version. A merge is the moment work lands,
    and counting the commits inside it as well would bump the number several
    times for one piece of work.

    Replayed in the order the merges actually happened, because the order
    changes the answer: a fix then a feature gives X.(Y+1).0, while a feature
    then a fix gives X.(Y+1).1.

    Deliberately NOT --first-parent. Work lands on dev, and dev is then merged
    into beta -- from beta's mainline that is a single "Merge branch 'dev'",
    with every feat/ and fix/ merge hanging off the SECOND parent and therefore
    invisible. Replaying beta that way returned the version that was already
    published, so the build advertised a number testers already had and the
    updater correctly refused to offer it. Every merge reachable since the tag
    is counted instead; each merge commit appears exactly once in that range,
    so nothing is double counted.

    NOTE: this requires merges to be real merge commits. A fast-forward merge
    creates none, so the branch name is lost and the landing is invisible here.
    scripts/promote.sh and the merge guide both use --no-ff for that reason.
    """
    rng = f"{since_tag}..HEAD" if since_tag else "HEAD"
    subjects = _git(
        "log", "--merges", "--reverse", "--pretty=%s", rng
    ).splitlines()

    major, minor, patch = base
    notes: list[str] = []
    for subject in subjects:
        m = MERGED_BRANCH.search(subject)
        if not m:
            continue
        branch = m.group("branch")
        # Every landing moves Z, feature or fix alike.
        #
        # X and Y are a DECISION, taken deliberately by running the release
        # workflow with a bump; nothing a branch is named can move them. But a
        # landing that moved no digit at all would be invisible: the version
        # would match a tag that already exists, the build would be skipped as
        # already-published, and the work would never reach a tester. So Z
        # advances on anything that lands, and the editorial question -- is
        # this a minor, is this a release -- stays with the human.
        if branch.startswith(("feat/", "feature/", "fix/", "hotfix/")):
            kind = "feature" if branch.startswith(("feat/", "feature/")) else "fix"
            patch += 1
            notes.append(f"{kind:<8} {branch:<34} -> {major}.{minor}.{patch}")
    return (major, minor, patch), notes


def apply_bump(version: tuple[int, int, int], bump: str) -> str:
    """One explicit bump, obeying the same carry rule as the replay.

    `major` is what promoting to production does; `minor` is a feature landing
    on beta and carries into X at ten; `patch` is a fix and is unbounded --
    there is no ceiling on how many fixes one release accumulates.
    """
    major, minor, patch = version
    if bump == "major":
        return "%d.%d.%d" % promote_to_production(major)
    if bump == "minor":
        return "%d.%d.%d" % bump_minor(major, minor)
    return f"{major}.{minor}.{patch + 1}"


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--bump", choices=["major", "minor", "patch"])
    g.add_argument("--infer", action="store_true")
    g.add_argument("--current", action="store_true")
    g.add_argument("--next", action="store_true", dest="next_",
                   help="replay every feat/ and fix/ branch merged since the "
                        "newest tag, applying one bump each, in order")
    ap.add_argument("--explain", action="store_true",
                    help="print the reasoning to stderr")
    args = ap.parse_args()

    base, base_tag = newest_tag()

    if args.current:
        print("%d.%d.%d" % base)
        return 0

    if args.next_:
        nxt, notes = replay_landings(base, base_tag)
        if args.explain:
            print(f"  base           : {base_tag or 'no tags yet'} "
                  f"({'%d.%d.%d' % base})", file=sys.stderr)
            if notes:
                print(f"  landed since   : {len(notes)}", file=sys.stderr)
                for n in notes:
                    print(f"      {n}", file=sys.stderr)
            else:
                print("  landed since   : nothing that moves the version",
                      file=sys.stderr)
            print("  next           : v%d.%d.%d" % nxt, file=sys.stderr)
        print("%d.%d.%d" % nxt)
        return 0

    if args.infer:
        bump, why = infer_bump(commits_since(base_tag))
    else:
        bump, why = args.bump, "requested"

    nxt = apply_bump(base, bump)

    if args.explain:
        print(f"  base           : {base_tag or 'no tags yet'} "
              f"({'%d.%d.%d' % base})", file=sys.stderr)
        print(f"  bump           : {bump} ({why})", file=sys.stderr)
        print(f"  next           : v{nxt}", file=sys.stderr)

    print(nxt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
