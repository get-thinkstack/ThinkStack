"""Every starter template compiles with NO network, from the warmed cache.

The promise "a clean machine compiles offline" was never checked as stated:
CI compiles with a network, so a missing cache file is silently downloaded.
On 2026-11-19, compiling with `--only-cached` against a cache built exactly as
CI builds it, four of six templates produced no PDF (TikZ libraries, then font
sizes, were never warmed) and Beamer was absent.

Heavy: needs the real engine and a cache warmed by `scripts/fetch-tex.sh`
(default `data/tex`, or THINKSTACK_TEX_DIR). Run with `pytest -m heavy`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from domain.paper_writer import templates

ROOT = Path(__file__).resolve().parent.parent
TEX = Path(os.environ.get("THINKSTACK_TEX_DIR", ROOT / "data" / "tex"))
ENGINE = TEX / ("tectonic.exe" if os.name == "nt" else "tectonic")

pytestmark = [
    pytest.mark.heavy,
    pytest.mark.skipif(
        not (ENGINE.exists() and (TEX / ".cache-warmed").exists()),
        reason="needs a cache warmed by scripts/fetch-tex.sh",
    ),
]


@pytest.fixture(scope="module")
def cache(tmp_path_factory):
    # a copy: compiling writes to the cache, and the shipped one must not change
    dest = tmp_path_factory.mktemp("cache") / "cache"
    shutil.copytree(TEX / "cache", dest)
    return dest


@pytest.mark.parametrize("template_id", [t.id for t in templates.ALL])
def test_the_template_compiles_offline(template_id, cache, tmp_path):
    tex = tmp_path / f"{template_id}.tex"
    tex.write_text(templates.render(template_id, "Offline"), encoding="utf-8")
    run = subprocess.run(
        [str(ENGINE), "-X", "compile", str(tex), "--outdir", str(tmp_path),
         "--only-cached", "-Z", "continue-on-errors"],
        env={**os.environ, "TECTONIC_CACHE_DIR": str(cache)},
        capture_output=True, text=True, timeout=300,
    )
    errors = [ln for ln in run.stderr.splitlines() if ln.startswith("error")]
    pdf = tmp_path / f"{template_id}.pdf"
    assert pdf.exists() and pdf.stat().st_size > 0, "\n".join(errors[:5])
    assert not errors, "\n".join(errors[:5])


# Documents people write that are NOT starter templates. The default size is
# 10pt (size10.clo), which no warm document used until 2026-11-20, so any plain
# \documentclass{article} failed offline -- including the bundle validator's
# figure and index checks, which passed in CI only because CI has a network.
ORDINARY = {
    "plain-10pt-figure": "\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\n"
                         "Hello.\\par\\includegraphics[width=2cm]{dot.png}\n\\end{document}\n",
    "plain-11pt": "\\documentclass[11pt]{article}\n\\begin{document}\n\\section{A}Text "
                  "\\emph{em} $x^2$.\n\\end{document}\n",
    # the bundle validator's index document, exactly
    "index": "\\documentclass{article}\n\\usepackage{imakeidx}\\usepackage{hyperref}\n"
             "\\makeindex\n\\begin{document}\nFederated learning\\index{federated learning}.\n"
             "\\newpage\nPrivacy\\index{privacy!differential}.\n\\printindex\n\\end{document}\n",
    "report-class": "\\documentclass{report}\n\\begin{document}\n\\chapter{A}Text.\n\\end{document}\n",
    "book-class": "\\documentclass{book}\n\\begin{document}\n\\chapter{A}Text.\n\\end{document}\n",
}


def _png(path):
    import struct
    import zlib
    def chunk(t, b):
        return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


def _compile(tex, cache, outdir):
    return subprocess.run(
        [str(ENGINE), "-X", "compile", str(tex), "--outdir", str(outdir),
         "--only-cached", "-Z", "continue-on-errors", "--keep-intermediates"],
        env={**os.environ, "TECTONIC_CACHE_DIR": str(cache)},
        capture_output=True, text=True, timeout=300,
    )


@pytest.mark.parametrize("name", sorted(ORDINARY))
def test_an_ordinary_document_compiles_offline(name, cache, tmp_path):
    _png(tmp_path / "dot.png")
    tex = tmp_path / f"{name}.tex"
    tex.write_text(ORDINARY[name], encoding="utf-8")
    run = _compile(tex, cache, tmp_path)
    # The app's second pass: indexing.py turns the .idx into the .ind, and the
    # engine runs again to typeset it, which needs more than the first pass.
    from domain.paper_writer.indexing import write_index
    if write_index(tmp_path, stem=name):
        run = _compile(tex, cache, tmp_path)
    errors = [ln for ln in run.stderr.splitlines() if ln.startswith("error")]
    pdf = tmp_path / f"{name}.pdf"
    assert pdf.exists() and pdf.stat().st_size > 0, "\n".join(errors[:5])
    assert not errors, "\n".join(errors[:5])
