#!/usr/bin/env python3
"""Refuse a requirements file that lets a dependency move on its own.

Why this exists, precisely:

    1.6.13 built and ran.  nltk resolved to 3.10.0.
    1.6.16 built from a commit that changed no Python code.  nltk resolved to
    3.10.1, which had been released in between and added a security hook that
    refuses to import xml.etree when the working directory is importable.  The
    frozen backend died during startup on Linux, macOS and Windows at once.

Nothing on our side changed.  `nltk>=3.9.1` was an instruction to use whatever
existed at the moment someone pressed build, so the same commit produced a
different program on a different day, and no local run could reproduce it --
the developer's venv had 3.9.4, which has no such hook.

A range is a promise that every future release will work.  Nobody can make that
promise.  Pin, and upgrade deliberately: dependabot opens one pull request per
package, and a human decides.

    scripts/check_pins.py               # check the default files
    scripts/check_pins.py a.txt b.txt   # check specific ones
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_FILES = ["requirements.txt"]

# A requirement line looks like: name[extras] <op> version ; marker
NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"
PINNED = re.compile(rf"^{NAME}(\[[^\]]+\])?==[^\s;#]+", re.ASCII)

# Lines that are not a package requirement at all.
PASSTHROUGH = re.compile(r"^\s*(-r|--|#|$)")


def problems(path: Path) -> list[tuple[int, str, str]]:
    """Return (line number, text, reason) for every unpinned requirement."""
    found: list[tuple[int, str, str]] = []
    for n, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line or PASSTHROUGH.match(raw):
            continue
        if PINNED.match(line):
            continue
        if re.search(r"[<>~!]=|>|<", line):
            reason = "a range: resolves to whatever exists at build time"
        elif re.match(rf"^{NAME}(\[[^\]]+\])?\s*$", line):
            reason = "no version at all: resolves to the newest release"
        else:
            reason = "not an exact == pin"
        found.append((n, raw.strip(), reason))
    return found


def main() -> int:
    files = [Path(a) for a in sys.argv[1:]] or [ROOT / f for f in DEFAULT_FILES]
    bad = 0
    for f in files:
        if not f.exists():
            print(f"  ! {f} does not exist")
            continue
        found = problems(f)
        if not found:
            print(f"  ok  {f.name}: every requirement is pinned")
            continue
        bad += len(found)
        print(f"  FAIL {f.name}: {len(found)} unpinned requirement(s)")
        for n, text, reason in found:
            print(f"       line {n}: {text}")
            print(f"               {reason}")

    if bad:
        print()
        print("  Pin them with ==. A range means the same commit can build a")
        print("  different program tomorrow, which is how nltk 3.10.1 killed the")
        print("  frozen backend on all three platforms with no change on our side.")
        print("  Upgrades come through dependabot, one package per pull request,")
        print("  approved by a human.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
