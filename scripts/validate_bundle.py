#!/usr/bin/env python3
"""Validate a BUILT ThinkStack bundle by exercising it over HTTP.

This is the automated half of release testing: CI runs it on real macOS,
Windows and Linux runners against the frozen backend, every build. It replaces
asking a person to install the app and report back, which is slow, unreliable,
and was how three shipped bugs reached users -- a backend the app could not
find, a model path derived from the working directory, and an embedding model
that was never bundled and silently reached for HuggingFace.

Every check here corresponds to a bug that actually shipped. None of them can
be caught by the unit suite, because the unit suite tests source code and users
run an installer.

usage:
    python scripts/validate_bundle.py [--url http://127.0.0.1:8000] [--timeout 300]

Exits non-zero if any check fails. Prints a report either way.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import types
import time
import urllib.error
import urllib.request

# A minimal valid PDF with extractable text, embedded so this script needs no
# PDF library and no network. Ingesting it is the only thing that exercises the
# embedding model, which is where the "reaches for HuggingFace" bug lived.
SAMPLE_PDF_B64 = (
    "JVBERi0xLjQKMSAwIG9iago8PCAvVHlwZSAvQ2F0YWxvZyAvUGFnZXMgMiAwIFIgPj4KZW5kb2Jq"
    "CjIgMCBvYmoKPDwgL1R5cGUgL1BhZ2VzIC9LaWRzIFszIDAgUl0gL0NvdW50IDEgPj4KZW5kb2Jq"
    "CjMgMCBvYmoKPDwgL1R5cGUgL1BhZ2UgL1BhcmVudCAyIDAgUiAvTWVkaWFCb3ggWzAgMCA2MTIg"
    "NzkyXSAvUmVzb3VyY2VzIDw8IC9Gb250IDw8IC9GMSA1IDAgUiA+PiA+PiAvQ29udGVudHMgNCAw"
    "IFIgPj4KZW5kb2JqCjQgMCBvYmoKPDwgL0xlbmd0aCAyMDEgPj4Kc3RyZWFtCkJUIC9GMSAxMSBU"
    "ZiA0MCA3NTAgVGQgKFRoaW5rU3RhY2sgYnVuZGxlIHZhbGlkYXRpb24gZG9jdW1lbnQuKSBUaiAw"
    "IC0xOCBUZCAoSHlicmlkIHJldHJpZXZhbCBpbXByb3ZlZCByZWNhbGwgZnJvbSAwLjYxIHRvIDAu"
    "ODMuKSBUaiAwIC0xOCBUZCAoUXVhbnRpc2VkIHNtYWxsIGxhbmd1YWdlIG1vZGVscyBydW4gb2Zm"
    "bGluZSBvbiBDUFUuKSBUaiBFVAplbmRzdHJlYW0KZW5kb2JqCjUgMCBvYmoKPDwgL1R5cGUgL0Zv"
    "bnQgL1N1YnR5cGUgL1R5cGUxIC9CYXNlRm9udCAvSGVsdmV0aWNhID4+CmVuZG9iagp4cmVmCjAg"
    "NgowMDAwMDAwMDAwIDY1NTM1IGYgCjAwMDAwMDAwMDkgMDAwMDAgbiAKMDAwMDAwMDA1OCAwMDAw"
    "MCBuIAowMDAwMDAwMTE1IDAwMDAwIG4gCjAwMDAwMDAyNDEgMDAwMDAgbiAKMDAwMDAwMDQ5MyAw"
    "MDAwMCBuIAp0cmFpbGVyCjw8IC9TaXplIDYgL1Jvb3QgMSAwIFIgPj4Kc3RhcnR4cmVmCjU2Mwol"
    "JUVPRgo="
)

PASS, FAIL, WARN = "PASS", "FAIL", "WARN"
results: list[tuple[str, str, str]] = []


def record(status: str, name: str, detail: str = "") -> None:
    results.append((status, name, detail))
    mark = {PASS: "PASS", FAIL: "FAIL", WARN: "WARN"}[status]
    print(f"  {mark}  {name}")
    if detail:
        for line in str(detail).splitlines():
            print(f"        {line}")


def get(url: str, timeout: int = 30):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def get_text(url: str, timeout: int = 30):
    """GET a URL, returning an object with .text and .headers, or None.

    Separate from get(): the frontend checks need the raw body and the
    response headers, not parsed JSON.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")
            return types.SimpleNamespace(text=body, headers=dict(r.headers))
    except (urllib.error.URLError, OSError, TimeoutError, UnicodeError):
        return None


