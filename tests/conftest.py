"""shared test fixtures, path setup, and isolation guards.

ensures the project root is importable so ``import config`` / ``import
domain...`` resolve when pytest runs from anywhere, and keeps unit tests
hermetic: no test may read the developer's real hardware profile from the
environment or leak the in-module hardware cache into the next test. anything
that would touch real user data takes an explicit tmp path.
"""

import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


@pytest.fixture(autouse=True)
def _isolate_hardware_state(monkeypatch):
    """reset global hardware state around every test.

    ``infrastructure.hardware`` caches the detected profile in a module global
    and ``profile_system`` prefers THINKSTACK_HW_PROFILE from the env. both would
    leak across tests, so clear them before each one. done lazily (import inside)
    so this fixture doesn't force the import when a test doesn't need it.
    """
    monkeypatch.delenv("THINKSTACK_HW_PROFILE", raising=False)
    try:
        import infrastructure.hardware as hw
        monkeypatch.setattr(hw, "_cached_profile", None, raising=False)
    except Exception:
        # module not importable in this test's context -- nothing to reset.
        pass
    yield


@pytest.fixture
def gguf_dir(tmp_path):
    """a temp models dir plus a helper to drop fake gguf files of a given size.

    returns (dir_path, make(name, size_mb)) so tests can build a models
    directory with models of known sizes for budget/routing checks.
    """
    d = tmp_path / "models"
    d.mkdir()

    def make(name: str, size_mb: float) -> "os.PathLike":
        p = d / name
        with open(p, "wb") as f:
            _make_sparse(f)
            f.truncate(int(size_mb * 1024 * 1024))
        return p

    return d, make


def _make_sparse(f) -> None:
    """Mark an open file sparse on Windows, so truncate() reserves no disk.

    On NTFS, extending a file ALLOCATES the bytes; one full run once left
    23.8 GB in %TEMP% and failed ~40 unrelated tests with ENOSPC. POSIX
    filesystems already make a truncated file sparse, so this is a no-op there.
    """
    if os.name != "nt":
        return
    import ctypes
    import msvcrt
    from ctypes import wintypes

    FSCTL_SET_SPARSE = 0x000900C4
    handle = msvcrt.get_osfhandle(f.fileno())
    returned = wintypes.DWORD()
    ctypes.windll.kernel32.DeviceIoControl(
        wintypes.HANDLE(handle), FSCTL_SET_SPARSE, None, 0, None, 0,
        ctypes.byref(returned), None,
    )


def allocated_bytes(path) -> int:
    """Disk actually used by a file, as opposed to its size."""
    if os.name == "nt":
        import ctypes
        high = ctypes.c_ulong(0)
        low = ctypes.windll.kernel32.GetCompressedFileSizeW(str(path), ctypes.byref(high))
        return (high.value << 32) + low
    return os.stat(path).st_blocks * 512
