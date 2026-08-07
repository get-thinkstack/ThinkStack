r"""GPU acceleration as something the user can switch on, not something we ship.

ThinkStack ships a CPU-only build of llama.cpp -- deliberately, because a GPU
build that most users cannot use is an installer nobody downloads. That is why
an RTX 4050 owner was told, correctly, that the engine could not use their card,
and then offered nothing at all. This module is the "and then".

── Why Vulkan rather than CUDA ──

CUDA was the obvious choice and the wrong one. It reaches NVIDIA cards only, and
only through NVIDIA's proprietary stack: prebuilt wheels exist, so it *looked*
cheapest, but it needs another ~557 MB of NVIDIA maths libraries on any machine
without the CUDA toolkit.

Vulkan reaches NVIDIA, AMD, Intel and integrated graphics through the loader
that ships **with the graphics driver**. The laptop this was written on has no
NVIDIA packages installed at all, and Vulkan already reports:

    Intel(R) UHD Graphics (TGL GT1)                 integrated
    NVIDIA GeForce RTX 3050 Ti Laptop (NVK GA107)   discrete
    llvmpipe (LLVM 22.1.8)                          software  <- excluded

Both real devices are reachable today, with nothing installed. CUDA would have
reached neither. See infrastructure/vulkan.py.

The cost is honest: Vulkan is slower than CUDA on an NVIDIA card. It is far
faster than the processor on every card, which is the comparison that matters
when the alternative is no acceleration at all.

── What is actually downloaded ──

Not drivers. **Our own program's GPU build.** The distinction is the whole
answer to "why can you not use the drivers I already have":

    libvulkan.so.1     the LOADER.   Theirs. Ships with the driver. Never ours.
    libggml-vulkan.so  the KERNELS.  OURS. llama.cpp's own GPU code, which
                                     exists on no machine anywhere.

Only the second is downloaded, and no NVIDIA runtime is needed at all.

── Why an environment variable rather than replacing files ──

`llama_cpp` reads `LLAMA_CPP_LIB_PATH` and loads its shared libraries from
there, so the download lives in the user's writable data directory and is
pointed at. Nothing inside the installation is touched -- on Linux that is a
read-only AppImage mount, and on macOS a signed bundle.

── Why a subprocess decides whether it worked ──

A library that downloads cleanly can still fail to load: a driver too old, a
missing dependency, a CPU without the instructions the build assumes. Finding
that out inside the running backend means the backend is already damaged, on a
machine where this app is the only thing that can read the user's papers. So the
probe happens in a process that is allowed to crash, and the override is
committed only if that process reports success.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from infrastructure import vulkan

logger = logging.getLogger(__name__)

# Where the downloaded libraries live. Beside the models, for the same reason:
# it is the writable place that survives an update.
ACCEL_DIRNAME = "accel"
STATE_FILENAME = "state.json"

# Our Vulkan build of llama.cpp. Measured from the CI artifact rather than
# guessed: a wrong figure here is a promise broken at download time. CI writes
# it into the release manifest; this is the fallback used before one is fetched.
ENGINE_BYTES_ESTIMATE = 90 * 1048576


@dataclass(frozen=True)
class Component:
    """one downloadable piece, and whether the machine already has it."""
    key: str
    label: str
    bytes_: int
    present: bool = False
    # ours vs theirs -- shown to the user, because "this is our own program's
    # GPU build" is the sentence that answers "why not use my drivers".
    ours: bool = False


@dataclass
class Plan:
    """what switching acceleration on would involve, before doing it."""
    supported: bool = False
    reason: str = ""
    device: str = ""
    device_kind: str = ""
    components: list[Component] = field(default_factory=list)

    @property
    def to_download(self) -> list[Component]:
        return [c for c in self.components if not c.present]

    @property
    def download_bytes(self) -> int:
        return sum(c.bytes_ for c in self.to_download)

    def as_dict(self) -> dict:
        return {
            "supported": self.supported,
            "reason": self.reason,
            "device": self.device,
            "device_kind": self.device_kind,
            "download_bytes": self.download_bytes,
            "download_mb": round(self.download_bytes / 1048576),
            "components": [
                {"key": c.key, "label": c.label, "ours": c.ours,
                 "present": c.present, "mb": round(c.bytes_ / 1048576)}
                for c in self.components
            ],
        }


def engine_already_accelerated() -> bool:
    """is the llama.cpp we are about to use already GPU-capable?

    True when a user installed such a build themselves, or a previous
    activation is in effect. Either way there is nothing to offer.
    """
    try:
        from llama_cpp import llama_supports_gpu_offload
        return bool(llama_supports_gpu_offload())
    except (ImportError, AttributeError, OSError):
        return False


def platform_key() -> str | None:
    """the wheel family for this machine, or None if we have nothing to offer."""
    if platform.machine().lower() not in ("x86_64", "amd64"):
        return None
    if sys.platform.startswith("linux"):
        return "linux-x86_64"
    if sys.platform == "win32":
        return "windows-x86_64"
    # macOS is Metal, not CUDA -- a different build and a different conversation
    return None


def accel_dir(data_dir: Path) -> Path:
    return Path(data_dir) / ACCEL_DIRNAME


def state_path(data_dir: Path) -> Path:
    return accel_dir(data_dir) / STATE_FILENAME


def read_state(data_dir: Path) -> dict:
    """what a previous activation left behind. Never raises."""
    try:
        return json.loads(state_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def write_state(data_dir: Path, state: dict) -> None:
    p = state_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")


def active_lib_dir(data_dir: Path) -> Path | None:
    """the library directory to use, if one has been activated AND verified.

    ``verified`` is written only by a probe that ran in its own process and
    survived. An unverified directory is ignored, which is what keeps a bad
    download from taking the backend down with it on every start.
    """
    state = read_state(data_dir)
    if not state.get("active") or not state.get("verified"):
        return None
    lib = state.get("lib_dir")
    if not lib:
        return None
    p = Path(lib)
    return p if p.is_dir() else None


def apply_override(data_dir: Path) -> str | None:
    """point llama_cpp at the activated libraries. Call BEFORE importing it.

    Returns the directory applied, or None. Safe to call when nothing is
    activated, which is the common case.
    """
    lib = active_lib_dir(data_dir)
    if lib is None:
        return None

    os.environ["LLAMA_CPP_LIB_PATH"] = str(lib)
    # any libraries shipped beside the kernels are found through the normal
    # loader path, which llama_cpp does not set for us
    key = "PATH" if sys.platform == "win32" else "LD_LIBRARY_PATH"
    existing = os.environ.get(key, "")
    if str(lib) not in existing.split(os.pathsep):
        os.environ[key] = f"{lib}{os.pathsep}{existing}" if existing else str(lib)

    logger.info("GPU acceleration active: %s", lib)
    return str(lib)


def plan(data_dir: Path) -> Plan:
    """what turning acceleration on would take on this machine.

    Nothing is passed in: the question is entirely about what Vulkan can see,
    and that is asked of the loader rather than inferred from a hardware
    profile. A profile can say "there is an NVIDIA card"; only Vulkan can say
    whether anything is able to *use* it, which on a machine with the
    open-source drivers is a different answer.
    """
    if platform_key() is None:
        return Plan(reason="ThinkStack only offers graphics acceleration on "
                           "64-bit Linux and Windows so far.")

    if engine_already_accelerated():
        return Plan(reason="Graphics acceleration is already working on this "
                           "machine.")

    if not vulkan.available():
        return Plan(reason="No Vulkan driver was found. Installing the graphics "
                           "driver for your card would make acceleration "
                           "possible.")

    device = vulkan.best_device()
    if device is None:
        seen = vulkan.enumerate_devices()
        if seen:
            # the honest case for a machine where Vulkan only reports a software
            # rasteriser: there IS a device, and using it would be slower
            return Plan(reason="Vulkan is available, but only through software "
                               "rendering, which would be slower than your "
                               "processor.")
        return Plan(reason="No graphics device was found that could run the "
                           "model faster than your processor.")

    return Plan(
        supported=True,
        device=device.label,
        device_kind=device.kind,
        components=[
            Component(
                key="engine",
                label="ThinkStack's graphics engine",
                bytes_=ENGINE_BYTES_ESTIMATE,
                present=False,
                ours=True,
            ),
        ],
    )


# ── the probe ────────────────────────────────────────────────────────────

PROBE_FLAG = "--probe-acceleration"


def probe_in_subprocess(lib_dir: Path, timeout: int = 90) -> tuple[bool, str]:
    """load the downloaded libraries in a process that is allowed to die.

    A library can download perfectly and still fail to load: a driver older
    than the CUDA build expects, a missing dependency, or a CPU lacking the
    instructions the build assumes. Finding that out inside the running backend
    means the backend is already broken -- and on a machine where the app is
    the only thing that can read the user's papers, that is not an acceptable
    way to learn.

    Returns ``(ok, detail)``. Never raises.
    """
    exe = sys.executable
    # A frozen build has no python to call, so it re-invokes ITSELF with a flag
    # main.py handles before anything heavy is imported.
    cmd = ([exe, PROBE_FLAG, str(lib_dir)] if getattr(sys, "frozen", False)
           else [exe, str(Path(__file__).resolve().parents[1] / "main.py"),
                 PROBE_FLAG, str(lib_dir)])

    env = dict(os.environ)
    env["LLAMA_CPP_LIB_PATH"] = str(lib_dir)
    key = "PATH" if sys.platform == "win32" else "LD_LIBRARY_PATH"
    env[key] = f"{lib_dir}{os.pathsep}{env.get(key, '')}"
    env["THINKSTACK_PROBE"] = "1"

    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "The graphics libraries took too long to load and were stopped."
    except OSError as e:
        return False, f"Could not run the check: {e}"

    if r.returncode == 0 and "GPU_OFFLOAD_OK" in (r.stdout or ""):
        return True, "verified"

    detail = (r.stderr or r.stdout or "").strip().splitlines()
    tail = detail[-1] if detail else f"exit code {r.returncode}"
    return False, tail[:300]


def run_probe(lib_dir: str) -> int:
    """the child side of :func:`probe_in_subprocess`. Called from main.py.

    Deliberately tiny: import llama.cpp, ask whether it can offload, print a
    token the parent looks for. Anything that goes wrong here takes only this
    process with it.
    """
    try:
        from llama_cpp import llama_supports_gpu_offload
        if llama_supports_gpu_offload():
            print("GPU_OFFLOAD_OK")
            return 0
        print("the libraries loaded but report no GPU support", file=sys.stderr)
        return 2
    except Exception as e:  # noqa: BLE001 - this process exists to absorb it
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 3


def activate(data_dir: Path, lib_dir: Path) -> tuple[bool, str]:
    """verify, then switch on. Nothing unverified is ever committed."""
    ok, detail = probe_in_subprocess(lib_dir)
    write_state(data_dir, {
        "active": ok,
        "verified": ok,
        "lib_dir": str(lib_dir),
        "detail": detail,
        "platform": platform_key(),
    })
    return ok, detail


def deactivate(data_dir: Path) -> None:
    """go back to the processor. The files stay, so re-enabling is instant."""
    state = read_state(data_dir)
    state.update(active=False, verified=False)
    write_state(data_dir, state)
