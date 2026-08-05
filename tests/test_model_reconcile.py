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

    def test_a_missing_manifest_falls_back_to_the_files_present(self, tmp_path):
        # builds released before the manifest existed carry weights and no
        # manifest; reporting nothing would retire a model sitting right there.
        gguf(tmp_path / "qwen2.5-0.5b-instruct-q4_k_m.gguf")
        m = BundledManifest.load(tmp_path)
        assert [x.file for x in m.models] == ["qwen2.5-0.5b-instruct-q4_k_m.gguf"]

    def test_an_empty_directory_yields_an_empty_manifest(self, tmp_path):
        # the normal case now: ThinkStack ships no weights at all.
        assert BundledManifest.load(tmp_path).models == ()

    def test_no_tasks_are_inferred_from_a_filename(self, tmp_path):
        # inferring turns a description into an instruction; giving every file
        # `general` made them compete and the larger one won.
        gguf(tmp_path / "qwen2.5-0.5b-instruct-q4_k_m.gguf")
        gguf(tmp_path / "qwen2.5-1.5b-instruct-q4_k_m.gguf")
        assert all(x.tasks == () for x in BundledManifest.load(tmp_path).models)

    def test_corrupt_manifest_falls_back_rather_than_raising(self, tmp_path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        gguf(tmp_path / "a-q4_k_m.gguf")
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


class TestWhatTheBundledBaselineMayClaim:
    """The rule changed shape when the baseline did, so it is restated here.

    The ORIGINAL rule was "the base claims only `general`". That was correct
    when the base was a Qwen2.5 0.5B: it emitted prose where an equation was
    asked for, so any task it claimed was a task it would do badly, and
    claiming `latex_writer` did exactly that -- silently outranking the 1.5B
    for Scribe.

    The baseline is now a Qwen3 0.6B chosen deliberately FOR the structured
    jobs, because ollama_client constrains their output with a GBNF grammar and
    a small model cannot emit malformed JSON. So claiming `gap_analysis` and
    `latex_writer` is now the intent rather than the bug.

    What has NOT changed is `analysis`. Summarisation is open-ended prose over
    a whole paper, it is the one job a larger model plainly does better, and a
    baseline that claimed it would suppress the upgrade suggestion forever.
    """

    def test_the_baseline_never_claims_analysis(self):
        from domain.model_manager.catalog import bundled_models
        for spec in bundled_models():
            assert "analysis" not in spec.tasks, (
                f"{spec.label} claims `analysis`. Summaries are where a larger "
                f"model earns its download; claiming it here means the upgrade "
                f"is never suggested."
            )

    def test_the_baseline_covers_general_so_nothing_is_unrouted(self):
        from domain.model_manager.catalog import bundled_models
        bundled = bundled_models()
        assert bundled, "something must be bundled, or a fresh install has no model"
        assert any("general" in s.tasks for s in bundled)

    def test_catalog_and_release_config_agree_on_what_ships(self):
        """The two files that decide what is bundled must not drift.

        catalog.py drives suggestions; release.config.json drives the build.
        If they disagree, the app describes a model the installer does not
        carry -- which is the four-places problem the manifest exists to end.
        """
        import json
        from domain.model_manager.catalog import bundled_models

        root = Path(__file__).resolve().parent.parent
        cfg = json.loads((root / "release.config.json").read_text())
        shipped = {
            (m if isinstance(m, str) else m["url"]).rsplit("/", 1)[-1]
            for m in cfg["models"]
        }
        assert {s.name for s in bundled_models()} == shipped, (
            "catalog.py and release.config.json disagree about what is bundled"
        )

    def test_a_changed_baseline_always_declares_what_it_replaces(self):
        """If the bundled model ever changes, `replaces` must name the old one.

        Empty is correct while the baseline is unchanged -- there is nothing to
        supersede. The moment it changes, an omitted `replaces` leaves every
        existing install carrying BOTH models: the old weights are never
        deleted, and routing may still prefer them.

        This asserts the conditional, so it starts guarding the instant someone
        edits the URL without editing `replaces`.
        """
        import json
        root = Path(__file__).resolve().parent.parent
        cfg = json.loads((root / "release.config.json").read_text())

        # what the last released build shipped
        PREVIOUS = "qwen2.5-0.5b-instruct-q4_k_m.gguf"

        for m in cfg["models"]:
            url = m if isinstance(m, str) else m["url"]
            filename = url.rsplit("/", 1)[-1]
            replaces = m.get("replaces", []) if isinstance(m, dict) else []
            if filename != PREVIOUS:
                assert replaces, (
                    f"{filename} differs from the shipped baseline "
                    f"({PREVIOUS}) but names nothing in `replaces`. Existing "
                    f"installs would keep both models."
                )