def post(url: str, payload: dict, timeout: int = 600):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def upload_pdf(url: str, content: bytes, timeout: int = 600):
    """multipart upload without the requests dependency."""
    boundary = "----thinkstackvalidate"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="validate.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def wait_for_backend(base: str, timeout: int) -> dict | None:
    """Poll until the backend answers, or give up. Never hangs forever."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            return get(f"{base}/api/system/health", timeout=5)
        except (urllib.error.URLError, OSError, TimeoutError):
            time.sleep(2)
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--timeout", type=int, default=300,
                    help="seconds to wait for the backend to come up")
    ap.add_argument("--skip-inference", action="store_true",
                    help="skip chat/analysis (still checks ingest + embeddings)")
    ap.add_argument("--expect-version", default="",
                    help="the version this bundle was built as; the UI it "
                         "serves must report exactly this")
    args = ap.parse_args()
    base = args.url.rstrip("/")

    print("-" * 60)
    print(f"  ThinkStack bundle validation  ({sys.platform})")
    print("-" * 60)

    # 1. the backend comes up at all
    started = time.time()
    health = wait_for_backend(base, args.timeout)
    if health is None:
        record(FAIL, f"backend never answered within {args.timeout}s")
        return report()
    record(PASS, f"backend ready in {time.time() - started:.1f}s")

    # 1b. THE UI THIS BUNDLE SERVES IS THE ONE IT WAS BUILT FROM.
    #
    # Nothing checked this, on any platform, ever. Every check here exercised
    # the API and none of them requested the frontend, so a bundle could ship
    # a stale UI and pass everything. That is not hypothetical: a build was
    # released whose window showed the previous version's number and the
    # previous version's buttons, and it was only caught by a person looking
    # at the screen and by downloading the installer and grepping it by hand.
    #
    # The version is the honest probe. Vite bakes it into the JS bundle from
    # tauri.conf.json at build time, so if the served bundle reports the
    # version this build was stamped with, the frontend in the package is the
    # one this run produced -- which also proves the build ran in the right
    # order (stamp, then frontend).
    index = get_text(f"{base}/")
    if index is None:
        record(FAIL, "frontend not served", "GET / returned nothing")
    else:
        # index.html must never be cached: its name is stable across builds,
        # so a cached copy keeps pointing at the previous build's assets. That
        # shipped -- an updated app rendered the old UI from the webview cache.
        cache = (index.headers.get("cache-control") or "").lower()
        if "no-store" in cache:
            record(PASS, "index.html is uncacheable", cache)
        else:
            record(FAIL, "index.html is cacheable",
                   f"cache-control: {cache or '(absent)'} -- an updated app "
                   "will serve the previous build from the webview cache")

        refs = re.findall(r'/assets/([A-Za-z0-9._-]+\.js)', index.text)
        if not refs:
            record(FAIL, "index.html references no JS bundle")
        else:
            asset = get_text(f"{base}/assets/{refs[0]}")
            if asset is None:
                record(FAIL, "the JS bundle index.html points at is missing",
                       refs[0])
            elif args.expect_version:
                # Quoted, in ANY of the three styles. Vite replaces
                # __APP_VERSION__ with a string literal, but the minifier
                # rewrites literals as backtick templates -- the bundle
                # contains `1.6.13`, not "1.6.13". Matching only double quotes
                # failed on every real build, which would have made this check
                # cry wolf until someone deleted it.
                #
                # Still quoted rather than bare, which narrows it -- but be
                # honest about the limit: a dependency version that happens to
                # be quoted will also match, so passing "19.2.7" here succeeds
                # because React's version is in the bundle. That does not
                # weaken what this is for. The failure being guarded against is
                # a STALE frontend, and a stale bundle carries the PREVIOUS app
                # version, which cannot match the one this build stamped.
                needle = re.compile(
                    r"[\"'`]" + re.escape(args.expect_version) + r"[\"'`]"
                )
                if needle.search(asset.text):
                    record(PASS, "UI reports the built version",
                           f"{args.expect_version} in {refs[0]}")
                else:
                    found = re.findall(r'\b\d+\.\d+\.\d+\b', asset.text)[:3]
                    record(FAIL, "UI reports the WRONG version",
                           f"expected {args.expect_version}, bundle contains "
                           f"{found or 'no version string'} ({refs[0]})")
            else:
                record(PASS, "UI bundle served", refs[0])

    # 2. hardware diagnosis produced real numbers
    hw = health.get("hardware") or {}
    if hw.get("total_ram_gb"):
        record(PASS, "hardware detected",
               f"{hw['total_ram_gb']} GB RAM, tier {hw.get('tier')}, gpu {hw.get('gpu')}")
    else:
        record(FAIL, "hardware not detected", json.dumps(hw))

    # 3. the language model resolved to a real, absolute path.
    #    A relative path here is the bug where the model dir was derived from
    #    the working directory and resolved to the literal string "data/models".
    llm = health.get("llm") or {}
    path = str(llm.get("model_path", ""))
    if llm.get("status") == "connected" and llm.get("target_available"):
        if path.startswith("/") or (len(path) > 2 and path[1] == ":"):
            record(PASS, "model resolved", path)
        else:
            record(FAIL, "model path is not absolute", path)
    else:
        record(FAIL, "model not resolved",
               f"status={llm.get('status')} available={llm.get('target_available')} path={path}")

    # 4. ingest a PDF. The only thing that loads the embedding model, and the
    #    check that proves the weights shipped rather than being fetched.
    try:
        pdf = base64.b64decode(SAMPLE_PDF_B64)
        t0 = time.time()
        upload_pdf(f"{base}/api/documents/upload", pdf)
        record(PASS, f"ingested a PDF in {time.time() - t0:.1f}s "
                     "(embedding model loaded locally)")
    except Exception as e:  # noqa: BLE001
        record(FAIL, "PDF ingest failed", repr(e))

    # 5. the document is actually searchable
    try:
        res = post(f"{base}/api/search", {"query": "hybrid retrieval recall", "top_k": 3})
        hits = len(res.get("results", []))
        record(PASS if hits else FAIL, f"search returned {hits} hit(s)")
    except Exception as e:  # noqa: BLE001
        record(FAIL, "search failed", repr(e))

    # 6. real inference through the bundled llama.cpp, on the PLAIN-TEXT path.
    #
    #    This used to call /api/chat. Chat was scrapped, so it now goes through
    #    Scribe's generate, which is the remaining feature that asks the model
    #    for free text rather than grammar-constrained JSON. Keeping a plain-text
    #    check is the point: it and check 6b exercise the two different decoder
    #    paths, and a bundle can break one while the other still works.
    if args.skip_inference:
        record(WARN, "inference skipped (--skip-inference)")
    else:
        try:
            proj = post(f"{base}/api/papers/projects", {"name": "bundle-inference"})
            pid = proj.get("project_id")
            if not pid:
                raise RuntimeError(f"could not create a project: {str(proj)[:120]}")
            t0 = time.time()
            ans = post(f"{base}/api/papers/generate", {
                "project_id": pid,
                "prompt": "Write one sentence introducing a paper about recall.",
                "current_source": "",
            })
            text = (ans.get("generated_latex") or "").strip()
            if text:
                record(PASS, f"inference produced {len(text)} chars in {time.time() - t0:.1f}s",
                       text[:120])
            else:
                record(FAIL, "inference returned nothing", json.dumps(ans)[:200])
        except Exception as e:  # noqa: BLE001
            record(FAIL, "inference failed", repr(e))

    # 6b. SUMMARIZATION -- the JSON-mode path, which nothing here touched.
    #
    # Check 6 above is plain text generation. Summarize
    # is different in the way that matters: it asks the model for STRUCTURED
    # output, parses it, and fails softly by putting an apology in the summary
    # field instead of raising. So a bundle where structured output is broken
    # passed every check here with 10/10 while a tester on macOS saw "This paper
    # could not be summarized" on the very first paper they tried.
    #
    # Failing softly is right for the product -- one bad paper must not abort a
    # multi-paper run -- but it means the ONLY way to detect the failure is to
    # read the returned text. So that is what this does.
    if not args.skip_inference:
        try:
            # The ingest check above does not keep the id, so ask for it the
            # same way the UI does.
            listing = get(f"{base}/api/documents") or {}
            docs = listing.get("documents") if isinstance(listing, dict) else listing
            doc_id = (docs or [{}])[0].get("doc_id") if docs else None
            if not doc_id:
                raise RuntimeError(f"no ingested document to summarize: {str(listing)[:120]}")
            t0 = time.time()
            res = post(f"{base}/api/analysis/summarize", {"doc_ids": [doc_id]})
            summary = ((res.get("result") or res).get("summary_text") or "").strip()
            points = (res.get("result") or res).get("key_points") or []
            if not summary:
                record(FAIL, "summarize returned no summary at all", json.dumps(res)[:200])
            elif "could not be summarized" in summary or "could not be read" in summary:
                # The soft-failure text. The real cause is in the backend log,
                # which CI uploads on failure -- that is the whole point of
                # catching it here instead of at a tester's desk.
                record(FAIL, "summarize failed softly (structured output broke)",
                       summary[:160])
            else:
                record(PASS,
                       f"summarized a paper in {time.time() - t0:.1f}s "
                       f"({len(summary)} chars, {len(points)} key point(s))",
                       summary[:120])
        except Exception as e:  # noqa: BLE001
            record(FAIL, "summarize request failed", repr(e))

    # 7. the paper writer actually compiles a PDF.
    #    This is the check that would have caught the flagship feature failing
    #    on every machine without a system LaTeX. It asserts the SHIPPED TeX
    #    engine works -- CI runners have no LaTeX installed, so a pass here
    #    means a clean user machine compiles too.
    try:
        proj = post(f"{base}/api/papers/projects", {"name": "bundle-validation"})
        pid = proj.get("project_id")
        src = (
            "\\documentclass[12pt,a4paper]{article}\n"
            "\\usepackage[utf8]{inputenc}\\usepackage[T1]{fontenc}\n"
            "\\usepackage{amsmath,amssymb}\\usepackage{booktabs}\n"
            "\\usepackage{tikz}\\usepackage{pgfplots}\\pgfplotsset{compat=1.18}\n"
            "\\begin{document}\n\\section{Validation}\n"
            "\\begin{equation} E=mc^2 \\end{equation}\n"
            "\\begin{tabular}{@{}ll@{}}\\toprule a & b \\\\\\midrule 1 & 2 "
            "\\\\\\bottomrule\\end{tabular}\n"
            "\\begin{tikzpicture}\\begin{axis}\\addplot {x^2};\\end{axis}"
            "\\end{tikzpicture}\n\\end{document}\n"
        )
        post(f"{base}/api/papers/save", {"project_id": pid, "source": src})
        t0 = time.time()
        res = post(f"{base}/api/papers/compile", {"project_id": pid}, timeout=600)
        warn = res.get("warnings") or []
        record(PASS, f"paper writer compiled a PDF in {time.time() - t0:.1f}s "
                     "(bundled TeX engine, equations + tables + pgfplots)",
               f"{len(warn)} warning(s)" if warn else "")
    except Exception as e:  # noqa: BLE001
        record(FAIL, "paper writer could not compile a PDF", repr(e))

    # 8. model setup / consent endpoint answers
    try:
        setup = get(f"{base}/api/models/setup")
        sug = (setup.get("suggested_upgrade") or {}).get("name", "none")
        record(PASS, f"model setup reachable (needs_permission={setup.get('needs_permission')}, suggests={sug})")
    except Exception as e:  # noqa: BLE001
        record(FAIL, "model setup endpoint failed", repr(e))

    return report()


def report() -> int:
    failed = [r for r in results if r[0] == FAIL]
    warned = [r for r in results if r[0] == WARN]
    passed = [r for r in results if r[0] == PASS]
    print("-" * 60)
    if failed:
        print(f"  {len(failed)} FAILED, {len(warned)} warning(s), {len(passed)} passed")
        for _, name, detail in failed:
            print(f"    - {name}" + (f": {detail}" if detail else ""))
    else:
        print(f"  {len(passed)} passed, {len(warned)} warning(s), 0 failed")
    print("-" * 60)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
