#!/usr/bin/env python3
"""Work out the next version number, so nobody has to remember or guess it.

The rules, stated once:

    a fix      -> patch     X.Y.Z   -> X.Y.(Z+1)
    a feature  -> minor     X.Y.Z   -> X.(Y+1).0
    a breaking -> major     X.Y.Z   -> (X+1).0.0

"Current" means the newest published STABLE tag (vX.Y.Z), not whatever happens
to sit in tauri.conf.json, because that file is only bumped as part of cutting a
release and is therefore behind between releases.

The kind can be given, or inferred from the commit subjects since that tag using
the conventional-commit prefixes this project already uses. Inference is
deliberately conservative: anything it cannot classify counts as a fix, so an
unclear history produces a patch bump rather than an inflated one.

usage:
    next_version.py --bump minor      # next minor from the newest stable tag
    next_version.py --infer           # classify the commits, then bump
    next_version.py --explain --infer # ... and say why
    next_version.py --current         # the newest stable tag, bare
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys

SEMVER_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")

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


def commits_since(version: tuple[int, int, int]) -> list[str]:
    """Commit subjects since that tag, or the whole history if it has none."""
    tag = "v%d.%d.%d" % version
    rng = f"{tag}..HEAD" if _git("rev-parse", "--verify", "--quiet", tag) else "HEAD"
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


def apply_bump(version: tuple[int, int, int], bump: str) -> str:
    major, minor, patch = version
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    return f"{major}.{minor}.{patch + 1}"


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--bump", choices=["major", "minor", "patch"])
    g.add_argument("--infer", action="store_true")
    g.add_argument("--current", action="store_true")
    ap.add_argument("--explain", action="store_true",
                    help="print the reasoning to stderr")
    args = ap.parse_args()

    cur = current_stable()

    if args.current:
        print("%d.%d.%d" % cur)
        return 0

    if args.infer:
        commits = commits_since(cur)
        bump, why = infer_bump(commits)
    else:
        bump, why = args.bump, "requested"

    nxt = apply_bump(cur, bump)

    if args.explain:
        print("  current stable : v%d.%d.%d" % cur, file=sys.stderr)
        print(f"  bump           : {bump} ({why})", file=sys.stderr)
        print(f"  next           : v{nxt}", file=sys.stderr)

    print(nxt)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
