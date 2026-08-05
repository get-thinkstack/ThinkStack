#!/usr/bin/env python3
"""write data/models/bundled.json, describing what THIS build ships.

Swapping the bundled model used to mean editing four places -- release.config
.json, catalog.BASE_MODEL, settings.llm_analysis_model and TASK_MODEL_MAP --
and missing one left routing pointing at a file that is not there. That friction
is exactly what would make shipping our own fine-tuned SLM painful.

Now the build emits a manifest beside the weights and the app reads that, so
changing the bundled model is ONE edit to release.config.json.

release.config.json accepts two shapes, and both work:

    "models": [
      "https://huggingface.co/.../qwen2.5-0.5b-instruct-q4_k_m.gguf"
    ]

    "models": [
      {
        "url": "https://.../thinkstack-slm-1b-v1-q4_k_m.gguf",
        "label": "ThinkStack SLM 1B",
        "tasks": ["general", "analysis"],
        "replaces": ["qwen2-5-0-5b-instruct-q4-k-m"]
      }
    ]

The plain string stays supported because every existing config uses it, and a
release pipeline is a bad place to require a migration. Missing fields are
filled from catalog.py where the model is one we already know, so the common
case needs no metadata at all.

`replaces` is the field that makes an UPDATE work rather than just an install:
it names the previously-bundled ids this model supersedes, so first run after an
upgrade deletes the old weights instead of leaving both. Without it retirement
would have to infer intent from absence -- which is how the beta-latest installs
got stranded.

usage:
    scripts/make_bundled_manifest.py [--config release.config.json]
                                     [--out data/models]
                                     [--check]

--check verifies an existing manifest matches the config without writing, for
CI to fail on drift rather than shipping a stale one.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_VERSION = 1
MANIFEST_NAME = "bundled.json"

_ID_STRIP = re.compile(r"[^a-z0-9]+")


def make_id(filename: str) -> str:
    """the same id the app derives, so the two agree.

    Mirrors domain/model_manager/registry.make_id. Duplicated deliberately:
    this script runs during a build, where importing the application package
    would drag in its dependencies (pydantic, httpx) for one string transform.
    tests/test_bundled_manifest.py asserts the two never diverge.
    """
    s = filename.strip().lower()
    if s.endswith(".gguf"):
        s = s[: -len(".gguf")]
    return _ID_STRIP.sub("-", s).strip("-")


def _catalog_defaults(filename: str) -> dict:
    """label / size / tasks from catalog.py, when it knows this model.

    Best-effort: the script must still work in a build environment where the
    app's dependencies are not installed.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from domain.model_manager.catalog import by_name  # noqa: PLC0415

        spec = by_name(filename)
        if spec is None:
            return {}
        return {"label": spec.label, "size_gb": spec.size_gb, "tasks": list(spec.tasks)}
    except Exception:  # noqa: BLE001 - the manifest is still valid without it
        return {}


def _measure(models_dir: Path, filename: str) -> float | None:
    """the real on-disk size in GB, or None when the file is not here.

    None rather than 0.0, because 0.0 is a legitimate measurement -- a 3 MB
    file rounds to it -- and `measured or declared` would then silently prefer
    a stale declared size over the truth. The same `or`-on-a-float mistake
    approved an oversized model in the router; it is worth naming twice.
    """
    try:
        return round((models_dir / filename).stat().st_size / (1024 ** 3), 2)
    except OSError:
        return None


def build_manifest(config: dict, models_dir: Path) -> dict:
    """the manifest this config describes."""
    entries = []
    for item in config.get("models", []):
        if isinstance(item, str):
            item = {"url": item}
        if not isinstance(item, dict):
            continue

        url = str(item.get("url") or "").strip()
        filename = str(item.get("file") or "").strip() or url.rsplit("/", 1)[-1]
        if not filename:
            continue

        defaults = _catalog_defaults(filename)
        measured = _measure(models_dir, filename)

        entries.append({
            "id": str(item.get("id") or make_id(filename)),
            "file": filename,
            "label": str(item.get("label") or defaults.get("label") or Path(filename).stem),
            # measured beats declared beats catalog: a build that changed the
            # quantisation should not report the old size.
            "size_gb": (
                measured if measured is not None
                else float(item.get("size_gb") or defaults.get("size_gb") or 0.0)
            ),
            "tasks": list(item.get("tasks") or defaults.get("tasks") or ["general"]),
            "replaces": list(item.get("replaces") or []),
        })

    return {"version": SCHEMA_VERSION, "models": entries}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(ROOT / "release.config.json"))
    ap.add_argument("--out", default=str(ROOT / "data" / "models"),
                    help="directory to write bundled.json into")
    ap.add_argument("--check", action="store_true",
                    help="verify the existing manifest matches, do not write")
    args = ap.parse_args()

    try:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        print(f"cannot read {args.config}: {e}", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    manifest = build_manifest(config, out_dir)

    # An EMPTY manifest is valid and is the normal case: ThinkStack ships no
    # weights, and first-run setup asks the user which model to install. It
    # still has to be written, because its absence means something different --
    # BundledManifest.load falls back to the catalog when the file is missing,
    # which would tell the app a model is bundled when none is.

    target = out_dir / MANIFEST_NAME

    if args.check:
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print(f"::error::{target} is missing or unreadable; run "
                  f"scripts/make_bundled_manifest.py", file=sys.stderr)
            return 1
        # Compare ignoring size, which legitimately differs between a machine
        # that has the weights and one that does not.
        def strip(m):
            return [{k: v for k, v in e.items() if k != "size_gb"} for e in m["models"]]
        if strip(existing) != strip(manifest):
            print("::error::bundled.json does not match release.config.json",
                  file=sys.stderr)
            return 1
        print("bundled.json matches release.config.json")
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {target}")
    for e in manifest["models"]:
        replaces = f"  replaces {', '.join(e['replaces'])}" if e["replaces"] else ""
        print(f"  {e['label']}  ({e['size_gb']} GB)  -> {', '.join(e['tasks'])}{replaces}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
