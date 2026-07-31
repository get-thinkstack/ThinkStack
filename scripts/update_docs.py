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
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Files that may contain markers. Anything not listed is never touched.
TARGETS = [
    "README.md",
    "CONTRIBUTING.md",
    "docs/ABOUT.md",
    "docs/FEATURES.md",
    "docs/FUTURE_WORK.md",
    "scripts/README.md",
]


# ---------------------------------------------------------------- facts


def _version() -> str:
    return json.loads((ROOT / "src-tauri" / "tauri.conf.json").read_text())["version"]


def _count_lines(paths) -> int:
    return sum(len(p.read_text(encoding="utf-8", errors="replace").splitlines()) for p in paths)


def _python_modules() -> list[Path]:
    out = []
    for d in ("api", "domain", "infrastructure"):
        out += sorted((ROOT / d).rglob("*.py"))
    out += [ROOT / "main.py", ROOT / "config.py"]
    return [p for p in out if p.is_file() and p.name != "__init__.py"]


def _test_modules() -> list[Path]:
    return sorted((ROOT / "tests").glob("test_*.py"))


def _test_count() -> int:
    """Collected test count. Falls back to 0 if pytest cannot run here."""
    try:
        # NOT -q: the quiet form lists per-file counts and omits the total.
        # The summary line is "308 tests collected in 0.88s".
        r = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only"],
            cwd=ROOT, capture_output=True, text=True, timeout=300,
        )
        m = re.search(r"(\d+)\s+tests?\s+collected", r.stdout)
        return int(m.group(1)) if m else 0
    except Exception:  # noqa: BLE001
        return 0


def _endpoint_count() -> int:
    """Routes declared across the api routers, counted from the decorators."""
    methods = {"get", "post", "put", "delete", "patch"}
    total = 0
    for f in sorted((ROOT / "api").glob("routes_*.py")):
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            for dec in getattr(node, "decorator_list", []):
                if (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and dec.func.attr in methods and dec.args):
                    total += 1
    return total


def facts() -> dict[str, str]:
    py = _python_modules()
    tests = _test_modules()
    fe = sorted((ROOT / "frontend" / "src").rglob("*.jsx")) + \
         sorted((ROOT / "frontend" / "src").rglob("*.js"))
    rs = sorted((ROOT / "src-tauri" / "src").glob("*.rs"))
    adr = len(re.findall(r"^## \d{4}-\d{2}-\d{2}", (ROOT / "docs" / "ADR.md").read_text(), re.M))
    n_tests = _test_count()

    return {
        "version": _version(),
        "tests": f"{n_tests} tests across {len(tests)} modules" if n_tests
                 else f"{len(tests)} test modules",
        "test_count": str(n_tests) if n_tests else "",
        "python_loc": f"{_count_lines(py):,} lines across {len(py)} modules",
        "frontend_loc": f"{_count_lines(fe):,} lines, "
                        f"{len([p for p in fe if p.suffix == '.jsx'])} components",
        "rust_loc": f"{_count_lines(rs):,} lines",
        "endpoints": str(_endpoint_count()),
        "adr_count": str(adr),
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
