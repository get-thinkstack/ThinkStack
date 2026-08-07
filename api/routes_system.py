"""
system api routes.

provides health check, model status, and collection statistics
endpoints for monitoring the application state.
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
    """check overall system health including llm runtime connectivity.

    returns:
        system status, llm connection state, and configuration.
    """
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
    """list all models available in the active local llm runtime.

    returns:
        list of available models and the currently configured target.
    """
    llm_status = await ollama_client.check_health()
    return {
        "provider": settings.llm_provider,
        "target_model": llm_status.get("target_model", settings.ollama_model),
        "available": llm_status.get("model_list", []),
        "target_available": llm_status.get("target_available", False),
    }


@router.post("/model")
async def set_model(request: SetModelRequest):
    """switch the active llm model at runtime (global for the app).

    for llama.cpp this releases the current model and loads the requested
    gguf file on the next generation. use a model name returned by the
    /models endpoint.

    args:
        request: the target model name (e.g. a gguf filename).

    returns:
        the now-active model and updated runtime status.
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
    """what the background analysis queue is doing right now.

    the ui polls this to draw a determinate progress bar: ``done``/``total``
    describe the current batch, so "analysing paper 2 of 5" is real rather than
    a spinner that cannot say how far along it is. both are 0 when idle, which
    is the client's cue to render nothing at all.

    returns:
        ``{running, label, queued, done, total, last_error}``.
    """
    return job_queue.status()


@router.get("/stats")
async def system_stats():
    """get knowledge base statistics.

    returns:
        total documents, chunks, and document id listing.
    """
    return get_collection_stats()


@router.get("/hardware")
async def hardware_info():
    """return detected hardware specifications.

    reports the machine's ram, cpu cores, gpu, vram, and the
    computed performance tier used for model loading decisions.

    returns:
        hardware profile with recommendations.
    """
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
    """Re-examine this machine and report what it can do.

    The app profiles the machine once at startup and caches it, which is right:
    hardware does not change while the app runs, and probing on every launch
    would slow every launch. But it means a user who adds memory, closes a
    memory-hog, or installs a GPU-capable runtime has no way to make the app
    look again -- and someone who upgraded from a build that predates this has
    never been profiled by it at all.

    POST rather than GET because it discards cached state. It reads nothing
    the user owns and changes no setting: it only re-answers "what can this
    machine do".

    Returns the same structure the Diagnose screen renders, which is also what
    the model picker will consume when the two are merged.
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

    # Acceleration is optional, so nothing about it may take this endpoint
    # down. A graphics driver is third-party code loaded into our process and
    # can do anything, including raise from a function documented not to --
    # and Bench renders the machine card from this response. Degrade to "no
    # offer", which is the state the app was in anyway.
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
    """return counts of collected training data pairs.

    privacy-safe: returns only counts, never content.
    the training data stays on the user's machine.

    returns:
        dictionary mapping task types to example counts.
    """
    return {
        "task_counts": training_stats(),
        "privacy": "all training data is stored locally and never leaves this device",
    }
