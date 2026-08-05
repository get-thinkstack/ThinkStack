"""model setup api.

powers the first-run flow: report what the machine can run, what models it
already has (including via Ollama / LM Studio), and whether a better model is
worth offering. downloading only ever happens through an explicit POST, so the
app never reaches out to the network on its own.
"""

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from config import settings
from domain.model_manager import catalog
from domain.model_manager.discovery import discover_all, installed_names
from domain.model_manager.downloader import downloader
from infrastructure.hardware import max_safe_model_size_gb, profile_system

logger = logging.getLogger(__name__)
router = APIRouter()


class DownloadRequest(BaseModel):
    """explicit user consent to fetch one catalog model."""
    name: str


@router.get("/setup")
async def model_setup():
    """everything the first-run screen needs, in one call.

    reports the hardware budget, models already on this machine and where they
    came from, and at most one suggested upgrade. `needs_permission` is the
    signal for the UI to show a consent prompt -- when it is false there is
    nothing to ask about and the app should start straight away.
    """
    hw = profile_system()
    budget = max_safe_model_size_gb()

    # discovery touches the filesystem and probes ollama over http; keep it off
    # the event loop so a slow probe cannot block other requests.
    found = await asyncio.to_thread(
        discover_all, settings.models_dir, settings.ollama_base_url
    )
    installed = installed_names(found)
    # tier as well as budget: a model that FITS can still be a bad
    # suggestion on a slow machine. see catalog.suggested_upgrade.
    upgrade = catalog.suggested_upgrade(budget, installed, hw.tier)

    return {
        "hardware": {
            "tier": hw.tier,
            "total_ram_gb": hw.total_ram_gb,
            "available_ram_gb": hw.available_ram_gb,
            "gpu": hw.gpu_name or "none",
            "budget_gb": budget,
        },
        "installed": [
            {
                "name": m.name,
                "source": m.source,
                "size_gb": m.size_gb,
                "usable_directly": m.usable_directly,
            }
            for m in found
        ],
        "runnable": [s.name for s in catalog.runnable_on(budget)],
        "suggested_upgrade": (
            {
                "name": upgrade.name,
                "label": upgrade.label,
                "size_gb": upgrade.size_gb,
                "description": upgrade.description,
                "tasks": list(upgrade.tasks),
            }
            if upgrade
            else None
        ),
        # the UI only prompts when there is a real, actionable improvement
        "needs_permission": upgrade is not None,
    }


@router.get("/catalog")
async def list_catalog():
    """every model ThinkStack knows about, and whether it ships with the app."""
    return {
        "models": [
            {
                "name": s.name,
                "label": s.label,
                "size_gb": s.size_gb,
                "bundled": s.bundled,
                "tasks": list(s.tasks),
                "min_ram_gb": s.min_ram_gb,
                "description": s.description,
            }
            for s in catalog.CATALOG
        ]
    }


@router.post("/download")
async def start_download(request: DownloadRequest):
    """download a catalog model. this IS the consent step.

    refuses anything not in the catalog, so a caller cannot point the app at an
    arbitrary URL.
    """
    spec = catalog.by_name(request.name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"unknown model: {request.name}")
    if downloader.is_active():
        raise HTTPException(status_code=409, detail="a download is already running")

    # run in a worker thread; the client polls /download/status for progress
    asyncio.create_task(
        asyncio.to_thread(downloader.download, spec, settings.models_dir)
    )
    logger.info("user approved download of %s (%.2f gb)", spec.name, spec.size_gb)
    return {"status": "started", "name": spec.name, "size_gb": spec.size_gb}


@router.get("/download/status")
async def download_status():
    """progress of the current or most recent download."""
    return downloader.progress or {"status": "idle"}


@router.post("/download/cancel")
async def cancel_download():
    """stop an in-flight download and discard the partial file."""
    return {"cancelled": downloader.cancel()}
