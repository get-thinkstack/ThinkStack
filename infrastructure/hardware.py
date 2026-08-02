"""
hardware profiler module.

detects system ram, cpu cores, and gpu vram to classify the machine
into a performance tier and recommend safe model loading parameters.
prevents oom crashes by ensuring the llm context size and gpu offload
are tuned to the available resources.
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class HardwareProfile:
    """snapshot of the machine's compute resources."""
    total_ram_gb: float = 0.0
    available_ram_gb: float = 0.0
    cpu_cores: int = 1
    gpu_name: str = ""
    vram_gb: float = 0.0
    has_cuda: bool = False
    tier: str = "low"  # low | medium | high


def _detect_ram() -> tuple[float, float]:
    """return (total_gb, available_gb) using psutil.

    a failure here is not cosmetic: 0.0 total ram classifies the machine as the
    "low" tier, which pins context size and model choice to the most
    conservative settings for the life of the process. so it is logged at error
    level with the real exception -- the previous warning said only "psutil not
    installed", which was a guess that sent the packaged-build investigation
    after the wrong cause.
    """
    try:
        import psutil
        mem = psutil.virtual_memory()
        return round(mem.total / (1024 ** 3), 1), round(mem.available / (1024 ** 3), 1)
    except Exception as e:  # noqa: BLE001 - never let hardware probing kill startup
        logger.error(
            "ram detection failed (%s: %s); falling back to the low tier",
            type(e).__name__, e, exc_info=True,
        )
        return 0.0, 0.0


def _detect_cpu_cores() -> int:
    """return the number of physical cpu cores."""
    try:
        import psutil
        return psutil.cpu_count(logical=False) or os.cpu_count() or 1
    except ImportError:
        return os.cpu_count() or 1


def _detect_gpu() -> tuple[str, float, bool]:
    """return (gpu_name, vram_gb, has_cuda) using torch if available."""
    try:
        import torch
        if torch.cuda.is_available():
            name = torch.cuda.get_device_name(0)
            # total_memory, not total_mem. the misspelling raised
            # AttributeError -- which was not caught below -- so on a machine
            # that actually HAS cuda, probing the gpu crashed the caller
            # instead of degrading to "no gpu". AttributeError is caught now
            # so a future torch rename cannot do the same thing again.
            vram = round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 1)
            return name, vram, True
    except (ImportError, RuntimeError, AssertionError, AttributeError) as e:
        logger.warning("gpu detection failed, assuming none: %s", e)
    return "", 0.0, False


def _classify_tier(total_ram_gb: float, vram_gb: float) -> str:
    """classify a machine into a performance tier.

    tiers:
        low:    <12 gb ram and no usable gpu (<2 gb vram)
        medium: 12-24 gb ram or 2-8 gb vram
        high:   >24 gb ram or >8 gb vram
    """
    if vram_gb > 8 or total_ram_gb > 24:
        return "high"
    if vram_gb >= 2 or total_ram_gb >= 12:
        return "medium"
    return "low"


def _profile_from_env() -> HardwareProfile | None:
    """rebuild the profile from THINKSTACK_HW_PROFILE, set by the tauri shell.

    the desktop app diagnoses the machine natively (src-tauri/src/diagnosis.rs)
    before spawning this backend and passes the result as json. preferring it
    means the packaged app never imports torch or probes cuda just to size the
    model — that probe is slow and can stall on a broken driver. returns none
    when the var is absent (e.g. the backend run standalone / in dev), so the
    caller falls back to local detection.
    """
    raw = os.environ.get("THINKSTACK_HW_PROFILE")
    if not raw:
        return None
    try:
        d = json.loads(raw)
        total = float(d.get("total_ram_gb", 0.0))
        vram = float(d.get("vram_gb", 0.0))
        return HardwareProfile(
            total_ram_gb=total,
            available_ram_gb=float(d.get("available_ram_gb", 0.0)),
            cpu_cores=int(d.get("cpu_cores") or d.get("cpu_threads") or 1),
            gpu_name=str(d.get("gpu_name", "")),
            vram_gb=vram,
            has_cuda=bool(d.get("has_cuda", False)),
            tier=str(d.get("tier") or _classify_tier(total, vram)),
        )
    except (ValueError, TypeError) as e:
        logger.warning("could not parse THINKSTACK_HW_PROFILE, detecting locally: %s", e)
        return None


