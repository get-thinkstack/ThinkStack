r"""turning GPU acceleration on, and refusing to when it would not work.

The bug this comes from: a tester's RTX 4050 was correctly detected, correctly
reported as unusable by the CPU-only engine we ship, and then offered nothing at
all. The detection was right; the dead end was the defect.

Most of what follows is about NOT doing it. Downloading a gigabyte and pointing
the inference engine at libraries that cannot load would take the app from
"slower than it could be" to "cannot answer anything", on a machine where it is
the only thing that can read the user's papers. So a plan is refused for every
reason it should be, and an activation only sticks when a separate process has
loaded the libraries and lived.

No test here needs a GPU, a driver, or a network.
"""

from __future__ import annotations

import json

import pytest

from infrastructure import acceleration as accel


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    """`apply_override` writes to os.environ, so every test must start clean.

    Not merely hygiene. The first draft of this file leaked LLAMA_CPP_LIB_PATH
    from one test into the next, pointing llama_cpp at an empty directory -- and
    the next `import llama_cpp` died with "Shared library with base name 'llama'
    not found". That is precisely the failure the subprocess probe exists to
    keep away from the running backend, demonstrated by accident.
    """
    import sys
    for key in ("LLAMA_CPP_LIB_PATH", "THINKSTACK_PROBE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PATH" if sys.platform == "win32" else "LD_LIBRARY_PATH", "")


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def linux_x86(monkeypatch):
    """a supported platform, so tests isolate one refusal at a time."""
    monkeypatch.setattr(accel, "platform_key", lambda: "linux-x86_64")
    monkeypatch.setattr(accel, "engine_already_accelerated", lambda: False)


@pytest.fixture
def devices(monkeypatch):
    """inject what Vulkan reports. Returns a setter."""
    from infrastructure import vulkan

    def setter(items):
        monkeypatch.setattr(accel.vulkan, "available", lambda: bool(items))
        monkeypatch.setattr(accel.vulkan, "enumerate_devices", lambda: list(items))
        order = {"discrete": 0, "integrated": 1}
        usable = sorted((d for d in items if d.usable),
                        key=lambda d: (order.get(d.kind, 9), -d.heap_bytes))
        monkeypatch.setattr(accel.vulkan, "best_device",
                            lambda: usable[0] if usable else None)
    setter._vulkan = vulkan
    return setter


def _dev(name, kind, vendor="NVIDIA", heap=4_000_000_000):
    from infrastructure.vulkan import VulkanDevice
    return VulkanDevice(name=name, vendor=vendor, kind=kind,
                        heap_bytes=heap, api_version="1.3")


DISCRETE = _dev("NVIDIA GeForce RTX 3050 Ti Laptop GPU (NVK GA107)", "discrete")
IGPU = _dev("Intel(R) UHD Graphics (TGL GT1)", "integrated", "Intel")
SOFTWARE = _dev("llvmpipe (LLVM 22.1.8, 256 bits)", "software", "0x10005",
                16_500_000_000)


class TestWhenWeRefuseToOffer:
    def test_no_vulkan_at_all(self, data_dir, linux_x86, devices):
        devices([])
        p = accel.plan(data_dir)
        assert not p.supported
        assert "No Vulkan driver" in p.reason

    def test_software_rendering_only(self, data_dir, linux_x86, devices):
        # THE case. llvmpipe IS the processor; offloading to it would be slower
        # than the CPU path already running, while reporting success.
        devices([SOFTWARE])
        p = accel.plan(data_dir)
        assert not p.supported
        assert "software rendering" in p.reason
        assert "slower" in p.reason

    def test_already_accelerated(self, data_dir, linux_x86, devices, monkeypatch):
        devices([DISCRETE])
        monkeypatch.setattr(accel, "engine_already_accelerated", lambda: True)
        p = accel.plan(data_dir)
        assert not p.supported
        assert "already working" in p.reason

    def test_unsupported_platform(self, data_dir, monkeypatch):
        monkeypatch.setattr(accel, "platform_key", lambda: None)
        p = accel.plan(data_dir)
        assert not p.supported
        assert "Linux and Windows" in p.reason

    def test_every_refusal_says_why(self, data_dir, linux_x86, devices):
        # a disabled button with no explanation is the dead end being fixed
        for items in ([], [SOFTWARE]):
            devices(items)
            p = accel.plan(data_dir)
            assert p.reason and p.reason[0].isupper() and p.reason.endswith(".")


