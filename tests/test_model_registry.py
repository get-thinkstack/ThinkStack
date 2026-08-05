"""the model registry, exercised against real files.

Nothing is mocked. Every test writes an actual registry.json and actual gguf
files to a tmp_path, because the failures this module has to survive are all
filesystem failures: a model the user deleted, a file that is not a gguf, a
registry truncated by a power cut, one written by a newer ThinkStack.

The registry sits between the user and every AI feature in the app. A parse
error that raises here takes down more than it protects, so most of these tests
assert on *degrading* rather than on raising.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from domain.model_manager.registry import (
    GGUF_MAGIC,
    KNOWN_TASKS,
    SCHEMA_VERSION,
    ModelEntry,
    ModelImportError,
    Registry,
    entry_from_import,
    make_id,
    removal_warning,
    validate_gguf,
)


def write_gguf(path: Path, size_mb: float = 1.0) -> Path:
    """a file llama.cpp would accept the first four bytes of."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(GGUF_MAGIC)
        f.write(b"\0" * max(0, int(size_mb * 1024 * 1024) - 4))
    return path


def entry(**kw) -> ModelEntry:
    base = dict(id="m", path="/nonexistent/m.gguf", label="M")
    base.update(kw)
    return ModelEntry(**base)


class TestMakeId:
    def test_punctuation_does_not_change_identity(self):
        # the same weights spelled three ways must not become three entries
        a = make_id("Qwen2.5-1.5B-Instruct-Q4_K_M.gguf")
        b = make_id("qwen2.5_1.5b_instruct_q4_k_m")
        c = make_id("  QWEN2.5 1.5B INSTRUCT Q4 K M.gguf  ")
        assert a == b == c

    def test_quantisation_is_kept(self):
        # deliberately unlike discovery.model_key: a user may register both
        # quants and route them to different tasks.
        assert make_id("qwen2.5-1.5b-q4_k_m.gguf") != make_id("qwen2.5-1.5b-q8_0.gguf")

    def test_no_leading_or_trailing_separators(self):
        assert not make_id("---weird---.gguf").startswith("-")
        assert not make_id("---weird---.gguf").endswith("-")


class TestStatus:
    def test_missing_outranks_too_big(self, tmp_path):
        # a deleted 40 GB model must report "missing", not "too_big" -- telling
        # someone to free memory when the file is gone sends them after the
        # wrong fix entirely.
        e = entry(path=str(tmp_path / "gone.gguf"), size_gb=40.0)
        assert e.status(budget_gb=2.0) == "missing"

    def test_too_big_against_a_known_budget(self, tmp_path):
        p = write_gguf(tmp_path / "big.gguf")
        assert entry(path=str(p), size_gb=8.0).status(budget_gb=3.0) == "too_big"

    def test_unknown_budget_never_rejects(self, tmp_path):
        p = write_gguf(tmp_path / "big.gguf")
        # budget 0 means "we could not measure", which must not block a load
        assert entry(path=str(p), size_gb=99.0).status(budget_gb=0.0) == "present"

    def test_a_recorded_error_surfaces(self, tmp_path):
        p = write_gguf(tmp_path / "m.gguf")
        assert entry(path=str(p), last_error="oom").status() == "failed"

    def test_empty_path_is_missing_not_a_crash(self):
        assert entry(path="").status() == "missing"


