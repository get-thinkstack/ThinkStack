"""The API contract: every caller must hit a route the backend defines.

This exists because a call site was written from memory rather than from the
code. `scripts/validate_bundle.py` posted to `/api/papers/create`; the actual
route is `/api/papers/projects`, and the only symptom was a 405 at runtime --
long after the code was written and reviewed.

Nothing else catches this. The route table lives in Python and the callers live
in JavaScript, so no type checker spans the gap, and the unit suite mocks the
API away. A test is the only place the two halves can be compared.

If this fails, one of two things is true: a route was renamed and its callers
were not updated, or a caller was written against a path that never existed.
Both are the same bug -- fix the caller or restore the route.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HTTP_METHODS = {"GET", "POST", "PUT", "DELETE", "PATCH"}


def _placeholder(path: str) -> str:
    """Normalise `{doc_id}` and `${docId}` to a single form so they compare."""
    return re.sub(r"(\$\{[^}]+\}|\{[^}]+\})", "{}", path).rstrip("/")


def _router_prefixes() -> dict[str, str]:
    """Map `routes_x` -> the prefix main.py mounts it under."""
    main = (ROOT / "main.py").read_text(encoding="utf-8")
    return {
        m.group(1): m.group(2)
        for m in re.finditer(r'include_router\((\w+)_router,\s*prefix="([^"]+)"', main)
    }


def defined_routes() -> set[tuple[str, str]]:
    """(METHOD, full path) for every route the backend declares."""
    prefixes = _router_prefixes()
    found: set[tuple[str, str]] = set()
    for f in sorted((ROOT / "api").glob("routes_*.py")):
        prefix = prefixes.get(f.stem.replace("routes_", ""), "")
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            for dec in getattr(node, "decorator_list", []):
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                method = dec.func.attr.upper()
                if method not in HTTP_METHODS or not dec.args:
                    continue
                arg = dec.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add((method, _placeholder(prefix + arg.value)))
    return found


def frontend_calls() -> set[tuple[str, str]]:
    """(METHOD, full path) for every call in the frontend's api client."""
    src = (ROOT / "frontend" / "src" / "utils" / "api.js").read_text(encoding="utf-8")
    calls: set[tuple[str, str]] = set()
    pattern = r"request\(\s*[`'\"]([^`'\"]+)[`'\"](?:\s*,\s*\{[^}]*method:\s*'(\w+)')?"
    for m in re.finditer(pattern, src):
        path = m.group(1).split("?")[0]
        calls.add(((m.group(2) or "GET").upper(), _placeholder("/api" + path)))
    return calls


def validator_calls() -> set[tuple[str, str]]:
    """(METHOD, full path) for every call in scripts/validate_bundle.py."""
    src = (ROOT / "scripts" / "validate_bundle.py").read_text(encoding="utf-8")
    calls: set[tuple[str, str]] = set()
    for m in re.finditer(r'(get|post|upload_pdf)\(f?"\{base\}(/api/[^"]+)"', src):
        method = "GET" if m.group(1) == "get" else "POST"
        calls.add((method, _placeholder(m.group(2))))
    return calls


class TestApiContract:
    def test_backend_declares_routes(self):
        """Guard the guard: if parsing breaks, the checks below pass vacuously."""
        routes = defined_routes()
        assert len(routes) > 20, f"only found {len(routes)} routes - parsing is broken"
        assert ("GET", "/api/system/health") in routes

    def test_callers_were_found(self):
        """Same guard for the caller side: an empty set proves nothing."""
        assert frontend_calls(), "no frontend calls parsed - the regex has drifted"
        assert validator_calls(), "no validator calls parsed - the regex has drifted"

    @pytest.mark.parametrize("source", ["frontend", "validator"])
    def test_every_call_hits_a_real_route(self, source):
        routes = defined_routes()
        calls = frontend_calls() if source == "frontend" else validator_calls()
        missing = sorted(c for c in calls if c not in routes)
        assert not missing, (
            f"{source} calls routes the backend does not define:\n"
            + "\n".join(f"  {m} {p}" for m, p in missing)
            + "\n\nEither the route was renamed and this caller was missed, or the "
              "caller was written from memory. `/api/papers/create` vs the real "
              "`/api/papers/projects` is how this test came to exist."
        )
