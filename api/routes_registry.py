"""Bench's model routes: what this install has, what each model does, add and
remove.

`GET` returns one snapshot (`_snapshot`) with every model, what each task
resolves to right now, models found on the machine but not registered, and the
catalog judged against this machine. It is one call because a card's status
depends on the other entries.

Two rules this module keeps:
- Bench must resolve routing exactly as generation does: the same router, the
  same budget (infrastructure/capability.py), the same fallback. A Bench that
  disagrees with the runtime is the failure this module exists to prevent.
- Writes state their consequence: removing a model reports what stops working;
  importing validates the file first; only files ThinkStack created can be
  deleted from disk.

Storage and routing logic: domain/model_manager/registry.py and router.py.
Catalog downloads are api/routes_models.py.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from config import settings
from domain.model_manager.downloader import downloader
from domain.model_manager.manifest import BundledManifest
from domain.model_manager.registry import (
    KNOWN_TASKS,
    ModelImportError,
    Registry,
    entry_from_import,
    removal_warning,
)
from domain.model_manager.router import resolve

logger = logging.getLogger(__name__)
router = APIRouter()


class ImportRequest(BaseModel):
    """a gguf the user picked off their own disk."""
    path: str
    tasks: list[str] = Field(default_factory=list)
    label: str = ""


class AssignRequest(BaseModel):
    """change what a registered model is used for."""
    tasks: list[str] | None = None
    label: str | None = None


def _capability():
    """This machine's capability, or None when it cannot be measured.

    Not `hardware.max_safe_model_size_gb`: that is a second, different budget
    (`available - 3.0 + vram` against capability's `size + 1.0 <= available`),
    and only capability.py may decide, so Bench and Diagnose agree.
    """
    try:
        from infrastructure.capability import for_this_machine
        return for_this_machine()
    except Exception as e:  # noqa: BLE001 - budgeting is advisory
        logger.warning("could not read this machine's capability: %s", e)
        return None


def _runs_slowly(size_gb: float, gpu_gb: float) -> bool:
    """True when the model cannot go on a GPU the engine can use AND is too
    big for a processor to answer in tolerable time. Size 0 = unmeasured."""
    if size_gb <= 0:
        return False
    from domain.model_manager.catalog import CPU_COMFORTABLE_GB
    if gpu_gb > 0 and size_gb <= gpu_gb:
        return False
    return size_gb > CPU_COMFORTABLE_GB


def _base_model():
    """The model the runtime falls back to, or None.

    Asked of the client (`_resolve_llama_model_path`), never re-derived, so
    Bench's answer cannot drift from what generation actually does.
    """
    try:
        from infrastructure.ollama_client import ollama_client
        return ollama_client._resolve_llama_model_path()
    except Exception as e:  # noqa: BLE001 - no model at all is a valid state
        logger.debug("no base model available: %s", e)
        return None


def _legacy_defaults(task: str) -> list[str]:
    """the deprecated hardcoded task map, still honoured as a last resort."""
    try:
        from infrastructure.ollama_client import OllamaClient
        return list(OllamaClient.TASK_MODEL_MAP.get(task, []))
    except Exception:  # noqa: BLE001
        return []


def _snapshot() -> dict:
    """Everything Bench needs about models, in one consistent payload."""
    registry = Registry.load(settings.models_dir)
    manifest = BundledManifest.load(settings.bundled_models_dir)
    cap = _capability()
    # The SAME budget the runtime routes on. Bench must not compute its own, or
    # it will confidently show a model as usable that generation then skips.
    from infrastructure.hardware import max_safe_model_size_gb
    try:
        budget = max_safe_model_size_gb()
    except Exception as e:  # noqa: BLE001 - advisory
        logger.warning("could not compute the model budget: %s", e)
        budget = 0.0
    # capability supplies the SENTENCE when something does not fit, so the
    # explanation Bench prints is the one the Diagnose screen would give.
    plan_for_size = cap.plan_for_size if cap is not None else None
    # Memory the ENGINE can offload to -- not the card's spec sheet.
    # Zero on a CPU-only build, and zero when the shipped llama.cpp
    # cannot use the GPU that is present.
    gpu_gb = cap.usable_gpu_memory_gb if cap is not None else 0.0

    # what each task would actually use right now -- the honest answer, after
    # budget and existence checks, not just what is assigned.
    base_model = _base_model()
    routing = {}
    _resolutions = {}
    for task in KNOWN_TASKS:
        r = resolve(
            task,
            registry=registry,
            manifest=manifest,
            models_dir=settings.models_dir,
            budget_gb=budget,
            legacy_defaults=_legacy_defaults(task),
            plan_for_size=plan_for_size,
            base_model=base_model,
        )
        # A raw gguf filename ("qwen2.5-0.5b-instruct-q4_k_m.gguf") is a
        # build artefact, not a name a reader should have to parse. Resolve it
        # to the label the rest of the UI uses.
        routing[task] = {**r.as_dict(), **_describe(r, registry)}
        _resolutions[task] = r

    models = []
    for e in registry.models:
        # Jobs this model is assigned but NOT doing (too large for free memory
        # right now, or outranked), said on its own card.
        not_in_use = [
            task for task in e.tasks
            if (r := _resolutions.get(task)) is not None
            and r.entry_id != e.id
            and (not r.path or Path(r.path) != Path(e.path or "/nonexistent"))
        ]
        models.append({
            **e.as_dict(),
            "status": e.status(budget),
            # The same judgement the download catalog makes, applied to models
            # already installed. Without it a user could assign a 4B they own
            # to Analysis and get three tokens a second with nothing said.
            "slow_here": _runs_slowly(e.size_gb, gpu_gb),
            "is_bundled": manifest.is_bundled(e.id),
            "not_in_use": not_in_use,
            # computed here, not in the UI: it depends on every other entry,
            # and duplicating that rule in javascript would let the two drift.
            "removal_warning": removal_warning(e, registry),
        })

    discovered = _discovered_not_yet_configured(registry)

    return {
        "models": models,
        "routing": routing,
        "tasks": list(KNOWN_TASKS),
        "budget_gb": round(budget, 1),
        # Models already on this machine that are not configured yet.
        "discovered": discovered,
        # The one recommended download, in the same payload.
        "upgrade": _upgrade_offer(registry, budget, cap.tier if cap else "", plan_for_size, gpu_gb),
        # The whole catalog, even when `upgrade` is None: "not recommended"
        # and "not allowed" are different statements.
        "catalog": _catalog_for(registry, budget, cap.tier if cap else "", plan_for_size, gpu_gb),
        "download": downloader.progress or {"status": "idle"},
    }


def _describe(resolution, registry: Registry) -> dict:
    """A display name and size for the router's pick: the user's label, then
    the catalog's name, then the filename."""
    if resolution.ollama_tag:
        return {"label": f"{resolution.ollama_tag} (via Ollama)", "size_gb": 0.0}
    if not resolution.path:
        return {"label": "", "size_gb": 0.0}

    filename = Path(resolution.path).name
    if resolution.entry_id:
        entry = registry.get(resolution.entry_id)
        if entry is not None:
            return {"label": entry.label or filename, "size_gb": entry.size_gb}
    for e in registry.models:
        if e.path and Path(e.path).name == filename:
            return {"label": e.label or filename, "size_gb": e.size_gb}

    from domain.model_manager.catalog import by_name
    spec = by_name(filename)
    if spec is not None:
        return {"label": spec.label, "size_gb": spec.size_gb}

    try:
        size = Path(resolution.path).stat().st_size / (1024 ** 3)
    except OSError:
        size = 0.0
    return {"label": Path(filename).stem, "size_gb": round(size, 2)}


def _catalog_for(registry: Registry, budget_gb: float, tier: str,
                 plan_for_size=None, gpu_gb: float = 0.0) -> list[dict]:
    """Every catalog model, judged against this machine. Nothing is hidden;
    `fits` and `recommended_here` let the UI warn without refusing."""
    try:
        from domain.model_manager import catalog
        from domain.model_manager.discovery import discover_all, installed_names

        found = discover_all(settings.models_dir, settings.ollama_base_url)
        installed = installed_names(found)
        installed.update(e.id for e in registry.models)
        installed.update(Path(e.path).name for e in registry.models if e.path)

        out = []
        for s in catalog.optional_models():
            already = (
                s.name in installed
                or catalog._installed_key_match(s, installed)
            )
            out.append({
                "name": s.name,
                "label": s.label,
                # What the user GETS, first. The model's name answers "which
                # weights"; a researcher's question is "why would I want it".
                "outcome": s.outcome or s.label,
                "speed": s.speed_words(gpu_gb),
                "size_gb": s.size_gb,
                "description": s.description,
                "tasks": list(s.tasks),
                "installed": already,
                # Asked of capability, not the budget number: that floors at 0 on a
                # constrained machine, and 0 means "unmeasured, no limit" elsewhere,
                # so the weakest machine would be told it can run everything.
                "fits": (
                    bool(getattr(plan_for_size(s.size_gb), "fits", True))
                    if plan_for_size is not None
                    else (budget_gb <= 0 or s.min_ram_gb <= budget_gb)
                ),
                "min_ram_gb": s.min_ram_gb,
                # fits = the weights will load. slow_here = they will load and
                # then disappoint. Shown, not hidden: a user with a reason to
                # want a big model may still take it.
                "slow_here": not s.runs_well_on(gpu_gb),
                "recommended_here": (
                    bool(s.tasks) and (not tier or s.runs_on_tier(tier))
                    and s.runs_well_on(gpu_gb)
                ),
            })
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("could not build the catalog view: %s", e)
        return []


def _upgrade_offer(registry: Registry, budget_gb: float, tier: str = "",
                   plan_for_size=None, gpu_gb: float = 0.0) -> dict | None:
    """The best catalog model worth downloading, or None.

    "Already have it" comes from discovery (which knows an Ollama model under
    another name is the same weights) plus the registry (imports count too).
    """
    try:
        from domain.model_manager import catalog
        from domain.model_manager.discovery import discover_all, installed_names

        found = discover_all(settings.models_dir, settings.ollama_base_url)
        installed = installed_names(found)
        installed.update(e.id for e in registry.models)
        installed.update(Path(e.path).name for e in registry.models if e.path)

        spec = catalog.suggested_upgrade(budget_gb, installed, tier, gpu_gb)
        if spec is None:
            return None
        # Never offer what will not load. suggested_upgrade filters on
        # min_ram_gb against a budget that can be a floored zero; this is
        # the authoritative second look.
        if plan_for_size is not None and not getattr(plan_for_size(spec.size_gb), "fits", True):
            return None
        return {
            "name": spec.name,
            "label": spec.label,
            "size_gb": spec.size_gb,
            "description": spec.description,
            "tasks": list(spec.tasks),
        }
    except Exception as e:  # noqa: BLE001 - an offer is a bonus, never a failure
        logger.warning("could not work out an upgrade offer: %s", e)
        return None


def _discovered_not_yet_configured(registry: Registry) -> list[dict]:
    """Models found on this machine but not in the registry yet.

    Only real files are `assignable`. Ollama keeps weights as blobs llama.cpp
    cannot open, so Ollama models are listed for information only.
    """
    try:
        from domain.model_manager.discovery import discover_all

        known_paths = {
            str(Path(e.path).expanduser().resolve())
            for e in registry.models if e.path
        }
        out: list[dict] = []
        seen: set[str] = set()
        for m in discover_all(settings.models_dir, settings.ollama_base_url):
            assignable = m.usable_directly and bool(m.path)
            key = ""
            if assignable:
                try:
                    key = str(Path(m.path).expanduser().resolve())
                except (OSError, ValueError):
                    continue
                if key in known_paths or key in seen:
                    continue
                seen.add(key)
            elif m.name in seen:
                continue
            else:
                seen.add(m.name)

            out.append({
                "name": m.name,
                "label": Path(m.name).stem if assignable else m.name,
                "source": m.source,
                "path": m.path,
                "size_gb": m.size_gb,
                "assignable": assignable,
            })
        return out
    except Exception as e:  # noqa: BLE001 - a bonus list must never fail the page
        logger.warning("could not list discovered models: %s", e)
        return []


@router.get("/registry")
async def get_registry():
    """every model this install knows about, and what each task resolves to."""
    return _snapshot()


@router.post("/registry/import")
async def import_model(request: ImportRequest):
    """Register a GGUF the user has on disk. Referenced, never copied, and
    `managed` is false, so ThinkStack never deletes it."""
    registry = Registry.load(settings.models_dir)

    try:
        entry = entry_from_import(request.path, request.tasks, request.label)
    except ModelImportError as e:
        # user-facing text by construction; see validate_gguf
        raise HTTPException(status_code=400, detail=str(e)) from e

    existing = registry.by_path(entry.path)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail=f"That model is already added as \"{existing.label}\".",
        )

    registry.upsert(entry)
    if not registry.save(settings.models_dir):
        raise HTTPException(status_code=500, detail="Could not save the model list.")

    logger.info("imported model %s (%.2f gb) for %s",
                entry.id, entry.size_gb, ", ".join(entry.tasks) or "no tasks")
    return {"model": entry.as_dict(), "snapshot": _snapshot()}


