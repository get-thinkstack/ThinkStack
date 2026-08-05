"""the bundled manifest, and reconciling it against the registry on update.

These tests are about what happens ACROSS versions -- the app installed one set
of models, this build ships another, and something has to decide what to add,
what to delete, and what to leave alone. Everything runs against real files in
tmp_path, because the invariant that matters most is which files survive.

Three rules are asserted repeatedly, because breaking any of them destroys user
data or silently undoes a deliberate choice:

  * a file we did not create is never deleted (``managed``)
  * a task assignment a human made is never overwritten (``user_assigned``)
  * a bundled model the user removed is never silently reinstalled (opt-out)
"""

from __future__ import annotations

import json
from pathlib import Path

from domain.model_manager.manifest import BundledManifest, BundledModel
from domain.model_manager.reconcile import reconcile_and_save, reconcile_bundled
from domain.model_manager.registry import GGUF_MAGIC, ModelEntry, Registry


def gguf(path: Path, size_mb: float = 1.0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(GGUF_MAGIC)
        f.write(b"\0" * max(0, int(size_mb * 1024 * 1024) - 4))
    return path


def write_manifest(bundled_dir: Path, *models: dict) -> Path:
    bundled_dir.mkdir(parents=True, exist_ok=True)
    p = bundled_dir / "bundled.json"
    p.write_text(json.dumps({"version": 1, "models": list(models)}), encoding="utf-8")
    return p


class TestManifestLoading:
    def test_reads_a_manifest(self, tmp_path):
        write_manifest(tmp_path, {
            "id": "slm-1b", "file": "slm-1b.gguf", "label": "SLM 1B",
            "size_gb": 0.68, "tasks": ["general", "analysis"],
            "replaces": ["qwen2-5-0-5b"],
        })
        m = BundledManifest.load(tmp_path)
        assert [x.id for x in m.models] == ["slm-1b"]
        assert m.files_for("analysis") == ["slm-1b.gguf"]
        assert m.replaced_ids() == {"qwen2-5-0-5b"}

    def test_a_missing_manifest_falls_back_to_the_catalog(self, tmp_path):
        # every build shipped before this feature has weights and no manifest;
        # returning nothing would retire a model sitting right there.
        m = BundledManifest.load(tmp_path / "does-not-exist")
        assert m.models, "the catalog fallback must not be empty"
        assert any("qwen" in x.file for x in m.models)

    def test_corrupt_manifest_falls_back_rather_than_raising(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "bundled.json").write_text("{ not json", encoding="utf-8")
        assert BundledManifest.load(tmp_path).models

    def test_an_entry_with_no_file_is_dropped(self, tmp_path):
        write_manifest(tmp_path, {"id": "ghost", "label": "Ghost"})
        assert BundledManifest.load(tmp_path).models == ()

    def test_id_defaults_to_the_filename(self, tmp_path):
        write_manifest(tmp_path, {"file": "Some-Model-Q4_K_M.gguf"})
        assert BundledManifest.load(tmp_path).models[0].id == "some-model-q4-k-m"

    def test_a_newer_schema_is_still_read(self, tmp_path):
        # unlike the registry we never WRITE this file, so a newer one is safe
        tmp_path.mkdir(parents=True, exist_ok=True)
        (tmp_path / "bundled.json").write_text(json.dumps({
            "version": 99,
            "models": [{"id": "a", "file": "a.gguf", "tasks": ["analysis"]}],
        }), encoding="utf-8")
        assert BundledManifest.load(tmp_path).files_for("analysis") == ["a.gguf"]


class TestFirstInstall:
    def test_a_bundled_model_is_copied_and_registered(self, tmp_path):
        bundled, models = tmp_path / "bundled", tmp_path / "models"
        gguf(bundled / "slm.gguf")
        m = BundledManifest(models=(BundledModel(
            id="slm", file="slm.gguf", label="SLM", tasks=("general",)),))

        r = Registry()
        report = reconcile_bundled(r, m, bundled_dir=bundled, models_dir=models)

        assert (models / "slm.gguf").is_file()
        entry = r.get("slm")
        assert entry.origin == "bundled" and entry.managed is True
        assert entry.tasks == ("general",)
        assert entry.user_assigned is False
        assert report.installed == ["SLM"]

    def test_a_manifest_model_that_was_not_shipped_is_reported(self, tmp_path):
        # the real cause: a release.config.json entry whose download failed at
        # build time. must be visible, not silent.
        bundled, models = tmp_path / "bundled", tmp_path / "models"
        bundled.mkdir(parents=True)
        m = BundledManifest(models=(BundledModel(id="x", file="missing.gguf"),))
        report = reconcile_bundled(Registry(), m, bundled_dir=bundled, models_dir=models)
        assert report.errors and "not shipped" in report.errors[0]

    def test_source_checkout_where_src_equals_dst_does_not_truncate(self, tmp_path):
        # bundled_dir == models_dir in a checkout; copying a file onto itself
        # would empty it.
        d = tmp_path / "models"
        p = gguf(d / "slm.gguf", size_mb=2)
        before = p.stat().st_size
        m = BundledManifest(models=(BundledModel(id="slm", file="slm.gguf"),))
        reconcile_bundled(Registry(), m, bundled_dir=d, models_dir=d)
        assert p.stat().st_size == before


class TestRetirement:
    def _setup(self, tmp_path):
        bundled, models = tmp_path / "bundled", tmp_path / "models"
        gguf(bundled / "new.gguf")
        old = gguf(models / "old.gguf", size_mb=8)
        r = Registry()
        r.upsert(ModelEntry(id="old", path=str(old), label="Old 0.5B",
                            size_gb=0.5, origin="bundled", managed=True,
                            tasks=("general", "analysis")))
        m = BundledManifest(models=(BundledModel(
            id="new", file="new.gguf", label="New 1B",
            tasks=("general",), replaces=("old",)),))
        return r, m, bundled, models, old

    def test_the_superseded_model_is_deleted_and_unregistered(self, tmp_path):
        r, m, bundled, models, old = self._setup(tmp_path)
        report = reconcile_bundled(r, m, bundled_dir=bundled, models_dir=models)

        assert not old.exists(), "we shipped it, so we clean it up"
        assert r.get("old") is None
        assert r.get("new") is not None
        assert report.retired == ["Old 0.5B"]
        assert report.reclaimed_gb > 0

    def test_a_task_only_the_old_model_covered_is_inherited(self, tmp_path):
        # without this, replacing the bundled model silently leaves `analysis`
        # unassigned and every summary quietly downgrades.
        r, m, bundled, models, _ = self._setup(tmp_path)
        reconcile_bundled(r, m, bundled_dir=bundled, models_dir=models)
        assert "analysis" in r.get("new").tasks

    def test_an_inherited_task_is_not_marked_as_user_intent(self, tmp_path):
        # a release decision must stay overwritable by the next release
        r, m, bundled, models, _ = self._setup(tmp_path)
        reconcile_bundled(r, m, bundled_dir=bundled, models_dir=models)
        assert r.get("new").user_assigned is False

    def test_an_unmanaged_entry_is_unregistered_but_its_file_survives(self, tmp_path):
        bundled, models = tmp_path / "bundled", tmp_path / "models"
        gguf(bundled / "new.gguf")
        mine = gguf(tmp_path / "mine" / "mine.gguf")
        r = Registry()
        r.upsert(ModelEntry(id="old", path=str(mine), label="Mine",
                            origin="bundled", managed=False, tasks=("general",)))
        m = BundledManifest(models=(BundledModel(
            id="new", file="new.gguf", replaces=("old",)),))

        reconcile_bundled(r, m, bundled_dir=bundled, models_dir=models)
        assert mine.exists(), "managed=False means the file is not ours to delete"

    def test_imported_models_are_never_touched(self, tmp_path):
        bundled, models = tmp_path / "bundled", tmp_path / "models"
        gguf(bundled / "new.gguf")
        mine = gguf(tmp_path / "mine" / "mistral.gguf")
        r = Registry()
        r.upsert(ModelEntry(id="mistral", path=str(mine), label="Mistral",
                            origin="imported", managed=False,
                            tasks=("analysis",), user_assigned=True))
        m = BundledManifest(models=(BundledModel(
            id="new", file="new.gguf", tasks=("analysis",)),))

        reconcile_bundled(r, m, bundled_dir=bundled, models_dir=models)
        assert mine.exists()
        assert r.get("mistral").tasks == ("analysis",)
        assert r.get("mistral").user_assigned is True


class TestUserIntentSurvivesAnUpdate:
    def test_a_user_assignment_is_not_overwritten_by_the_manifest(self, tmp_path):
        bundled, models = tmp_path / "bundled", tmp_path / "models"
        gguf(bundled / "slm.gguf")
        existing = gguf(models / "slm.gguf")
        r = Registry()
        # the user deliberately took analysis AWAY from the bundled model
        r.upsert(ModelEntry(id="slm", path=str(existing), label="SLM",
                            origin="bundled", managed=True,
                            tasks=("general",), user_assigned=True))
        m = BundledManifest(models=(BundledModel(
            id="slm", file="slm.gguf", tasks=("general", "analysis")),))

        reconcile_bundled(r, m, bundled_dir=bundled, models_dir=models)
        assert r.get("slm").tasks == ("general",), "the update must not undo this"

    def test_a_manifest_assignment_IS_refreshed_when_the_user_never_chose(self, tmp_path):
        bundled, models = tmp_path / "bundled", tmp_path / "models"
        gguf(bundled / "slm.gguf")
        existing = gguf(models / "slm.gguf")
        r = Registry()
        r.upsert(ModelEntry(id="slm", path=str(existing), label="SLM",
                            origin="bundled", managed=True,
                            tasks=("general",), user_assigned=False))
        m = BundledManifest(models=(BundledModel(
            id="slm", file="slm.gguf", tasks=("general", "analysis")),))

        reconcile_bundled(r, m, bundled_dir=bundled, models_dir=models)
        assert set(r.get("slm").tasks) == {"general", "analysis"}


class TestOptOut:
    def test_a_removed_bundled_model_is_not_reinstalled(self, tmp_path):
        bundled, models = tmp_path / "bundled", tmp_path / "models"
        gguf(bundled / "slm.gguf")
        r = Registry()
        r.opt_out("slm")
        m = BundledManifest(models=(BundledModel(id="slm", file="slm.gguf"),))

        report = reconcile_bundled(r, m, bundled_dir=bundled, models_dir=models)
        assert not (models / "slm.gguf").exists(), "700 MB must not come back uninvited"
        assert r.get("slm") is None
        assert report.skipped_optout == ["slm"]

    def test_opting_back_in_installs_it(self, tmp_path):
        bundled, models = tmp_path / "bundled", tmp_path / "models"
        gguf(bundled / "slm.gguf")
        r = Registry()
        r.opt_out("slm")
        m = BundledManifest(models=(BundledModel(id="slm", file="slm.gguf"),))
        reconcile_bundled(r, m, bundled_dir=bundled, models_dir=models)

        r.opt_in("slm")
        reconcile_bundled(r, m, bundled_dir=bundled, models_dir=models)
        assert (models / "slm.gguf").is_file()
        assert r.get("slm") is not None


class TestReconcileAndSave:
    def test_it_persists_and_is_idempotent(self, tmp_path):
        bundled, models = tmp_path / "bundled", tmp_path / "models"
        gguf(bundled / "slm.gguf")
        write_manifest(bundled, {"id": "slm", "file": "slm.gguf",
                                 "label": "SLM", "tasks": ["general"]})

        first = reconcile_and_save(models, bundled)
        assert first.changed is True
        assert Registry.path_for(models).is_file()

        # running again must do nothing: startup calls this every launch
        second = reconcile_and_save(models, bundled)
        assert second.changed is False
        assert len(Registry.load(models).models) == 1

    def test_it_never_raises_even_on_an_unwritable_dir(self, tmp_path):
        # startup calls this; a failure here must not stop the app opening
        report = reconcile_and_save(Path("/proc/nope/models"), tmp_path / "nothing")
        assert isinstance(report.errors, list)

    def test_the_summary_reads_as_a_sentence(self, tmp_path):
        bundled, models = tmp_path / "bundled", tmp_path / "models"
        gguf(bundled / "slm.gguf")
        write_manifest(bundled, {"id": "slm", "file": "slm.gguf", "label": "SLM 1B"})
        report = reconcile_and_save(models, bundled)
        assert report.summary().startswith("This update")
        assert "SLM 1B" in report.summary()


class TestBaseModelMustNotClaimStructuredTasks:
    """The regression that shipped, and how it got in.

    ``catalog.BASE_MODEL.tasks`` was descriptive metadata nobody routed on, and
    it listed ``latex_writer``. The registry then began SEEDING assignments from
    that field, which turned a description into an instruction: the 0.5B started
    outranking the 1.5B for Scribe, silently undoing the deliberate choice
    documented at ``ollama_client.TASK_MODEL_MAP``.

    The general rule these tests pin: the base model is the FALLBACK for
    everything, and the router already guarantees that. It must never CLAIM a
    task, because claiming one lets it beat a better model chosen on purpose.
    """

    def test_the_bundled_base_claims_only_general(self):
        from domain.model_manager.catalog import BASE_MODEL
        assert BASE_MODEL.tasks == ("general",), (
            "the base model must not claim a structured task -- see "
            "ollama_client.TASK_MODEL_MAP for why the 0.5B is not used for these"
        )

    def test_no_bundled_model_claims_a_task_the_task_map_sends_elsewhere(self):
        # the tripwire for the general case, not just latex_writer
        from domain.model_manager.catalog import bundled_models
        from infrastructure.ollama_client import OllamaClient

        for spec in bundled_models():
            for task, preferred in OllamaClient.TASK_MODEL_MAP.items():
                if not preferred:
                    continue
                if preferred[0] == spec.name:
                    continue  # it IS the preferred model; claiming is correct
                assert task not in spec.tasks, (
                    f"{spec.name} claims {task!r}, but TASK_MODEL_MAP routes it "
                    f"to {preferred[0]!r}. A bundled model that claims a task it "
                    f"is not the best at will outrank the better model."
                )

    def test_an_existing_install_self_heals_on_upgrade(self, tmp_path):
        # a user already running the beta has the bad assignment persisted.
        # reconciliation must correct it, because user_assigned is False.
        bundled, models = tmp_path / "bundled", tmp_path / "models"
        gguf(bundled / "base.gguf")
        existing = gguf(models / "base.gguf")
        r = Registry()
        r.upsert(ModelEntry(id="base", path=str(existing), label="Base",
                            origin="bundled", managed=True,
                            tasks=("general", "latex_writer"),   # the bad state
                            user_assigned=False))
        m = BundledManifest(models=(BundledModel(
            id="base", file="base.gguf", label="Base", tasks=("general",)),))

        reconcile_bundled(r, m, bundled_dir=bundled, models_dir=models)
        assert r.get("base").tasks == ("general",), "the upgrade must correct it"