class TestWhatWeOffer:
    def test_a_discrete_card_is_offered(self, data_dir, linux_x86, devices):
        devices([DISCRETE])
        assert accel.plan(data_dir).supported

    def test_an_integrated_gpu_is_offered_too(self, data_dir, linux_x86, devices):
        # Vulkan's whole advantage over CUDA: an iGPU is real parallel silicon
        devices([IGPU])
        p = accel.plan(data_dir)
        assert p.supported
        assert p.device_kind == "integrated"

    def test_an_amd_card_is_offered(self, data_dir, linux_x86, devices):
        # the vendor CUDA could never reach
        devices([_dev("AMD Radeon RX 7600", "discrete", "AMD")])
        assert accel.plan(data_dir).supported

    def test_the_plan_names_the_device_that_would_be_used(self, data_dir, linux_x86, devices):
        # "a GPU" is not actionable on a laptop with three of them
        devices([IGPU, DISCRETE, SOFTWARE])
        assert "3050" in accel.plan(data_dir).device

    def test_only_our_engine_is_downloaded(self, data_dir, linux_x86, devices):
        # no NVIDIA runtime, no drivers -- the loader is already installed
        devices([DISCRETE])
        p = accel.plan(data_dir)
        assert [c.key for c in p.components] == ["engine"]
        assert p.components[0].ours is True

    def test_nothing_belonging_to_a_driver_vendor_is_downloaded(self, data_dir, linux_x86, devices):
        devices([DISCRETE])
        for c in accel.plan(data_dir).components:
            assert "driver" not in c.label.lower()
            assert "cuda" not in c.label.lower()

    def test_the_size_is_known_before_committing(self, data_dir, linux_x86, devices):
        devices([DISCRETE])
        d = accel.plan(data_dir).as_dict()
        assert d["download_mb"] > 0

    def test_it_is_far_smaller_than_the_cuda_path_would_have_been(self, data_dir, linux_x86, devices):
        # CUDA was 424 MB of engine plus ~557 MB of NVIDIA maths libraries.
        # This is the number that made Vulkan the right call.
        devices([DISCRETE])
        assert accel.plan(data_dir).as_dict()["download_mb"] < 200


