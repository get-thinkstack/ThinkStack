"""the user's model choices, persisted.

`catalog.py` says what ThinkStack knows about; `discovery.py` says what happens
to be on the machine. Neither is writable, so before this module a model the
user supplied had nowhere to be recorded and no way to be selected for a task.

This is that missing piece: a small JSON file listing every model available to
this install, where its weights are, and which jobs it is allowed to do.

Two invariants carry most of the safety:

  * ``managed`` says whether ThinkStack created the file. We only ever delete
    weights we put there ourselves. An imported model is REFERENCED in place --
    a 7 GB import must not cost 14 GB of disk on a machine we already know is
    constrained -- so its file belongs to the user and is never touched.

  * ``user_assigned`` says whether a human chose ``tasks``. A release manifest
    may overwrite assignments a previous manifest made; it may never overwrite
    a choice the user made. Without this, upgrading would silently undo the
    routing someone deliberately set up.

Status is deliberately NOT stored. Whether a model is missing or too large is a
fact about right now -- a model that did not fit yesterday fits today if the
user closed a browser -- and persisting it would only let the UI go stale.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

from infrastructure.atomic_io import atomic_write_json

logger = logging.getLogger(__name__)

# Bumped only for a change old code could not read. Readers treat a HIGHER
# version as "written by a newer ThinkStack" and decline to touch it, rather
# than parsing it wrongly and writing the damage back.
SCHEMA_VERSION = 1

REGISTRY_FILENAME = "registry.json"

# Every task the router can be asked about.
#
# EXACTLY the task_type values something actually generates with -- grep for
# `task_type=` and this is the list. It deliberately does NOT include "chat" or
# "search", which appear in catalog.py as descriptive metadata about what a
# model is good at: nothing routes on them, so offering them in the UI would let
# a user assign a model to a job that is never dispatched, and then reasonably
# conclude the app was ignoring their choice.
#
# Kept here rather than imported from ollama_client so the domain layer does not
# depend on the runtime. tests/test_model_registry.py asserts the two agree.
KNOWN_TASKS: tuple[str, ...] = (
    "general",
    "analysis",
    "gap_analysis",
    "latex_writer",
)

# Where a model's weights came from.
#   bundled    shipped inside this build, copied out on first run  (managed)
#   downloaded fetched by us, on the user's instruction            (managed)
#   imported   the user pointed at a file they already had         (NOT managed)
#   external   found via Ollama / LM Studio, loaded where it lies  (NOT managed)
ORIGINS: tuple[str, ...] = ("bundled", "downloaded", "imported", "external")

# The first four bytes of every GGUF file. Checked on import so a mistyped path
# or a .safetensors file fails immediately with a clear message, instead of
# succeeding here and exploding inside llama.cpp during someone's first summary.
GGUF_MAGIC = b"GGUF"

_ID_STRIP = re.compile(r"[^a-z0-9]+")


def pretty_name(filename: str) -> str:
    """a readable name for a gguf, when nothing better is available.

    "Qwen2.5-1.5B-Instruct-Q4_K_M.gguf" -> "Qwen2.5 1.5B Instruct Q4_K_M"

    A gguf filename is a build artefact -- lowercase, hyphenated, with the
    quantisation welded on. Showing it raw in a sentence makes the UI read like
    a log file. The catalog label is preferred wherever we recognise the model;
    this is the fallback for one we have never seen.
    """
    stem = filename[:-5] if filename.lower().endswith(".gguf") else filename
    words = []
    for w in re.split(r"[-\s]+", stem):
        if not w:
            continue
        # keep tokens that already carry meaningful case or digits
        # A token carrying digits or existing capitals is already meaningful
        # as written ("1.5b", "Q4_K_M", "3B") -- capitalising it would produce
        # "Q4_k_m". Only plain words get title case.
        words.append(w if (any(c.isdigit() for c in w) or any(c.isupper() for c in w))
                     else w.capitalize())
    return " ".join(words) or stem


def make_id(name: str) -> str:
    """a stable, filesystem-safe id derived from a model name or filename.

    Ids are compared, logged, and used as dict keys, so they must not vary with
    punctuation: ``Qwen2.5-1.5B-Instruct-Q4_K_M.gguf`` and
    ``qwen2.5_1.5b_instruct_q4_k_m`` describe the same weights and must produce
    the same id.

    This is intentionally NOT ``discovery.model_key``. That function answers "are
    these the same weights?" and deliberately discards the quantisation, because
    re-downloading a q4 when you have a q8 is waste. Here the quantisation must
    be KEPT: a user may register both quants and assign them to different tasks,
    and collapsing them would make one silently overwrite the other.
    """
    s = name.strip().lower()
    if s.endswith(".gguf"):
        s = s[: -len(".gguf")]
    return _ID_STRIP.sub("-", s).strip("-")


@dataclass(frozen=True)
class ModelEntry:
    """one model this install may use."""

    id: str
    path: str
    label: str
    size_gb: float = 0.0
    origin: str = "imported"
    # may ThinkStack delete this file? true only for weights we created.
    managed: bool = False
    tasks: tuple[str, ...] = ()
    # did a human choose `tasks`, or did a release manifest?
    user_assigned: bool = False
    # relative capability, copied from the catalog when we recognise the model.
    # Without it, two models claiming `analysis` were ordered by LABEL, so
    # "Llama 3.2 3B" beat "Qwen3 4B" on the alphabet -- a coin toss deciding
    # which model does the work.
    quality: int = 0
    # why this model last failed to load, kept so the Bench card can explain
    # itself after a restart. cleared on a successful load.
    last_error: str | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "path": self.path,
            "label": self.label,
            "size_gb": self.size_gb,
            "origin": self.origin,
            "managed": self.managed,
            "tasks": list(self.tasks),
            "user_assigned": self.user_assigned,
            "quality": self.quality,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ModelEntry":
        """rebuild an entry from json, tolerating anything unexpected.

        A registry written by a future version, hand-edited, or truncated must
        degrade to a usable entry rather than raising -- this file sits between
        the user and every AI feature in the app, so a parse error here would
        take down more than it fixes. Unknown keys are ignored; missing ones
        take their default.
        """
        tasks = d.get("tasks") or []
        if not isinstance(tasks, list):
            tasks = []
        origin = str(d.get("origin") or "imported")
        return cls(
            id=str(d.get("id") or make_id(str(d.get("path", "")))),
            path=str(d.get("path") or ""),
            label=str(d.get("label") or ""),
            size_gb=float(d.get("size_gb") or 0.0),
            origin=origin if origin in ORIGINS else "imported",
            managed=bool(d.get("managed", False)),
            tasks=tuple(str(t) for t in tasks if t in KNOWN_TASKS),
            user_assigned=bool(d.get("user_assigned", False)),
            quality=int(d.get("quality") or 0),
            last_error=d.get("last_error") or None,
        )

    def exists(self) -> bool:
        try:
            return bool(self.path) and Path(self.path).is_file()
        except OSError:
            return False

    def status(self, budget_gb: float = 0.0) -> str:
        """what is true about this entry RIGHT NOW.

        ``missing`` outranks everything: a file that is not there cannot be too
        big, and telling the user to free memory when the real problem is a
        deleted file would send them after the wrong fix.

        A budget of 0 means "unknown", which is treated as no constraint --
        better to attempt a load and let the loader's own fallback handle it
        than to refuse a model that would have worked.
        """
        if not self.exists():
            return "missing"
        if budget_gb > 0 and self.size_gb > budget_gb:
            return "too_big"
        if self.last_error:
            return "failed"
        return "present"


@dataclass
class Registry:
    """every model available to this install, and what each may be used for.

    Load with :meth:`load`, mutate through the methods, persist with
    :meth:`save`. Mutations do not write to disk on their own: reconciliation
    makes several changes in a row, and writing after each would leave the file
    briefly describing a state that never really existed.
    """

    models: list[ModelEntry] = field(default_factory=list)
    # ids of bundled models the user deliberately removed. an update must not
    # silently re-copy weights onto a disk somebody cleared on purpose.
    bundled_optout: list[str] = field(default_factory=list)
    # set when the file on disk was written by a newer ThinkStack. we then read
    # what we can but refuse to save, so a downgrade cannot destroy newer data.
    read_only: bool = False

    # ── persistence ────────────────────────────────────────────────────

    @staticmethod
    def path_for(models_dir: Path) -> Path:
        return Path(models_dir) / REGISTRY_FILENAME

    @classmethod
    def load(cls, models_dir: Path) -> "Registry":
        """read the registry, degrading to empty on any problem.

        A missing file is the normal first-run case. A corrupt one is not, but
        the response is the same: start empty and log it. Refusing to start
        because a JSON file is damaged would take every AI feature down over
        something the user can fix by re-importing a model.
        """
        p = cls.path_for(models_dir)
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return cls()
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("model registry at %s is unreadable (%s); starting empty", p, e)
            return cls()

        if not isinstance(raw, dict):
            logger.warning("model registry at %s is not an object; starting empty", p)
            return cls()

        version = raw.get("version", SCHEMA_VERSION)
        read_only = False
        if isinstance(version, int) and version > SCHEMA_VERSION:
            # Written by a newer version. Read what we understand so the app
            # still works, but never write back -- that would silently delete
            # fields this build does not know about.
            logger.warning(
                "model registry is schema v%s, this build understands v%s; "
                "using it read-only", version, SCHEMA_VERSION,
            )
            read_only = True

        entries: list[ModelEntry] = []
        for item in raw.get("models") or []:
            if isinstance(item, dict):
                try:
                    entries.append(ModelEntry.from_dict(item))
                except (TypeError, ValueError) as e:
                    logger.warning("skipping unreadable registry entry %r: %s", item, e)

        optout = [str(x) for x in (raw.get("bundled_optout") or []) if x]
        return cls(models=entries, bundled_optout=optout, read_only=read_only)

    def save(self, models_dir: Path) -> bool:
        """persist atomically. returns whether anything was written."""
        if self.read_only:
            logger.warning("refusing to overwrite a newer-schema model registry")
            return False
        payload = {
            "version": SCHEMA_VERSION,
            "bundled_optout": sorted(set(self.bundled_optout)),
            "models": [m.as_dict() for m in self.models],
        }
        try:
            atomic_write_json(self.path_for(models_dir), payload)
            return True
        except (OSError, TypeError, ValueError) as e:
            logger.error("could not save model registry: %s", e, exc_info=True)
            return False

    # ── lookup ─────────────────────────────────────────────────────────

    def get(self, model_id: str) -> ModelEntry | None:
        for m in self.models:
            if m.id == model_id:
                return m
        return None

    def by_path(self, path: str | Path) -> ModelEntry | None:
        """find an entry by filesystem path, however it was spelled.

        Resolved before comparing so ``~/models/x.gguf``, ``./models/x.gguf``
        and an absolute path all match the same entry -- otherwise importing a
        model twice by different routes would create two entries fighting over
        the same file.
        """
        # ValueError, not just OSError: a path containing a NUL byte raises
        # ValueError from os.path.realpath before the filesystem is ever
        # touched. A lookup is a question, not an action -- it answers "no"
        # for anything unaskable rather than propagating.
        try:
            target = Path(path).expanduser().resolve()
        except (OSError, RuntimeError, ValueError):
            return None
        for m in self.models:
            try:
                if Path(m.path).expanduser().resolve() == target:
                    return m
            except (OSError, RuntimeError, ValueError):
                continue
        return None

    def for_task(self, task: str) -> list[ModelEntry]:
        """entries assigned to ``task``, strongest claim first.

        A model the user explicitly assigned outranks one a release manifest
        assigned. That ordering is the whole reason ``user_assigned`` exists:
        upgrading must never quietly re-route work away from the model somebody
        chose on purpose.
        """
        matching = [m for m in self.models if task in m.tasks]
        # user intent first, then the MORE CAPABLE model. Label is only the
        # final tiebreak, so the ordering is stable but never decided by it.
        return sorted(
            matching,
            key=lambda m: (not m.user_assigned, -m.quality, m.label.lower()),
        )

    # ── mutation ───────────────────────────────────────────────────────

    def upsert(self, entry: ModelEntry) -> ModelEntry:
        """add ``entry``, or replace the existing one with the same id."""
        for i, m in enumerate(self.models):
            if m.id == entry.id:
                self.models[i] = entry
                return entry
        self.models.append(entry)
        return entry

    def remove(self, model_id: str) -> ModelEntry | None:
        """drop an entry. does NOT delete the file -- see `managed`."""
        for i, m in enumerate(self.models):
            if m.id == model_id:
                return self.models.pop(i)
        return None

    def assign(self, model_id: str, tasks: list[str], *, by_user: bool = True) -> ModelEntry | None:
        """set which jobs a model may do.

        Unknown task names are dropped rather than rejected: the caller is a
        JSON request body, and one bad name in a list of five should not lose
        the other four.
        """
        entry = self.get(model_id)
        if entry is None:
            return None
        clean = tuple(t for t in tasks if t in KNOWN_TASKS)
        updated = replace(entry, tasks=clean, user_assigned=by_user or entry.user_assigned)
        self.upsert(updated)
        return updated

    def record_error(self, model_id: str, error: str | None) -> ModelEntry | None:
        """remember (or clear) why a model last failed to load."""
        entry = self.get(model_id)
        if entry is None:
            return None
        updated = replace(entry, last_error=error or None)
        self.upsert(updated)
        return updated

    def opt_out(self, model_id: str) -> None:
        if model_id not in self.bundled_optout:
            self.bundled_optout.append(model_id)

    def opt_in(self, model_id: str) -> None:
        self.bundled_optout = [x for x in self.bundled_optout if x != model_id]


# ── removal safety ─────────────────────────────────────────────────────


def removal_warning(entry: ModelEntry, registry: Registry) -> str | None:
    """what the user should understand before removing ``entry``, or None.

    Deliberately a WARNING and never a veto. The user knows their machine and
    their disk better than a heuristic does, and blocking a removal because our
    budget estimate disagrees would be paternalistic about a decision that is
    genuinely theirs.

    What it does do is name the consequence in terms of the app's behaviour,
    because that is the part they cannot see: "you will lose X" is actionable,
    "are you sure?" is not.
    """
    orphaned = [
        task for task in entry.tasks
        if not [m for m in registry.for_task(task) if m.id != entry.id and m.exists()]
    ]

    if not orphaned:
        return None

    pretty = ", ".join(t.replace("_", " ") for t in sorted(orphaned))

    # Losing the last model for a job is different from losing the last model
    # entirely, and the user needs to be able to tell those apart.
    others_left = [m for m in registry.models if m.id != entry.id and m.exists()]
    if not others_left:
        return (
            "This is the only model on this machine. Removing it stops "
            "ThinkStack answering anything until you add another one "
            "(you can import one you already have, or download one)."
        )

    return (
        f"Nothing else is set up for {pretty}. Those will fall back to the "
        f"bundled model, which is faster but less reliable on structured work."
    )


# ── import validation ──────────────────────────────────────────────────


class ModelImportError(ValueError):
    """an imported path cannot be used as a model. message is user-facing."""


def validate_gguf(path: str | Path) -> Path:
    """check ``path`` is a real, readable GGUF file and return it resolved.

    Every failure here is one the user can act on, so each raises with its own
    message rather than a single "invalid file". Checking the magic bytes costs
    one 4-byte read and converts a crash deep inside llama.cpp -- during a
    summary, minutes later -- into an error at the moment of import, next to the
    file picker that caused it.
    """
    # ValueError catches a NUL byte in the path, which raises out of
    # os.path.realpath rather than as an OSError.
    try:
        p = Path(path).expanduser()
        exists, is_dir = p.exists(), p.is_dir()
    except (OSError, RuntimeError, ValueError) as e:
        raise ModelImportError(f"That path could not be read: {e}") from e

    if not exists:
        raise ModelImportError("There is no file at that path.")
    if is_dir:
        raise ModelImportError("That is a folder. Pick the .gguf file inside it.")

    try:
        p = p.resolve()
        with open(p, "rb") as f:
            magic = f.read(4)
    except PermissionError as e:
        raise ModelImportError("ThinkStack is not allowed to read that file.") from e
    except OSError as e:
        raise ModelImportError(f"That file could not be read: {e}") from e

    if magic != GGUF_MAGIC:
        raise ModelImportError(
            "That is not a GGUF model file. ThinkStack loads .gguf weights -- "
            "the format LM Studio and llama.cpp use."
        )
    return p


def entry_from_import(
    path: str | Path,
    tasks: list[str],
    label: str = "",
    *,
    origin: str = "imported",
    managed: bool = False,
) -> ModelEntry:
    """build a registry entry for a file the user pointed at.

    Validates first, so a caller cannot register a path that will not load.
    """
    p = validate_gguf(path)
    try:
        size_gb = round(p.stat().st_size / (1024 ** 3), 2)
    except OSError:
        size_gb = 0.0
    return ModelEntry(
        id=make_id(p.name),
        path=str(p),
        label=label.strip() or _catalog_label(p.name) or pretty_name(p.name),
        size_gb=size_gb,
        origin=origin if origin in ORIGINS else "imported",
        managed=managed,
        tasks=tuple(t for t in tasks if t in KNOWN_TASKS),
        user_assigned=True,
        quality=_catalog_quality(p.name),
    )


def _catalog_label(filename: str) -> str:
    """the published name for these weights, if we ship or offer them.

    Preferred over ``pretty_name`` so a model the user imports by hand shows the
    same name as the same model downloaded through the app -- otherwise Bench
    lists "Qwen2.5 1.5B" and "Qwen2.5 1.5b Instruct q4_k_m" as if they were
    different things.
    """
    try:
        from domain.model_manager.catalog import by_name
        spec = by_name(filename)
        return spec.label if spec else ""
    except Exception:  # noqa: BLE001
        return ""


def _catalog_quality(filename: str) -> int:
    """the catalog's capability rank for these weights, or 0 if unknown.

    A model the user supplied themselves is usually not in the catalog, and 0
    is the honest answer there: we have no basis for ranking it. It still wins
    any task the user assigns it, because user intent sorts ahead of capability.
    """
    try:
        from domain.model_manager.catalog import by_name
        spec = by_name(filename)
        return spec.quality if spec else 0
    except Exception:  # noqa: BLE001
        return 0