@router.patch("/registry/{model_id}")
async def update_model(model_id: str, request: AssignRequest):
    """change which jobs a model does, or what it is called."""
    registry = Registry.load(settings.models_dir)
    if registry.get(model_id) is None:
        raise HTTPException(status_code=404, detail="No such model.")

    if request.tasks is not None:
        unknown = [t for t in request.tasks if t not in KNOWN_TASKS]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Not something ThinkStack does: {', '.join(unknown)}",
            )
        registry.assign(model_id, request.tasks, by_user=True)

    if request.label is not None:
        from dataclasses import replace as _replace
        entry = registry.get(model_id)
        registry.upsert(_replace(entry, label=request.label.strip() or entry.label))

    if not registry.save(settings.models_dir):
        raise HTTPException(status_code=500, detail="Could not save the model list.")
    return {"model": registry.get(model_id).as_dict(), "snapshot": _snapshot()}


@router.delete("/registry/{model_id}")
async def remove_model(model_id: str, delete_file: bool = False):
    """Remove a model, and optionally delete its file.

        delete_file=False  forget the model; the .gguf stays (the default,
                           because the wrong guess should be the harmless one)
        delete_file=True   forget it AND delete the file; refused for any
                           file ThinkStack did not create (`managed` false)

    Removal is never blocked, but what stops working is reported.
    """
    registry = Registry.load(settings.models_dir)
    entry = registry.get(model_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="No such model.")

    manifest = BundledManifest.load(settings.bundled_models_dir)
    warning = removal_warning(entry, registry)
    deleted_file = False

    if delete_file and not entry.managed:
        raise HTTPException(
            status_code=400,
            detail="That file is not ThinkStack's to delete. It was added from "
                   "your own disk, so remove it there if you want it gone.",
        )

    if delete_file and entry.managed:
        try:
            p = Path(entry.path)
            if p.is_file():
                p.unlink()
                deleted_file = True
        except OSError as e:
            logger.warning("could not delete %s: %s", entry.path, e)
            raise HTTPException(
                status_code=500,
                detail=f"The model was removed from ThinkStack, but its file "
                       f"could not be deleted: {e}",
            ) from e

    registry.remove(model_id)

    # Remember a deliberate removal of a BUNDLED model, so the next update
    # offers it rather than silently copying it back onto their disk. Only when
    # the file is gone: forgetting a bundled model whose weights are still
    # there is a routing change, not a decision to stop shipping it.
    if manifest.is_bundled(model_id) and deleted_file:
        registry.opt_out(model_id)

    if not registry.save(settings.models_dir):
        raise HTTPException(status_code=500, detail="Could not save the model list.")

    logger.info("removed model %s (file deleted: %s)", model_id, deleted_file)
    return {
        "removed": model_id,
        "file_deleted": deleted_file,
        "warning": warning,
        "snapshot": _snapshot(),
    }