class TestNothingUnverifiedIsUsed:
    def test_no_state_means_no_override(self, data_dir):
        assert accel.active_lib_dir(data_dir) is None

    def test_active_but_unverified_is_ignored(self, data_dir, tmp_path):
        lib = tmp_path / "libs"
        lib.mkdir()
        accel.write_state(data_dir, {"active": True, "verified": False,
                                     "lib_dir": str(lib)})
        # the flag that matters is `verified`, and only a probe writes it
        assert accel.active_lib_dir(data_dir) is None

    def test_verified_and_present_is_used(self, data_dir, tmp_path):
        lib = tmp_path / "libs"
        lib.mkdir()
        accel.write_state(data_dir, {"active": True, "verified": True,
                                     "lib_dir": str(lib)})
        assert accel.active_lib_dir(data_dir) == lib

    def test_a_directory_that_vanished_is_ignored(self, data_dir, tmp_path):
        # an update or a manual clean-out should not brick the next start
        accel.write_state(data_dir, {"active": True, "verified": True,
                                     "lib_dir": str(tmp_path / "gone")})
        assert accel.active_lib_dir(data_dir) is None

    def test_corrupt_state_is_ignored_rather_than_fatal(self, data_dir):
        p = accel.state_path(data_dir)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{not json")
        assert accel.read_state(data_dir) == {}
        assert accel.active_lib_dir(data_dir) is None


class TestApplyingTheOverride:
    def test_does_nothing_when_inactive(self, data_dir, monkeypatch):
        monkeypatch.delenv("LLAMA_CPP_LIB_PATH", raising=False)
        assert accel.apply_override(data_dir) is None
        assert "LLAMA_CPP_LIB_PATH" not in __import__("os").environ

    def test_points_llama_cpp_at_the_libraries(self, data_dir, tmp_path, monkeypatch):
        import os
        lib = tmp_path / "libs"
        lib.mkdir()
        accel.write_state(data_dir, {"active": True, "verified": True,
                                     "lib_dir": str(lib)})
        monkeypatch.delenv("LLAMA_CPP_LIB_PATH", raising=False)
        assert accel.apply_override(data_dir) == str(lib)
        assert os.environ["LLAMA_CPP_LIB_PATH"] == str(lib)

    def test_also_puts_the_maths_libraries_on_the_loader_path(self, data_dir, tmp_path, monkeypatch):
        import os
        import sys
        lib = tmp_path / "libs"
        lib.mkdir()
        accel.write_state(data_dir, {"active": True, "verified": True,
                                     "lib_dir": str(lib)})
        key = "PATH" if sys.platform == "win32" else "LD_LIBRARY_PATH"
        monkeypatch.setenv(key, "/somewhere/else")
        accel.apply_override(data_dir)
        assert str(lib) in os.environ[key].split(os.pathsep)
        assert "/somewhere/else" in os.environ[key], "must not clobber the existing path"

    def test_applying_twice_does_not_duplicate_the_path(self, data_dir, tmp_path, monkeypatch):
        import os
        import sys
        lib = tmp_path / "libs"
        lib.mkdir()
        accel.write_state(data_dir, {"active": True, "verified": True,
                                     "lib_dir": str(lib)})
        key = "PATH" if sys.platform == "win32" else "LD_LIBRARY_PATH"
        monkeypatch.setenv(key, "")
        accel.apply_override(data_dir)
        accel.apply_override(data_dir)
        assert os.environ[key].split(os.pathsep).count(str(lib)) == 1


class TestActivationRequiresASurvivingProbe:
    def test_a_failed_probe_is_not_committed(self, data_dir, tmp_path, monkeypatch):
        lib = tmp_path / "libs"
        lib.mkdir()
        monkeypatch.setattr(accel, "probe_in_subprocess",
                            lambda d, **k: (False, "driver too old"))
        ok, detail = accel.activate(data_dir, lib)
        assert ok is False
        assert "driver too old" in detail
        # and crucially, the next start does not try to use it
        assert accel.active_lib_dir(data_dir) is None

    def test_a_passing_probe_is_committed(self, data_dir, tmp_path, monkeypatch):
        lib = tmp_path / "libs"
        lib.mkdir()
        monkeypatch.setattr(accel, "probe_in_subprocess", lambda d, **k: (True, "verified"))
        ok, _ = accel.activate(data_dir, lib)
        assert ok is True
        assert accel.active_lib_dir(data_dir) == lib

    def test_the_reason_for_a_failure_is_kept(self, data_dir, tmp_path, monkeypatch):
        # so the user is told why, rather than that it just did not work
        lib = tmp_path / "libs"
        lib.mkdir()
        monkeypatch.setattr(accel, "probe_in_subprocess",
                            lambda d, **k: (False, "CUDA driver version is insufficient"))
        accel.activate(data_dir, lib)
        assert "insufficient" in json.loads(accel.state_path(data_dir).read_text())["detail"]

    def test_deactivating_keeps_the_files(self, data_dir, tmp_path, monkeypatch):
        # re-enabling should not mean downloading a gigabyte again
        lib = tmp_path / "libs"
        lib.mkdir()
        monkeypatch.setattr(accel, "probe_in_subprocess", lambda d, **k: (True, "verified"))
        accel.activate(data_dir, lib)
        accel.deactivate(data_dir)
        assert accel.active_lib_dir(data_dir) is None
        assert accel.read_state(data_dir)["lib_dir"] == str(lib)


class TestTheProbeChild:
    """The child process, driven directly.

    llama_cpp is injected as a fake module rather than patched on the real one:
    the real one may not even be importable in the state being tested, which is
    the whole reason this runs in its own process.
    """

    @staticmethod
    def _fake_llama(monkeypatch, offload):
        import sys
        import types
        mod = types.ModuleType("llama_cpp")
        mod.llama_supports_gpu_offload = offload
        monkeypatch.setitem(sys.modules, "llama_cpp", mod)

    def test_reports_success_with_a_token_the_parent_looks_for(self, monkeypatch, capsys):
        self._fake_llama(monkeypatch, lambda: True)
        assert accel.run_probe("/anywhere") == 0
        assert "GPU_OFFLOAD_OK" in capsys.readouterr().out

    def test_loading_but_not_offloading_is_a_failure(self, monkeypatch, capsys):
        self._fake_llama(monkeypatch, lambda: False)
        assert accel.run_probe("/anywhere") == 2
        assert "GPU_OFFLOAD_OK" not in capsys.readouterr().out

    def test_a_crash_is_reported_not_raised(self, monkeypatch, capsys):
        # the child exists precisely to absorb this
        def boom():
            raise OSError("libcublas.so.12: cannot open shared object file")
        self._fake_llama(monkeypatch, boom)
        assert accel.run_probe("/anywhere") == 3
        assert "libcublas" in capsys.readouterr().err

    def test_a_library_that_will_not_import_is_absorbed(self, monkeypatch, capsys):
        # exactly what leaked between tests while writing this file
        import sys
        import types
        broken = types.ModuleType("llama_cpp")
        def _raise(*_a, **_k):
            raise FileNotFoundError("Shared library with base name 'llama' not found")
        broken.__getattr__ = _raise
        monkeypatch.setitem(sys.modules, "llama_cpp", broken)
        assert accel.run_probe("/anywhere") == 3
