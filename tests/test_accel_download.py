"""downloading the graphics engine, and the many ways it must fail safely.

Every test here is offline: the network is a fake opener, and the "engine" is a
tar file built in the test. That is not only for speed -- the property being
checked is that a partial, corrupt, hostile or unloadable download leaves the
app exactly as it was, and the only way to check that is to produce those
situations deliberately.

The stake is worth stating. This is the one feature that changes which shared
library the inference engine loads. Getting it wrong does not degrade the app;
it stops the app answering anything, on a machine where it is the only thing
that can read the user's papers.
"""

from __future__ import annotations

import hashlib
import io
import json
import tarfile

import pytest

from infrastructure import accel_download, acceleration
from infrastructure.accel_download import AccelInstaller


def make_archive(names=("lib/libllama.so", "lib/libggml-vulkan.so")) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name in names:
            data = b"x" * 64
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeResponse(io.BytesIO):
    def __init__(self, payload: bytes):
        super().__init__(payload)
        self.headers = {"content-length": str(len(payload))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def opener_for(archive: bytes, manifest: dict | None, *, fail_archive=False):
    """a stand-in for urlopen that serves our two assets."""
    def _open(url, timeout=None):
        if url.endswith(".json"):
            if manifest is None:
                raise OSError("404")
            return FakeResponse(json.dumps(manifest).encode())
        if fail_archive:
            raise OSError("connection reset")
        return FakeResponse(archive)
    return _open


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture(autouse=True)
def _never_really_probe(monkeypatch):
    """the probe spawns a process; each test says what it should conclude."""
    monkeypatch.setattr(acceleration, "probe_in_subprocess",
                        lambda d, **k: (True, "verified"))


@pytest.fixture
def archive():
    return make_archive()


@pytest.fixture
def manifest(archive):
    return {"backend": "vulkan", "platform": "linux-x86_64", "bytes": len(archive),
            "sha256": hashlib.sha256(archive).hexdigest(),
            "asset": "thinkstack-accel-vulkan-linux-x86_64.tar.gz"}


class TestTheHappyPath:
    def test_it_installs_and_activates(self, data_dir, archive, manifest):
        r = AccelInstaller().install(data_dir, "linux-x86_64",
                                     opener=opener_for(archive, manifest))
        assert r["status"] == "done"
        assert acceleration.active_lib_dir(data_dir) is not None

    def test_the_libraries_land_where_the_override_points(self, data_dir, archive, manifest):
        AccelInstaller().install(data_dir, "linux-x86_64",
                                 opener=opener_for(archive, manifest))
        lib = acceleration.active_lib_dir(data_dir)
        assert (lib / "libggml-vulkan.so").is_file()

    def test_progress_reaches_a_hundred(self, data_dir, archive, manifest):
        inst = AccelInstaller()
        inst.install(data_dir, "linux-x86_64", opener=opener_for(archive, manifest))
        assert inst.progress()["percent"] == 100.0

    def test_it_says_a_restart_is_needed(self, data_dir, archive, manifest):
        # the override is read at startup, so the running process is unchanged
        r = AccelInstaller().install(data_dir, "linux-x86_64",
                                     opener=opener_for(archive, manifest))
        assert "restart" in r["detail"].lower()


class TestItRefusesWhatItCannotTrust:
    def test_a_corrupt_download_is_rejected(self, data_dir, archive, manifest):
        # a truncated file fails to load in a way indistinguishable from an
        # incompatible driver, and the user would be told something untrue
        # about their own machine
        manifest["sha256"] = "0" * 64
        r = AccelInstaller().install(data_dir, "linux-x86_64",
                                     opener=opener_for(archive, manifest))
        assert r["status"] == "error"
        assert "intact" in r["error"]
        assert acceleration.active_lib_dir(data_dir) is None

    def test_no_manifest_means_no_download(self, data_dir, archive):
        # without a measured size there is no honest number to show and nothing
        # to verify against, so the answer is "not yet", not "download blindly"
        r = AccelInstaller().install(data_dir, "linux-x86_64",
                                     opener=opener_for(archive, None))
        assert r["status"] == "error"
        assert "not published" in r["error"]

    def test_a_network_failure_is_reported_not_raised(self, data_dir, archive, manifest):
        r = AccelInstaller().install(data_dir, "linux-x86_64",
                                     opener=opener_for(archive, manifest, fail_archive=True))
        assert r["status"] == "error"
        assert acceleration.active_lib_dir(data_dir) is None

    def test_an_archive_of_the_wrong_shape_is_rejected(self, data_dir, manifest):
        odd = make_archive(names=("notlib/thing.so",))
        manifest.update(bytes=len(odd), sha256=hashlib.sha256(odd).hexdigest())
        r = AccelInstaller().install(data_dir, "linux-x86_64",
                                     opener=opener_for(odd, manifest))
        assert r["status"] == "error"
        assert acceleration.active_lib_dir(data_dir) is None

    def test_a_traversing_member_is_refused(self, data_dir, manifest):
        # "the archive is ours" is an assumption that costs nothing to remove
        evil = make_archive(names=("lib/../../../etc/passwd",))
        manifest.update(bytes=len(evil), sha256=hashlib.sha256(evil).hexdigest())
        r = AccelInstaller().install(data_dir, "linux-x86_64",
                                     opener=opener_for(evil, manifest))
        assert r["status"] == "error"
        assert "unsafe path" in r["error"]


class TestAFailedProbeUndoesNothingElse:
    def test_libraries_that_cannot_load_are_not_activated(
        self, data_dir, archive, manifest, monkeypatch
    ):
        # THE case this design exists for: the download is perfect and the
        # libraries still cannot run here
        monkeypatch.setattr(acceleration, "probe_in_subprocess",
                            lambda d, **k: (False, "driver too old."))
        r = AccelInstaller().install(data_dir, "linux-x86_64",
                                     opener=opener_for(archive, manifest))
        assert r["status"] == "error"
        assert "still using your processor" in r["error"]
        assert acceleration.active_lib_dir(data_dir) is None

    def test_the_reason_reaches_the_user(self, data_dir, archive, manifest, monkeypatch):
        monkeypatch.setattr(acceleration, "probe_in_subprocess",
                            lambda d, **k: (False, "CUDA driver version is insufficient."))
        r = AccelInstaller().install(data_dir, "linux-x86_64",
                                     opener=opener_for(archive, manifest))
        assert "insufficient" in r["error"]


class TestOneAtATime:
    def test_a_second_install_does_not_start(self, data_dir, archive, manifest):
        inst = AccelInstaller()
        inst._progress = accel_download.AccelProgress(status="downloading")
        r = inst.install(data_dir, "linux-x86_64", opener=opener_for(archive, manifest))
        assert r["status"] == "downloading"

    def test_cancel_only_applies_while_running(self, data_dir):
        assert AccelInstaller().cancel() is False

    def test_progress_is_none_before_anything_starts(self):
        assert AccelInstaller().progress() is None


class TestNothingIsLeftBehind:
    def test_a_failure_leaves_no_partial_directory(self, data_dir, archive, manifest):
        manifest["sha256"] = "0" * 64
        AccelInstaller().install(data_dir, "linux-x86_64",
                                 opener=opener_for(archive, manifest))
        leftovers = list(acceleration.accel_dir(data_dir).glob("*.partial"))
        assert leftovers == []

    def test_reinstalling_replaces_rather_than_accumulates(self, data_dir, archive, manifest):
        for _ in range(2):
            AccelInstaller().install(data_dir, "linux-x86_64",
                                     opener=opener_for(archive, manifest))
        dirs = [p for p in acceleration.accel_dir(data_dir).iterdir() if p.is_dir()]
        assert len(dirs) == 1
