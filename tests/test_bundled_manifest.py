"""generating data/models/bundled.json from release.config.json.

This script decides what an installed app believes it shipped with, so the
tests that matter are the ones about SWAPPING the bundled model -- the whole
reason the manifest exists is that changing it used to mean editing four files
and missing one left routing pointing at weights that were not there.

Run as a subprocess, exactly the way build.sh and CI run it, so an import-time
break or an argparse mistake is caught here rather than in a release.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "make_bundled_manifest.py"


def run(config: dict, out_dir: Path, tmp_path: Path, *extra: str):
    cfg = tmp_path / "release.config.json"
    cfg.write_text(json.dumps(config), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--config", str(cfg), "--out", str(out_dir), *extra],
        capture_output=True, text=True,
    )


def manifest_of(out_dir: Path) -> dict:
    return json.loads((out_dir / "bundled.json").read_text(encoding="utf-8"))


class TestBothConfigShapes:
    def test_a_plain_url_string_still_works(self, tmp_path):
        # every config that exists today uses this; a release pipeline is a bad
        # place to require a migration.
        out = tmp_path / "models"
        r = run({"models": ["https://h/qwen2.5-0.5b-instruct-q4_k_m.gguf"]}, out, tmp_path)
        assert r.returncode == 0, r.stderr
        m = manifest_of(out)["models"][0]
        assert m["file"] == "qwen2.5-0.5b-instruct-q4_k_m.gguf"
        assert m["id"] == "qwen2-5-0-5b-instruct-q4-k-m"

    def test_a_rich_entry_carries_its_metadata(self, tmp_path):
        out = tmp_path / "models"
        r = run({"models": [{
            "url": "https://h/thinkstack-slm-1b-v1-q4_k_m.gguf",
            "label": "ThinkStack SLM 1B",
            "tasks": ["general", "analysis"],
            "replaces": ["qwen2-5-0-5b-instruct-q4-k-m"],
        }]}, out, tmp_path)
        assert r.returncode == 0, r.stderr
        m = manifest_of(out)["models"][0]
        assert m["label"] == "ThinkStack SLM 1B"
        assert m["tasks"] == ["general", "analysis"]
        assert m["replaces"] == ["qwen2-5-0-5b-instruct-q4-k-m"]

    def test_mixed_shapes_in_one_config(self, tmp_path):
        out = tmp_path / "models"
        r = run({"models": [
            "https://h/a-q4_k_m.gguf",
            {"url": "https://h/b-q4_k_m.gguf", "label": "B"},
        ]}, out, tmp_path)
        assert r.returncode == 0, r.stderr
        assert [m["file"] for m in manifest_of(out)["models"]] == [
            "a-q4_k_m.gguf", "b-q4_k_m.gguf"]


class TestTheSwapScenario:
    """what a release that changes the bundled model must produce."""

    def test_replaces_survives_into_the_manifest(self, tmp_path):
        # without this field, first run after the update cannot tell an
        # obsolete bundled model from one the user wants kept.
        out = tmp_path / "models"
        run({"models": [{"url": "https://h/new-q4_k_m.gguf",
                         "replaces": ["old-one", "older-one"]}]}, out, tmp_path)
        assert manifest_of(out)["models"][0]["replaces"] == ["old-one", "older-one"]

    def test_the_app_can_read_what_the_script_writes(self, tmp_path):
        # the two halves are written in different files and must agree
        from domain.model_manager.manifest import BundledManifest

        out = tmp_path / "models"
        run({"models": [{"url": "https://h/slm-q4_k_m.gguf",
                         "label": "SLM", "tasks": ["general", "analysis"],
                         "replaces": ["old"]}]}, out, tmp_path)

        loaded = BundledManifest.load(out)
        assert [m.label for m in loaded.models] == ["SLM"]
        assert loaded.files_for("analysis") == ["slm-q4_k_m.gguf"]
        assert loaded.replaced_ids() == {"old"}

    def test_ids_match_the_ones_the_app_derives(self, tmp_path):
        # make_id is duplicated in the script (it must run without the app's
        # dependencies installed). This is the tripwire for that duplication.
        from domain.model_manager.registry import make_id

        out = tmp_path / "models"
        for filename in ("Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
                         "gemma-3-1b-it-Q4_K_M.gguf",
                         "weird.name_with-bits.gguf"):
            run({"models": [f"https://h/{filename}"]}, out, tmp_path)
            assert manifest_of(out)["models"][0]["id"] == make_id(filename)


class TestDefaultsAndMeasurement:
    def test_a_known_model_takes_its_label_from_the_catalog(self, tmp_path):
        from domain.model_manager.catalog import BASE_MODEL

        out = tmp_path / "models"
        run({"models": [f"https://h/{BASE_MODEL.name}"]}, out, tmp_path)
        assert manifest_of(out)["models"][0]["label"] == BASE_MODEL.label

    def test_an_unknown_model_still_gets_a_usable_entry(self, tmp_path):
        out = tmp_path / "models"
        run({"models": ["https://h/nobody-has-heard-of-this-q4_k_m.gguf"]}, out, tmp_path)
        m = manifest_of(out)["models"][0]
        assert m["label"] and m["tasks"] == ["general"]

    def test_the_measured_size_beats_a_declared_one(self, tmp_path):
        # a build that changed the quantisation must not report the old size
        out = tmp_path / "models"
        out.mkdir(parents=True)
        (out / "m-q4_k_m.gguf").write_bytes(b"GGUF" + b"\0" * (64 * 1024 * 1024))
        run({"models": [{"url": "https://h/m-q4_k_m.gguf", "size_gb": 99.0}]}, out, tmp_path)
        assert 0 < manifest_of(out)["models"][0]["size_gb"] < 1.0


class TestFailureModes:
    def test_an_empty_model_list_is_valid_and_still_written(self, tmp_path):
        """ThinkStack ships no weights, so this is the normal case.

        The file must still be WRITTEN. Its absence means something different:
        BundledManifest.load falls back to the catalog when there is no file,
        which would tell the app a model is bundled when none is.
        """
        out = tmp_path / "models"
        r = run({"models": []}, out, tmp_path)
        assert r.returncode == 0, r.stderr
        assert manifest_of(out)["models"] == []

    def test_a_missing_config_is_reported_not_crashed(self, tmp_path):
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(tmp_path / "nope.json"),
             "--out", str(tmp_path)],
            capture_output=True, text=True,
        )
        assert r.returncode == 1
        assert "cannot read" in r.stderr

    def test_entries_with_no_url_are_skipped_not_fatal(self, tmp_path):
        out = tmp_path / "models"
        r = run({"models": [{"label": "ghost"}, "https://h/real-q4_k_m.gguf"]}, out, tmp_path)
        assert r.returncode == 0
        assert [m["file"] for m in manifest_of(out)["models"]] == ["real-q4_k_m.gguf"]


class TestCheckMode:
    def test_check_passes_on_a_matching_manifest(self, tmp_path):
        out = tmp_path / "models"
        cfg = {"models": ["https://h/a-q4_k_m.gguf"]}
        run(cfg, out, tmp_path)
        assert run(cfg, out, tmp_path, "--check").returncode == 0

    def test_check_fails_when_the_config_moved_on(self, tmp_path):
        out = tmp_path / "models"
        run({"models": ["https://h/a-q4_k_m.gguf"]}, out, tmp_path)
        r = run({"models": ["https://h/b-q4_k_m.gguf"]}, out, tmp_path, "--check")
        assert r.returncode == 1
        assert "does not match" in r.stderr

    def test_check_fails_when_the_manifest_is_absent(self, tmp_path):
        r = run({"models": ["https://h/a-q4_k_m.gguf"]}, tmp_path / "empty", tmp_path, "--check")
        assert r.returncode == 1

    def test_check_writes_nothing(self, tmp_path):
        out = tmp_path / "models"
        run({"models": ["https://h/a-q4_k_m.gguf"]}, out, tmp_path, "--check")
        assert not (out / "bundled.json").exists()


class TestTheRealConfig:
    def test_the_repo_config_produces_a_valid_manifest(self, tmp_path):
        """the config we actually ship must work, not just synthetic ones."""
        from domain.model_manager.manifest import BundledManifest

        root = Path(__file__).resolve().parent.parent
        out = tmp_path / "models"
        r = subprocess.run(
            [sys.executable, str(SCRIPT), "--config", str(root / "release.config.json"),
             "--out", str(out)],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, r.stderr
        loaded = BundledManifest.load(out)
        # Currently empty by design. If a model is ever bundled again it must
        # claim `general`, or a fresh install has nothing for the default task.
        if loaded.models:
            assert any("general" in m.tasks for m in loaded.models)
