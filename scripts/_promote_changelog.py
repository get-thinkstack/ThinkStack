#!/usr/bin/env python3
"""Promote CHANGELOG.md's [Unreleased] section to a released version.

Called by scripts/release.sh during a stable release. Keeping this in the release
script means the changelog is written while a change is fresh in its PR, rather
than reconstructed from `git log` weeks later when nobody remembers which commits
were user-visible.

Every failure mode here is non-fatal: a missing file, a missing section, or an
empty one leaves the changelog untouched and lets the release proceed. Blocking a
release over a documentation file would be the wrong trade.

usage: scripts/_promote_changelog.py <version>
"""

import datetime
import pathlib
import re
import sys

PLACEHOLDER = "Work merged but not yet tagged."


def main() -> int:
    if len(sys.argv) < 2:
        print("  changelog: no version given, skipped")
        return 0
    version = sys.argv[1]

    path = pathlib.Path("CHANGELOG.md")
    if not path.is_file():
        print("  changelog: CHANGELOG.md not found, skipped")
        return 0

    text = path.read_text(encoding="utf-8")

    # capture [Unreleased] up to the next version heading (or end of file)
    match = re.search(
        r"^## \[Unreleased\]\s*\n(.*?)(?=^## \[|\Z)", text, re.M | re.S
    )
    if not match:
        print("  changelog: no [Unreleased] section, left alone")
        return 0

    # Strip the placeholder and every horizontal rule, then check whether any
    # real content is left. Dropping only a *trailing* rule is not enough: once a
    # release has been promoted, the section is just the placeholder plus a rule,
    # and a lone "---" would otherwise read as content and promote an empty entry.
    body = match.group(1).replace(PLACEHOLDER, "")
    body = "\n".join(ln for ln in body.splitlines() if ln.strip() != "---").strip()

    if not body:
        print("  changelog: [Unreleased] is empty, left alone")
        return 0

    if re.search(rf"^## \[{re.escape(version)}\]", text, re.M):
        print(f"  changelog: [{version}] already present, left alone")
        return 0

    today = datetime.date.today().isoformat()
    fresh = f"## [Unreleased]\n\n{PLACEHOLDER}\n\n---\n\n"
    entry = f"## [{version}] - {today}\n\n{body}\n\n---\n\n"

    path.write_text(text[: match.start()] + fresh + entry + text[match.end():],
                    encoding="utf-8")
    print(f"  changelog: [Unreleased] -> [{version}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