def profile_system() -> HardwareProfile:
    """detect hardware and return a typed profile.

    this is the primary entry point. results are cached in-module after the
    first call. prefers the native profile supplied by the desktop shell via
    THINKSTACK_HW_PROFILE; only when that is absent does it detect locally
    (which imports torch for the gpu probe).

    returns:
        a populated HardwareProfile instance.
    """
    global _cached_profile
    if _cached_profile is not None:
        return _cached_profile

    from_env = _profile_from_env()
    if from_env is not None:
        logger.info(
            "hardware profile (from shell): %s tier - %.1f gb ram (%.1f free), "
            "%d cores, %s (%.1f gb vram)",
            from_env.tier, from_env.total_ram_gb, from_env.available_ram_gb,
            from_env.cpu_cores, from_env.gpu_name or "no gpu", from_env.vram_gb,
        )
        _cached_profile = from_env
        return from_env

    total_ram, avail_ram = _detect_ram()
    cores = _detect_cpu_cores()
    gpu_name, vram, has_cuda = _detect_gpu()
    tier = _classify_tier(total_ram, vram)

    profile = HardwareProfile(
        total_ram_gb=total_ram,
        available_ram_gb=avail_ram,
        cpu_cores=cores,
        gpu_name=gpu_name,
        vram_gb=vram,
        has_cuda=has_cuda,
        tier=tier,
    )

    logger.info(
        "hardware profile (detected): %s tier - %.1f gb ram (%.1f free), %d cores, %s (%.1f gb vram)",
        tier, total_ram, avail_ram, cores,
        gpu_name or "no gpu", vram,
    )

    _cached_profile = profile
    return profile


_cached_profile: HardwareProfile | None = None


def recommended_ctx_size(tier: str | None = None) -> int:
    """return a safe context size for the given tier.

    args:
        tier: performance tier string. if none, auto-detects.

    returns:
        recommended n_ctx value (2048, 4096, or 8192).
    """
    if tier is None:
        tier = profile_system().tier
    return {"low": 2048, "medium": 4096, "high": 8192}.get(tier, 2048)


def recommended_gpu_layers(vram_gb: float | None = None, model_size_gb: float = 1.0) -> int:
    """compute how many layers to offload to the gpu.

    a rough heuristic: each layer of a typical 1-3b model uses ~30-60 mb
    of vram. we leave 0.5 gb headroom for the kv-cache and cuda overhead.

    args:
        vram_gb: available gpu memory. if none, auto-detects.
        model_size_gb: approximate model file size on disk.

    returns:
        number of gpu layers to offload. 0 means cpu-only,
        -1 means offload all layers.
    """
    if vram_gb is None:
        vram_gb = profile_system().vram_gb

    if vram_gb < 1.5:
        return 0  # not enough vram for any useful offload

    usable_vram = vram_gb - 0.5  # headroom
    if model_size_gb <= usable_vram:
        return -1  # full offload fits

    # partial offload: estimate fraction of layers that fit
    # most gguf models have 24-32 layers; assume 32 for safety
    fraction = usable_vram / model_size_gb
    layers = int(fraction * 32)
    return max(0, min(layers, 32))


def max_safe_model_size_gb(
    available_ram_gb: float | None = None,
    vram_gb: float | None = None,
) -> float:
    """compute the maximum model file size we can safely load.

    reserves 3 gb for the os, embedding model (~0.1 gb), python, and
    the frontend. the model can live in ram, vram, or both.

    args:
        available_ram_gb: current free system ram.
        vram_gb: total gpu vram.

    returns:
        maximum safe model size in gb.
    """
    if available_ram_gb is None or vram_gb is None:
        profile = profile_system()
        available_ram_gb = profile.available_ram_gb if available_ram_gb is None else available_ram_gb
        vram_gb = profile.vram_gb if vram_gb is None else vram_gb

    ram_budget = max(0, available_ram_gb - 3.0)
    # model can span ram + vram
    return round(ram_budget + vram_gb, 1)


def model_file_size_gb(model_path: Path) -> float:
    """return the size of a model file in gb.

    args:
        model_path: path to the gguf file.

    returns:
        file size in gigabytes, or 0.0 if not found.
    """
    try:
        return round(model_path.stat().st_size / (1024 ** 3), 2)
    except (OSError, FileNotFoundError):
        return 0.0
