"""Tectonic compiles from the cache first, and reaches the network only for a
file the cache truly lacks.

Run normally, Tectonic answers a lookup the cache cannot satisfy by fetching
the online bundle's SHA256SUM -- including when LaTeX merely PROBES for an
optional file that does not exist anywhere (hyperref and imakeidx do this).
Offline that is fatal: the built installer could not compile an indexed
document with no network, measured on 2026-11-20, although every file it needs
was cached. With `--only-cached` the probe answers "not found" and it compiles.
"""

from __future__ import annotations

import pytest

from domain.paper_writer import compiler


@pytest.fixture
def calls(monkeypatch, tmp_path):
    seen = []

    def run_with(stderr_first):
        def fake_run(cmd, **kw):
            seen.append(cmd)
            class R:
                returncode = 0
                stdout = ""
                stderr = stderr_first if len(seen) == 1 else ""
            return R()
        monkeypatch.setattr(compiler.subprocess, "run", fake_run)
        (tmp_path / "main.tex").write_text("x")
        compiler._run_engine("tectonic", "tectonic", tmp_path / "main.tex", tmp_path)
        return seen
    return run_with


def test_the_first_pass_uses_only_the_cache(calls):
    seen = calls("")
    assert "--only-cached" in seen[0]
    assert len(seen) == 1, "a clean cached compile must not go to the network"


@pytest.mark.parametrize("missing", [
    "error: a.tex:2: ! LaTeX Error: File `beamer.cls' not found.",
    "error: a.tex:3: Font TU/lmr/m/it/10.95=[lmroman10-italic] at 10.95pt not loadable",
    "error: a.tex:19: Package tikz Error: I did not find the tikz library 'arrows.meta'.",
])
def test_a_file_the_cache_lacks_is_fetched_with_the_network(calls, missing):
    seen = calls(missing)
    assert len(seen) == 2
    assert "--only-cached" not in seen[1]


def test_offline_the_cached_result_stands(monkeypatch, tmp_path):
    """A user's own missing figure also says "not found". Offline, the retry
    can only fail on the network, and must not replace the cached result."""
    results = iter([
        ("error: main.tex:4: ! LaTeX Error: File `chart.png' not found.", "cached"),
        ('warning: failure requesting "SHA256SUM" from network\n'
         "caused by: Network is unreachable (os error 101)", "network"),
    ])

    def fake_run(cmd, **kw):
        err, tag = next(results)
        class R:
            returncode = 0
            stdout = tag
            stderr = err
        return R()

    monkeypatch.setattr(compiler.subprocess, "run", fake_run)
    (tmp_path / "main.tex").write_text("x")
    r = compiler._run_engine("tectonic", "tectonic", tmp_path / "main.tex", tmp_path)
    assert r.stdout == "cached"
