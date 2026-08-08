"""bring the registry in line with what this build ships.

Runs once on startup. It answers a question that only arises across an UPDATE:
the installed app has a registry describing the models the *previous* version
bundled, and this build ships a possibly different set. Something has to decide
what to install, what to retire, and what to leave strictly alone.

Three rules do the deciding, in this order:

  1. **The user's disk is the user's.** ``managed`` is false for anything the
     user imported, and nothing here ever touches those files. Not to relocate
     them, not to tidy them up. We delete only weights we ourselves wrote.

  2. **The user's intent outranks the release.** ``user_assigned`` marks task
     assignments a human made in Bench. A manifest may overwrite assignments a
     previous manifest made; it may never overwrite one of those.

  3. **An opt-out is remembered.** Removing the bundled model is a deliberate
     act, usually because the user runs something better. Re-copying 700 MB
     back onto their disk at every update would make that choice meaningless,
     so an opted-out model is offered in Bench rather than installed.

Everything here is best-effort. A failure to copy or delete one model is logged
and skipped -- reconciliation runs during startup, and taking the app down
because a file was locked would be a far worse outcome than a stale entry.
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from domain.model_manager.manifest import BundledManifest, BundledModel
from domain.model_manager.registry import ModelEntry, Registry

logger = logging.getLogger(__name__)


@dataclass
class ReconcileReport:
    """what reconciliation actually did, for logging and for Bench.

    Bench shows this after an update ("Replaced Qwen2.5 0.5B with ThinkStack
    SLM 1B, reclaimed 0.47 GB"), which is the whole reason retirement can be
    automatic: the user is told, they just are not asked.
    """

    installed: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    reclaimed_gb: float = 0.0
    skipped_optout: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.installed or self.retired)

    def as_dict(self) -> dict:
        return {
            "installed": self.installed,
            "retired": self.retired,
            "reclaimed_gb": round(self.reclaimed_gb, 2),
            "skipped_optout": self.skipped_optout,
            "errors": self.errors,
            "changed": self.changed,
        }

    def summary(self) -> str:
        """one sentence for the Bench card, or empty when nothing happened."""
        if not self.changed:
            return ""
        bits = []
        if self.installed:
            bits.append(f"added {', '.join(self.installed)}")
        if self.retired:
            reclaimed = f" (reclaimed {self.reclaimed_gb:.2f} GB)" if self.reclaimed_gb else ""
            bits.append(f"replaced {', '.join(self.retired)}{reclaimed}")
        return "This update " + " and ".join(bits) + "."


def _install(
    model: BundledModel, bundled_dir: Path, models_dir: Path
) -> tuple[Path | None, str]:
    """put ``model``'s weights in the writable models dir.

    A source checkout has ``bundled_dir == models_dir``, so the file is already
    where it needs to be and copying it onto itself would truncate it. Returns
    the destination path, or None with a reason.
    """
    dest = Path(models_dir) / model.file
    if dest.is_file():
        return dest, "already present"

    src = Path(bundled_dir) / model.file
    try:
        if not src.is_file():
            # Declared by the manifest but absent from the payload. Real cause:
            # a release.config.json entry whose download failed at build time.
            return None, f"{model.file} is declared in the manifest but was not shipped"
        if src.resolve() == dest.resolve():
            return dest, "already present"
        Path(models_dir).mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        return dest, "installed"
    except OSError as e:
        return None, f"could not install {model.file}: {e}"


def _retire(entry: ModelEntry, registry: Registry) -> tuple[bool, float, str]:
    """delete a superseded bundled model's weights and drop its entry.

    Guarded on ``managed``. An entry can only get here by being named in a
    manifest's ``replaces``, but the guard stays because a hand-edited registry
    could set ``origin: bundled`` on a path we never wrote -- and the cost of
    being wrong is deleting a file that is not ours.
    """
    freed = 0.0
    if not entry.managed:
        registry.remove(entry.id)
        return True, 0.0, "unregistered (file left in place; not ours to delete)"

    p = Path(entry.path)
    try:
        if p.is_file():
            freed = p.stat().st_size / (1024 ** 3)
            p.unlink()
    except OSError as e:
        # The entry still goes: it names a model this build has superseded, so
        # leaving it registered would route work to obsolete weights.
        registry.remove(entry.id)
        return False, 0.0, f"could not delete {p.name}: {e}"

    registry.remove(entry.id)
    return True, freed, "retired"


def _inherit_tasks(
    retired: ModelEntry, successor_id: str, registry: Registry
) -> list[str]:
    """hand over any task the retired model was the ONLY provider of.

    Without this, replacing the bundled analysis model would leave `analysis`
    with nothing assigned and quietly downgrade every summary. Tasks another
    model still covers are left alone -- inheriting those would override a
    choice the user may have made deliberately.
    """
    successor = registry.get(successor_id)
    if successor is None:
        return []

    orphaned = [
        t for t in retired.tasks
        if not [m for m in registry.for_task(t) if m.id != retired.id]
    ]
    if not orphaned:
        return []

    merged = tuple(dict.fromkeys((*successor.tasks, *orphaned)))
    # by_user=False: this is a release decision, not a human one, so it must
    # not masquerade as user intent and become un-overwritable later.
    registry.assign(successor_id, list(merged), by_user=False)
    return orphaned


def reconcile_bundled(
    registry: Registry,
    manifest: BundledManifest,
    *,
    bundled_dir: Path,
    models_dir: Path,
) -> ReconcileReport:
    """install what this build ships, retire what it supersedes.

    Mutates ``registry`` in place and returns what changed. Does NOT save --
    the caller decides when to persist, so a partial reconciliation cannot be
    written and then interrupted halfway.
    """
    report = ReconcileReport()

    for model in manifest.models:
        if model.id in registry.bundled_optout:
            report.skipped_optout.append(model.id)
            logger.info("%s was removed by the user; offering it rather than installing", model.id)
            continue

        dest, why = _install(model, bundled_dir, models_dir)
        if dest is None:
            report.errors.append(why)
            logger.warning("%s", why)
            continue

        existing = registry.get(model.id)
        if existing is None:
            registry.upsert(ModelEntry(
                id=model.id,
                path=str(dest),
                label=model.label or model.file,
                size_gb=model.size_gb,
                origin="bundled",
                managed=True,
                tasks=model.tasks,
                user_assigned=False,
            ))
            if why == "installed":
                report.installed.append(model.label or model.file)
        else:
            # Already known. Refresh the facts that can drift (the path changes
            # when STATE_DIR moves), but never the task assignment if a human
            # set it -- rule 2.
            registry.upsert(ModelEntry(
                id=existing.id,
                path=str(dest),
                label=model.label or existing.label,
                size_gb=model.size_gb or existing.size_gb,
                origin="bundled",
                managed=True,
                tasks=existing.tasks if existing.user_assigned else model.tasks,
                user_assigned=existing.user_assigned,
                last_error=existing.last_error,
            ))

    # -- retire what this build supersedes --
    for model in manifest.models:
        for old_id in model.replaces:
            old = registry.get(old_id)
            if old is None or old.id == model.id:
                continue
            inherited = _inherit_tasks(old, model.id, registry)
            ok, freed, why = _retire(old, registry)
            report.reclaimed_gb += freed
            report.retired.append(old.label or old.id)
            if not ok:
                report.errors.append(why)
            logger.info(
                "retired %s in favour of %s: %s%s",
                old_id, model.id, why,
                f"; {model.id} inherited {', '.join(inherited)}" if inherited else "",
            )

    return report


def reconcile_and_save(
    models_dir: Path, bundled_dir: Path, manifest: BundledManifest | None = None
) -> ReconcileReport:
    """load, reconcile, persist. the startup entry point.

    Never raises. Reconciliation runs during app startup, and a failure here
    must degrade to "the registry is what it was" rather than preventing the
    app from opening.
    """
    try:
        registry = Registry.load(models_dir)
        mf = manifest if manifest is not None else BundledManifest.load(bundled_dir)
        report = reconcile_bundled(
            registry, mf, bundled_dir=bundled_dir, models_dir=models_dir
        )
        if report.changed or not Registry.path_for(models_dir).exists():
            registry.save(models_dir)
        if report.changed:
            logger.info("model reconciliation: %s", report.summary())
        return report
    except Exception as e:  # noqa: BLE001 - startup must not die here
        logger.error("model reconciliation failed: %s", e, exc_info=True)
        return ReconcileReport(errors=[str(e)])