class TestPersistence:
    def test_round_trip(self, tmp_path):
        r = Registry()
        r.upsert(entry(id="a", path=str(tmp_path / "a.gguf"), tasks=("analysis",)))
        r.opt_out("old-bundled")
        assert r.save(tmp_path) is True

        back = Registry.load(tmp_path)
        assert [m.id for m in back.models] == ["a"]
        assert back.models[0].tasks == ("analysis",)
        assert back.bundled_optout == ["old-bundled"]

    def test_missing_file_is_the_normal_first_run(self, tmp_path):
        r = Registry.load(tmp_path)
        assert r.models == []
        assert r.read_only is False

    def test_corrupt_json_degrades_to_empty(self, tmp_path):
        Registry.path_for(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        Registry.path_for(tmp_path).write_text("{not json at all", encoding="utf-8")
        r = Registry.load(tmp_path)
        assert r.models == []

    def test_truncated_json_degrades_to_empty(self, tmp_path):
        # what a power cut mid-write used to leave behind, before atomic_io
        Registry.path_for(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        Registry.path_for(tmp_path).write_text('{"version":1,"models":[{"id"', encoding="utf-8")
        assert Registry.load(tmp_path).models == []

    def test_a_json_array_instead_of_an_object_degrades(self, tmp_path):
        Registry.path_for(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        Registry.path_for(tmp_path).write_text("[1,2,3]", encoding="utf-8")
        assert Registry.load(tmp_path).models == []

    def test_a_newer_schema_is_read_but_never_written(self, tmp_path):
        # a downgrade must not silently delete fields it does not understand
        Registry.path_for(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        Registry.path_for(tmp_path).write_text(json.dumps({
            "version": SCHEMA_VERSION + 1,
            "models": [{"id": "a", "path": "/x/a.gguf", "label": "A"}],
            "some_future_field": {"we": "cannot know"},
        }), encoding="utf-8")

        r = Registry.load(tmp_path)
        assert r.read_only is True
        assert [m.id for m in r.models] == ["a"]        # still usable
        assert r.save(tmp_path) is False                # but never written back

        # the future field survived because we refused to write
        on_disk = json.loads(Registry.path_for(tmp_path).read_text())
        assert "some_future_field" in on_disk

    def test_one_unreadable_entry_does_not_lose_the_others(self, tmp_path):
        Registry.path_for(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        Registry.path_for(tmp_path).write_text(json.dumps({
            "version": 1,
            "models": [
                {"id": "good", "path": "/x/good.gguf", "label": "Good"},
                "this is not an object",
                {"id": "also-good", "path": "/x/also.gguf", "label": "Also"},
            ],
        }), encoding="utf-8")
        assert [m.id for m in Registry.load(tmp_path).models] == ["good", "also-good"]

    def test_unknown_tasks_are_dropped_on_read(self, tmp_path):
        Registry.path_for(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        Registry.path_for(tmp_path).write_text(json.dumps({
            "version": 1,
            "models": [{"id": "a", "path": "/x/a.gguf", "label": "A",
                        "tasks": ["analysis", "mine_bitcoin"]}],
        }), encoding="utf-8")
        assert Registry.load(tmp_path).models[0].tasks == ("analysis",)

    def test_an_unknown_origin_falls_back_to_imported(self, tmp_path):
        # "imported" is the SAFE default: it means managed=False, so a garbled
        # origin can never make us delete a user's file.
        Registry.path_for(tmp_path).parent.mkdir(parents=True, exist_ok=True)
        Registry.path_for(tmp_path).write_text(json.dumps({
            "version": 1,
            "models": [{"id": "a", "path": "/x/a.gguf", "label": "A", "origin": "wat"}],
        }), encoding="utf-8")
        assert Registry.load(tmp_path).models[0].origin == "imported"


class TestLookup:
    def test_by_path_matches_across_spellings(self, tmp_path):
        p = write_gguf(tmp_path / "sub" / "m.gguf")
        r = Registry()
        r.upsert(entry(id="m", path=str(p)))
        # a relative route to the same file must find the same entry, or
        # importing twice would create two entries fighting over one file
        assert r.by_path(str(tmp_path / "sub" / ".." / "sub" / "m.gguf")) is not None

    def test_by_path_on_a_junk_path_returns_none(self):
        assert Registry().by_path("\0not/a/path") is None

    def test_for_task_puts_user_choices_first(self):
        r = Registry()
        r.upsert(entry(id="manifest", path="/a.gguf", label="AAA",
                       tasks=("analysis",), user_assigned=False))
        r.upsert(entry(id="mine", path="/z.gguf", label="ZZZ",
                       tasks=("analysis",), user_assigned=True))
        # ZZZ sorts last alphabetically, so this only passes if user_assigned wins
        assert [m.id for m in r.for_task("analysis")] == ["mine", "manifest"]

    def test_for_task_ignores_unrelated_models(self):
        r = Registry()
        r.upsert(entry(id="a", tasks=("general",)))
        assert r.for_task("analysis") == []


class TestMutation:
    def test_upsert_replaces_rather_than_duplicating(self):
        r = Registry()
        r.upsert(entry(id="a", label="first"))
        r.upsert(entry(id="a", label="second"))
        assert len(r.models) == 1
        assert r.models[0].label == "second"

    def test_assign_drops_unknown_tasks_but_keeps_the_rest(self):
        r = Registry()
        r.upsert(entry(id="a"))
        updated = r.assign("a", ["analysis", "not_a_task", "general"])
        assert set(updated.tasks) == {"analysis", "general"}

    def test_assign_marks_user_intent(self):
        r = Registry()
        r.upsert(entry(id="a", user_assigned=False))
        assert r.assign("a", ["general"]).user_assigned is True

    def test_a_manifest_assign_does_not_clear_existing_user_intent(self):
        # upgrading must never quietly undo routing somebody set up on purpose
        r = Registry()
        r.upsert(entry(id="a", tasks=("analysis",), user_assigned=True))
        assert r.assign("a", ["general"], by_user=False).user_assigned is True

    def test_assign_to_a_missing_id_returns_none(self):
        assert Registry().assign("ghost", ["general"]) is None

    def test_remove_returns_the_entry_and_leaves_the_file(self, tmp_path):
        p = write_gguf(tmp_path / "m.gguf")
        r = Registry()
        r.upsert(entry(id="m", path=str(p)))
        assert r.remove("m").id == "m"
        assert r.models == []
        assert p.exists(), "remove() must never delete weights itself"

    def test_record_error_then_clear(self):
        r = Registry()
        r.upsert(entry(id="a"))
        assert r.record_error("a", "out of memory").last_error == "out of memory"
        assert r.record_error("a", None).last_error is None

    def test_opt_out_is_idempotent(self):
        r = Registry()
        r.opt_out("x")
        r.opt_out("x")
        assert r.bundled_optout == ["x"]
        r.opt_in("x")
        assert r.bundled_optout == []


class TestRemovalWarning:
    """removal is never blocked -- but the consequence must be legible."""

    def test_no_warning_when_another_model_covers_the_task(self, tmp_path):
        a = write_gguf(tmp_path / "a.gguf")
        b = write_gguf(tmp_path / "b.gguf")
        r = Registry()
        r.upsert(entry(id="a", path=str(a), tasks=("analysis",)))
        r.upsert(entry(id="b", path=str(b), tasks=("analysis",)))
        assert removal_warning(r.get("a"), r) is None

    def test_warns_when_it_is_the_last_model_for_a_task(self, tmp_path):
        a = write_gguf(tmp_path / "a.gguf")
        b = write_gguf(tmp_path / "b.gguf")
        r = Registry()
        r.upsert(entry(id="a", path=str(a), tasks=("analysis",)))
        r.upsert(entry(id="b", path=str(b), tasks=("general",)))
        msg = removal_warning(r.get("a"), r)
        assert msg and "analysis" in msg

    def test_the_last_model_of_all_gets_a_different_warning(self, tmp_path):
        a = write_gguf(tmp_path / "a.gguf")
        r = Registry()
        r.upsert(entry(id="a", path=str(a), tasks=("analysis",)))
        msg = removal_warning(r.get("a"), r)
        assert msg and "only model" in msg

    def test_a_model_whose_file_vanished_does_not_count_as_coverage(self, tmp_path):
        # b is registered for analysis but its file is gone, so removing a
        # really does orphan the task -- the warning must say so.
        a = write_gguf(tmp_path / "a.gguf")
        r = Registry()
        r.upsert(entry(id="a", path=str(a), tasks=("analysis",)))
        r.upsert(entry(id="b", path=str(tmp_path / "gone.gguf"), tasks=("analysis",)))
        assert removal_warning(r.get("a"), r) is not None

    def test_removing_an_unassigned_model_never_warns(self, tmp_path):
        a = write_gguf(tmp_path / "a.gguf")
        r = Registry()
        r.upsert(entry(id="a", path=str(a), tasks=()))
        assert removal_warning(r.get("a"), r) is None


class TestImportValidation:
    def test_accepts_a_real_gguf(self, tmp_path):
        p = write_gguf(tmp_path / "good.gguf")
        assert validate_gguf(p) == p.resolve()

    def test_rejects_a_missing_path(self, tmp_path):
        with pytest.raises(ModelImportError, match="no file"):
            validate_gguf(tmp_path / "nope.gguf")

    def test_rejects_a_directory(self, tmp_path):
        with pytest.raises(ModelImportError, match="folder"):
            validate_gguf(tmp_path)

    def test_rejects_a_file_that_is_not_gguf(self, tmp_path):
        # the exact mistake this catches: picking the safetensors next to it.
        p = tmp_path / "model.safetensors"
        p.write_bytes(b"\x00\x00\x00\x00some other format")
        with pytest.raises(ModelImportError, match="not a GGUF"):
            validate_gguf(p)

    def test_rejects_a_gguf_named_file_that_is_actually_text(self, tmp_path):
        # renaming notes.txt to model.gguf must not get past us
        p = tmp_path / "model.gguf"
        p.write_text("this is not a model", encoding="utf-8")
        with pytest.raises(ModelImportError, match="not a GGUF"):
            validate_gguf(p)

    def test_rejects_an_empty_file(self, tmp_path):
        p = tmp_path / "empty.gguf"
        p.write_bytes(b"")
        with pytest.raises(ModelImportError, match="not a GGUF"):
            validate_gguf(p)

    def test_every_message_is_fit_to_show_a_user(self, tmp_path):
        # these strings go straight into the UI, so no tracebacks or repr junk
        for bad in (tmp_path / "nope.gguf", tmp_path):
            try:
                validate_gguf(bad)
            except ModelImportError as e:
                assert str(e)[0].isupper() and str(e).endswith((".", "e."))


class TestEntryFromImport:
    def test_builds_an_unmanaged_entry_by_default(self, tmp_path):
        p = write_gguf(tmp_path / "mistral-7b.gguf")
        e = entry_from_import(p, ["analysis"])
        assert e.managed is False, "an imported file belongs to the user"
        assert e.origin == "imported"
        assert e.user_assigned is True
        assert e.tasks == ("analysis",)
        assert e.path == str(p.resolve())

    def test_label_defaults_to_a_readable_form_of_the_filename(self, tmp_path):
        p = write_gguf(tmp_path / "mistral-7b.gguf")
        assert entry_from_import(p, []).label == "Mistral 7b"

    def test_an_explicit_label_wins(self, tmp_path):
        p = write_gguf(tmp_path / "mistral-7b.gguf")
        assert entry_from_import(p, [], label="My Model").label == "My Model"

    def test_a_whitespace_label_falls_back_to_the_filename(self, tmp_path):
        p = write_gguf(tmp_path / "mistral-7b.gguf")
        assert entry_from_import(p, [], label="   ").label == "Mistral 7b"

    def test_size_is_measured_not_trusted(self, tmp_path):
        p = write_gguf(tmp_path / "m.gguf", size_mb=8)
        assert 0.0 < entry_from_import(p, []).size_gb < 0.1

    def test_a_bad_path_raises_before_anything_is_registered(self, tmp_path):
        with pytest.raises(ModelImportError):
            entry_from_import(tmp_path / "ghost.gguf", ["analysis"])


class TestKnownTasks:
    def test_covers_every_task_the_runtime_routes(self):
        # if ollama_client grows a task and KNOWN_TASKS does not, assignments
        # to it would be silently dropped -- this is the tripwire for that.
        from infrastructure.ollama_client import OllamaClient
        for task in OllamaClient.TASK_MODEL_MAP:
            assert task in KNOWN_TASKS, f"{task} is routable but not assignable"


class TestRemovalNeverTouchesAFileWeDoNotOwn:
    """The API guard, which had no test until a mutation check found the gap.

    `managed` is the only thing standing between "forget this model" and
    "delete several gigabytes out of the user's own folder". An imported model
    lives wherever they keep their models -- often beside work unrelated to
    ThinkStack -- and removing it here must never reach outside the app.
    """

    def _client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        from config import settings
        monkeypatch.setattr(settings, "models_dir", tmp_path)
        monkeypatch.setattr(settings, "bundled_models_dir", tmp_path)
        import main
        return TestClient(main.app)

    def test_deleting_an_imported_file_is_refused(self, tmp_path, monkeypatch):
        mine = write_gguf(tmp_path / "mine" / "my-model.gguf")
        r = Registry()
        r.upsert(ModelEntry(id="my-model", path=str(mine), label="Mine",
                            origin="imported", managed=False))
        r.save(tmp_path)

        c = self._client(tmp_path, monkeypatch)
        resp = c.delete("/api/models/registry/my-model?delete_file=true")
        assert resp.status_code == 400, "deleting a file we do not own must be refused"
        assert "not ThinkStack's to delete" in resp.json()["detail"]
        assert mine.exists(), "the user's file must survive a refused delete"

    def test_forgetting_an_imported_model_leaves_the_file(self, tmp_path, monkeypatch):
        mine = write_gguf(tmp_path / "mine" / "my-model.gguf")
        r = Registry()
        r.upsert(ModelEntry(id="my-model", path=str(mine), label="Mine",
                            origin="imported", managed=False))
        r.save(tmp_path)

        c = self._client(tmp_path, monkeypatch)
        resp = c.delete("/api/models/registry/my-model?delete_file=false")
        assert resp.status_code == 200
        assert resp.json()["file_deleted"] is False
        assert mine.exists()
        assert Registry.load(tmp_path).get("my-model") is None

    def test_a_file_we_created_can_be_deleted_on_request(self, tmp_path, monkeypatch):
        ours = write_gguf(tmp_path / "ours.gguf")
        r = Registry()
        r.upsert(ModelEntry(id="ours", path=str(ours), label="Ours",
                            origin="downloaded", managed=True))
        r.save(tmp_path)

        c = self._client(tmp_path, monkeypatch)
        resp = c.delete("/api/models/registry/ours?delete_file=true")
        assert resp.status_code == 200
        assert resp.json()["file_deleted"] is True
        assert not ours.exists()

    def test_the_default_never_deletes(self, tmp_path, monkeypatch):
        # "remove" is ambiguous and destroying gigabytes is not recoverable,
        # so a caller that says nothing gets the harmless behaviour.
        ours = write_gguf(tmp_path / "ours.gguf")
        r = Registry()
        r.upsert(ModelEntry(id="ours", path=str(ours), label="Ours",
                            origin="downloaded", managed=True))
        r.save(tmp_path)

        c = self._client(tmp_path, monkeypatch)
        resp = c.delete("/api/models/registry/ours")
        assert resp.status_code == 200
        assert resp.json()["file_deleted"] is False
        assert ours.exists(), "an unqualified remove must not destroy weights"
