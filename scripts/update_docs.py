#!/usr/bin/env python3
"""Refresh the facts embedded in documentation, deterministically.

Numbers in documentation go stale silently. "207 tests" survived long after the
suite reached 309, and the README described a preview that had been deleted.
Prose has to be written by a person (or a model); counts do not, and a count
that is wrong is worse than no count because it is quoted with confidence.

Only text between markers is touched:

    <!-- autodoc:tests -->309 tests across 23 modules<!-- /autodoc -->

Everything outside a marker is left exactly as written, so this can never
clobber an edit. A marker whose value has not changed is not rewritten, so the
script is a no-op on a clean tree.

usage:
    python scripts/update_docs.py            # rewrite in place
    python scripts/update_docs.py --check    # exit 1 if anything is stale
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files that may contain markers. Anything not listed is never touched.
TARGETS = [
    # docs/ only. README.md and CONTRIBUTING.md are written and owned by
    # developers: a script editing sentences there produces churn in every
    # diff and trains people to skim what it wrote.
    "docs/ABOUT.md",
    "docs/ADR.md",
    "docs/FEATURES.md",
    "docs/FUTURE_WORK.md",
]


# ---------------------------------------------------------------- facts


def _version() -> str:
    """The newest published version, from the git tags.

    NOT from src-tauri/tauri.conf.json. That file is only bumped when
    scripts/release.sh runs, and releases no longer go through it -- CI stamps
    the version into the bundle at build time and never writes it back. So the
    committed value sat at 1.0.0 while 1.6.10 was shipping, and any doc built
    from it stated a version that had not existed for weeks.

    Tags are the record of what was actually released, which is the thing the
    documentation is trying to state.
    """
    out = subprocess.run(
        ["git", "tag", "--list", "v*"],
        capture_output=True, text=True, check=False, cwd=ROOT,
    ).stdout
    versions = []
    for line in out.splitlines():
        m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", line.strip())
        if m:
            versions.append(tuple(int(g) for g in m.groups()))
    if versions:
        return "%d.%d.%d" % max(versions)
    # No tags (a fresh clone with --depth=1, say). Fall back rather than lie.
    return json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text())["version"]







def _fe_dep(name: str) -> str:
    """A frontend dependency's version, without the ^ or ~ range marker."""
    pkg = json.loads((ROOT / "frontend" / "package.json").read_text())
    raw = pkg.get("dependencies", {}).get(name) or pkg.get("devDependencies", {}).get(name, "")
    return raw.lstrip("^~") or "?"


def _cargo(pattern: str) -> str:
    text = (ROOT / "src-tauri" / "Cargo.toml").read_text()
    m = re.search(pattern, text, re.M)
    return m.group(1) if m else "?"


def _ci_pin(key: str) -> str:
    """A toolchain version pinned in ci.yml, so docs and CI cannot disagree."""
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()
    m = re.search(rf"{key}:\s*'([^']+)'", text)
    return m.group(1) if m else "?"


def facts() -> dict[str, str]:
    """The values this tool is allowed to write: versions, and nothing else.

    It used to derive test counts, line counts, endpoint counts and ADR totals
    as well. Those are prose about the project, and prose belongs to whoever is
    writing it -- a number that maintains itself stops being read, and a script
    that rewrites sentences produces churn in every diff.

    Versions are different. Each has exactly one correct value, none of them is
    a judgement, and every one of them is wrong the moment something is
    upgraded. The app version in particular is wrong the moment a release is
    cut, which is precisely when nobody is looking at the docs.
    """
    return {
        "version": _version(),
        "react": _fe_dep("react"),
        "vite": _fe_dep("vite"),
        "tauri": _cargo(r'^tauri\s*=\s*(?:\{[^}]*version\s*=\s*")?([^",}]+)'),
        "rust_edition": _cargo(r'^edition\s*=\s*"([^"]+)"'),
        "python": _ci_pin("python-version"),
        "node": _ci_pin("node-version"),
    }




# ---------------------------------------------------------------- rewrite

MARKER = re.compile(
    r"(<!--\s*autodoc:(?P<key>[a-z_]+)\s*-->)(?P<body>.*?)(<!--\s*/autodoc\s*-->)",
    re.DOTALL,
)


def apply(check_only: bool) -> int:
    values = facts()
    stale: list[str] = []
    unknown: list[str] = []

    for rel in TARGETS:
        path = ROOT / rel
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")

        def swap(m: re.Match) -> str:
            key = m.group("key")
            if key not in values:
                unknown.append(f"{rel}: unknown marker {key!r}")
                return m.group(0)
            new = values[key]
            if m.group("body") != new:
                stale.append(f"{rel}: {key} -> {new}")
            return f"{m.group(1)}{new}{m.group(4)}"

        updated = MARKER.sub(swap, original)
        if updated != original and not check_only:
            path.write_text(updated, encoding="utf-8")

    for u in unknown:
        print(f"  warning: {u}")

    if not stale:
        print("  documentation facts are current")
        return 0

    verb = "stale" if check_only else "updated"
    print(f"  {len(stale)} value(s) {verb}:")
    for s in stale:
        print(f"    {s}")
    return 1 if check_only else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="report stale values without writing")
    args = ap.parse_args()
    return apply(args.check)


if __name__ == "__main__":
    raise SystemExit(main())
