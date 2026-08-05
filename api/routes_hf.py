"""browse Hugging Face for models, and fetch one.

The only routes in ThinkStack that reach the internet. Each is the direct
result of a click: nothing here runs on startup, on page load, or in the
background, because an offline-first app that quietly queries a remote API on
render is not offline-first in any sense a user would recognise.

The download route takes a repo id and a filename and builds the URL itself.
It never accepts a URL. The local API is reachable from the webview, which
Tauri treats as remote content, so an endpoint that fetched whatever URL it was
handed would be a general-purpose downloader pointed by whoever could reach it.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from config import settings
from domain.model_manager import huggingface as hf
from domain.model_manager.catalog import ModelSpec
from domain.model_manager.downloader import downloader
from domain.model_manager.registry import KNOWN_TASKS, Registry, entry_from_import

logger = logging.getLogger(__name__)
router = APIRouter()


class HfDownloadRequest(BaseModel):
    """explicit consent to fetch one file from one repository."""
    repo_id: str
    filename: str
    # what the model should do once it arrives. Empty is allowed -- the user can
    # assign it later from Bench -- but offering the choice here saves a step.
    tasks: list[str] = []


def _budget_gb() -> float:
    try:
        from infrastructure.hardware import max_safe_model_size_gb
        return max_safe_model_size_gb()
    except Exception:  # noqa: BLE001 - advisory only
        return 0.0


@router.get("/search")
async def search(q: str = Query(..., min_length=1), limit: int = 20):
    """repositories matching ``q`` that contain GGUF weights.

    Runs off the event loop: this is a network call to a third party and a slow
    response must not stall every other request the app is serving.
    """
    try:
        results = await asyncio.to_thread(hf.search_gguf_models, q, limit)
    except hf.HuggingFaceError as e:
        # 502, not 500: the failure is upstream, and the message is already
        # written for a human.
        raise HTTPException(status_code=502, detail=str(e)) from e

    return {"query": q, "results": [r.as_dict() for r in results]}


@router.get("/repo/{owner}/{name}")
async def repo(owner: str, name: str):
    """the GGUF files in one repository, with the one we would pick.

    Split across two path segments rather than a single ``repo_id`` query
    parameter so a slash cannot be smuggled in to reach a different path.
    """
    repo_id = f"{owner}/{name}"
    budget = _budget_gb()
    try:
        data = await asyncio.to_thread(hf.lookup, repo_id, budget)
    except hf.HuggingFaceError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    # Say which files this machine can actually hold, rather than leaving the
    # user to compare two numbers.
    for f in data["files"]:
        f["fits"] = budget <= 0 or f["size_gb"] <= budget
    data["budget_gb"] = round(budget, 1)
    return data


@router.post("/download")
async def download(request: HfDownloadRequest):
    """fetch one GGUF from Hugging Face. This IS the consent step.

    The URL is CONSTRUCTED from the repo id and filename; anything that is not
    a plain ``owner/name`` and a ``.gguf`` is refused before a socket opens.
    """
    try:
        url = hf.build_download_url(request.repo_id, request.filename)
    except hf.HuggingFaceError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if downloader.is_active():
        raise HTTPException(status_code=409, detail="A download is already running.")

    tasks = [t for t in request.tasks if t in KNOWN_TASKS]
    # Reuse the existing downloader: it already streams to a .part file and
    # renames only on success, so an interrupted fetch cannot leave a truncated
    # .gguf that llama.cpp would fail to load.
    spec = ModelSpec(
        name=request.filename,
        label=f"{request.repo_id.split('/')[-1]} ({request.filename})",
        size_gb=0.0,
        url=url,
        bundled=False,
        tasks=tuple(tasks),
    )

    asyncio.create_task(_download_and_register(spec, tasks))
    logger.info("user approved hugging face download of %s from %s",
                request.filename, request.repo_id)
    return {"status": "started", "name": spec.name, "repo_id": request.repo_id}


async def _download_and_register(spec: ModelSpec, tasks: list[str]) -> None:
    """download, then put it in the registry so it is actually usable.

    Without the second half a completed download leaves a file in the models
    directory that nothing routes to -- the user would have waited for a
    gigabyte and then had to go and find it under "already on this machine".
    """
    result = await asyncio.to_thread(downloader.download, spec, settings.models_dir)
    if result.get("status") != "done":
        return

    try:
        path = settings.models_dir / spec.name
        registry = Registry.load(settings.models_dir)
        if registry.by_path(path) is not None:
            return
        entry = entry_from_import(
            path, tasks, label="", origin="downloaded", managed=True,
        )
        registry.upsert(entry)
        registry.save(settings.models_dir)
        logger.info("registered downloaded model %s for %s",
                    entry.id, ", ".join(tasks) or "no tasks yet")
    except Exception as e:  # noqa: BLE001 - the file is there either way
        logger.warning("downloaded %s but could not register it: %s", spec.name, e)
