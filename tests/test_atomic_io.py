"""tests for crash-safe json persistence."""

import json

import pytest

from infrastructure.atomic_io import atomic_write_json


def test_writes_valid_json_that_round_trips(tmp_path):
    target = tmp_path / "data.json"
    payload = {"a": 1, "b": [1, 2, 3], "c": "text"}

    atomic_write_json(target, payload)

    assert json.loads(target.read_text(encoding="utf-8")) == payload


def test_no_temp_file_left_after_success(tmp_path):
    target = tmp_path / "data.json"
    atomic_write_json(target, {"ok": True})

    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "data.json"]
    assert leftovers == []


def test_original_preserved_when_serialization_fails(tmp_path):
    target = tmp_path / "data.json"
    good = {"keep": "me"}
    atomic_write_json(target, good)

    # a set is not json-serializable -> json.dump raises mid-write
    with pytest.raises(TypeError):
        atomic_write_json(target, {"bad": {1, 2, 3}})

    # the previously-good file must be untouched, and no temp file left behind
    assert json.loads(target.read_text(encoding="utf-8")) == good
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "data.json"]
    assert leftovers == []
