"""System routes: health, the active model, background jobs, hardware,
graphics acceleration, and training-data counts.

`/health` is what build.sh, validate_bundle.py and the selftests poll to prove a
frozen backend serves requests (the desktop shell only waits for the port).
Hardware decisions come from infrastructure/capability.py; acceleration from
infrastructure/acceleration.py.
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from infrastructure.ollama_client import ollama_client
from infrastructure.hardware import profile_system, recommended_ctx_size
from infrastructure.jobs import job_queue
from domain.knowledge_base.repository import get_collection_stats
from domain.fine_tuning.data_collector import training_stats
from config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


class SetModelRequest(BaseModel):
    """request body for switching the active llm model."""
    model: str


@router.get("/health")
async def health_check():
    """Backend status, LLM runtime state and the effective configuration."""
    llm_status = await ollama_client.check_health()
    collection_stats = get_collection_stats()

    hw = profile_system()

    return {
        "status": "running",
        "llm": llm_status,
        "ollama": llm_status,
        "knowledge_base": collection_stats,
        "hardware": {
            "tier": hw.tier,
            "total_ram_gb": hw.total_ram_gb,
            "gpu": hw.gpu_name or "none",
            "vram_gb": hw.vram_gb,
            "recommended_ctx_size": recommended_ctx_size(hw.tier),
        },
        "config": {
            "llm_provider": settings.llm_provider,
            "llm_model_path": str(settings.llm_model_path),
            "ollama_model": settings.ollama_model,
            "embedding_model": settings.embedding_model,
            "chunk_size": settings.chunk_size,
        },
    }


@router.get("/models")
async def list_models():
    """Models the active runtime can see, and the configured one."""
    llm_status = await ollama_client.check_health()
    return {
        "provider": settings.llm_provider,
        "target_model": llm_status.get("target_model", settings.ollama_model),
        "available": llm_status.get("model_list", []),
        "target_available": llm_status.get("target_available", False),
    }


@router.post("/model")
async def set_model(request: SetModelRequest):
    """Switch the active model, globally, at runtime.

    The current model is released and the new one loads on the next
    generation, not here.
    """
    try:
        result = await ollama_client.set_model(request.model)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    llm_status = await ollama_client.check_health()
    return {
        **result,
        "provider": settings.llm_provider,
        "available": llm_status.get("model_list", []),
    }


@router.get("/jobs")
async def background_jobs():
    """What the background analysis queue is doing right now.

    `done`/`total` describe the current batch, so the interface can say
    "analysing paper 2 of 5" rather than spin. Both are 0 when idle, which is
    the cue to render nothing.
    """
    return job_queue.status()


@router.get("/stats")
async def system_stats():
    """Knowledge-base counts: documents, chunks, document ids."""
    return get_collection_stats()


@router.get("/hardware")
async def hardware_info():
    """The cached hardware profile and what it allows."""
    from dataclasses import asdict
    from infrastructure.hardware import max_safe_model_size_gb

    hw = profile_system()
    return {
        **asdict(hw),
        "recommended_ctx_size": recommended_ctx_size(hw.tier),
        "max_safe_model_size_gb": max_safe_model_size_gb(),
    }


@router.post("/diagnose")
async def diagnose_machine():
    """Re-examine this machine, discarding the cached profile.

    The profile is cached at startup because hardware does not change while the
    app runs -- but closing a memory hog or installing a driver does change
    what it can do, and nothing else makes it look again.

    POST rather than GET because it discards cached state. It reads nothing the
    user owns and changes no setting.
    """
    import infrastructure.hardware as hardware
    from infrastructure.capability import for_this_machine
    from infrastructure.ollama_client import ollama_client

    # Force a fresh look rather than replaying the startup answer.
    hardware._cached_profile = None
    ollama_client._cap = None

    return for_this_machine().report()


# ── graphics acceleration ────────────────────────────────────────────────
# Kept beside /diagnose because it answers the same question -- what can this
# machine do -- and Bench renders both on one card. Splitting them would put
# "your machine has a GPU" and "here is how to use it" behind two calls that
# could disagree.


@router.get("/acceleration")
async def acceleration_status():
    """What this machine could do with graphics acceleration, and what it is doing.

    Everything the Bench card needs in one payload: the devices the graphics
    driver exposes, whether an offer is available and what it would cost, and
    whether a previous install is in effect. One call, so the panel can never
    render two halves that disagree.
    """
    from infrastructure import acceleration, vulkan
    from infrastructure.accel_download import fetch_manifest, installer
    from infrastructure.hardware import engine_supports_gpu_offload

    # A graphics driver is third-party code in our process and can raise from
    # anything. Bench's machine card depends on this response, so any failure
    # degrades to "no offer" rather than an error.
    try:
        plan = acceleration.plan(settings.data_dir)
        devices = vulkan.report()
    except Exception as e:  # noqa: BLE001 - a driver fault is not our crash
        logger.warning("graphics detection failed: %s", e)
        plan = acceleration.Plan(reason="Graphics hardware could not be read on "
                                        "this machine.")
        devices = {"loader_present": False, "devices": [], "would_use": None}

    state = acceleration.read_state(settings.data_dir)
    payload = {
        "active": engine_supports_gpu_offload(),
        "devices": devices,
        "plan": plan.as_dict(),
        "install": installer.progress(),
        # a previous attempt that failed should say why rather than silently
        # offering the same button again
        "last_attempt": {
            "verified": bool(state.get("verified")),
            "detail": state.get("detail", ""),
        } if state else None,
    }

    # Replace the built-in estimate with the measured figure when the release
    # manifest can be read. The number shown before asking for consent should
    # be the number that will actually be downloaded.
    if plan.supported:
        manifest = fetch_manifest(acceleration.platform_key())
        if manifest and manifest.get("bytes"):
            payload["plan"]["download_bytes"] = int(manifest["bytes"])
            payload["plan"]["download_mb"] = round(int(manifest["bytes"]) / 1048576)
            payload["plan"]["measured"] = True
    return payload


@router.post("/acceleration/enable")
async def acceleration_enable():
    """Download the graphics engine and switch it on, if it works here.

    Runs in a worker thread: the download is tens of megabytes and the verify
    step spawns a process, and neither may block the event loop that is also
    serving the page showing the progress bar.
    """
    import asyncio

    from infrastructure import acceleration
    from infrastructure.accel_download import installer

    plan = acceleration.plan(settings.data_dir)
    if not plan.supported:
        raise HTTPException(status_code=400, detail=plan.reason)
    if installer.busy():
        return installer.progress()

    key = acceleration.platform_key()
    asyncio.get_running_loop().run_in_executor(
        None, installer.install, settings.data_dir, key
    )
    return {"status": "downloading", "device": plan.device}


@router.get("/acceleration/progress")
async def acceleration_progress():
    from infrastructure.accel_download import installer
    return installer.progress() or {"status": "idle"}


@router.post("/acceleration/cancel")
async def acceleration_cancel():
    from infrastructure.accel_download import installer
    return {"cancelled": installer.cancel()}


@router.post("/acceleration/disable")
async def acceleration_disable():
    """Go back to the processor. The files stay, so re-enabling is instant."""
    from infrastructure import acceleration

    acceleration.deactivate(settings.data_dir)
    return {"active": False, "restart_required": True}


@router.get("/training-stats")
async def get_training_stats():
    """Counts of collected training pairs, per task.

    Counts only, never content -- the data stays on the user's machine.
    """
    return {
        "task_counts": training_stats(),
        "privacy": "all training data is stored locally and never leaves this device",
    }
