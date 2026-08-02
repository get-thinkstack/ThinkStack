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
