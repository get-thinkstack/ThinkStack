"""what THIS build ships, declared as data rather than code.

Changing which model ThinkStack bundles used to mean editing four places --
``release.config.json``, ``catalog.BASE_MODEL``, ``settings.llm_analysis_model``
and ``ollama_client.TASK_MODEL_MAP``. Miss one and routing points at a file that
is not there. That friction is exactly what would make shipping our own
fine-tuned SLM painful, so the build now writes a manifest beside the weights
and everything reads that instead:

    data/models/bundled.json

Swapping the bundled model becomes one edit to ``release.config.json``. No
Python changes.

The ``replaces`` field is what makes an UPDATE work rather than just an install.
Without it, first run after an upgrade would have to infer "is this old bundled
model obsolete, or did the user want it?" from its absence from the new
manifest -- and inferring intent from absence is how you strand people. The
release states the answer instead.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

MANIFEST_FILENAME = "bundled.json"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class BundledModel:
    """one model shipped inside this build."""

    id: str
    file: str                      # filename inside the bundled models dir
    label: str = ""
    size_gb: float = 0.0
    tasks: tuple[str, ...] = ()
    # ids of previously-bundled models this one supersedes. their weights are
    # deleted on first run after the update -- safe because we shipped them.
    replaces: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, d: dict) -> "BundledModel | None":
        """parse one entry, or None when it is unusable.

        A manifest entry with no ``file`` cannot be copied or loaded, so it is
        dropped rather than half-registered -- a registry entry pointing at
        nothing would fail later, further from the cause.
        """
        file = str(d.get("file") or "").strip()
        if not file:
            return None
        from domain.model_manager.registry import make_id

        return cls(
            id=str(d.get("id") or make_id(file)),
            file=file,
            label=str(d.get("label") or Path(file).stem),
            size_gb=float(d.get("size_gb") or 0.0),
            tasks=tuple(str(t) for t in (d.get("tasks") or [])),
            replaces=tuple(str(r) for r in (d.get("replaces") or [])),
        )


@dataclass(frozen=True)
class BundledManifest:
    """the set of models this build ships."""

    models: tuple[BundledModel, ...] = ()

    @classmethod
    def load(cls, bundled_dir: Path) -> "BundledManifest":
        """read ``bundled.json``, falling back to the catalog when absent.

        The fallback is not a nicety. Every build shipped before this feature
        has weights in ``data/models`` and no manifest, and a source checkout
        never had one. Returning an empty manifest for those would tell
        reconciliation that nothing is bundled, which would retire a model that
        is sitting right there and leave the install with none.
        """
        p = Path(bundled_dir) / MANIFEST_FILENAME
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except FileNotFoundError:
            logger.debug("no %s; deriving the bundled set from the catalog", p)
            return cls._from_catalog()
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("bundled manifest at %s is unreadable (%s); using the catalog", p, e)
            return cls._from_catalog()

        if not isinstance(raw, dict):
            logger.warning("bundled manifest at %s is not an object; using the catalog", p)
            return cls._from_catalog()

        version = raw.get("version", SCHEMA_VERSION)
        if isinstance(version, int) and version > SCHEMA_VERSION:
            # Unlike the registry we never write this file, so reading a newer
            # one is safe -- unknown fields are simply ignored.
            logger.info("bundled manifest is schema v%s; reading what we understand", version)

        out: list[BundledModel] = []
        for item in raw.get("models") or []:
            if not isinstance(item, dict):
                continue
            parsed = BundledModel.from_dict(item)
            if parsed is not None:
                out.append(parsed)
        return cls(models=tuple(out))

    @classmethod
    def _from_catalog(cls) -> "BundledManifest":
        """the bundled set implied by ``catalog.py``, for builds with no manifest."""
        try:
            from domain.model_manager.catalog import bundled_models
            from domain.model_manager.registry import make_id

            return cls(models=tuple(
                BundledModel(
                    id=make_id(s.name),
                    file=s.name,
                    label=s.label,
                    size_gb=s.size_gb,
                    tasks=tuple(s.tasks),
                )
                for s in bundled_models()
            ))
        except Exception as e:  # noqa: BLE001 - a fallback must never raise
            logger.warning("could not derive a bundled set from the catalog: %s", e)
            return cls()

    # ── lookup ─────────────────────────────────────────────────────────

    def get(self, model_id: str) -> BundledModel | None:
        for m in self.models:
            if m.id == model_id:
                return m
        return None

    def get_by_file(self, filename: str) -> BundledModel | None:
        """look up by gguf filename, which is what the router resolves against."""
        for m in self.models:
            if m.file == filename:
                return m
        return None

    def files_for(self, task: str) -> list[str]:
        """filenames this build bundles for ``task``, in manifest order."""
        return [m.file for m in self.models if task in m.tasks]

    def replaced_ids(self) -> set[str]:
        """every id this build's models supersede."""
        out: set[str] = set()
        for m in self.models:
            out.update(m.replaces)
        return out

    def is_bundled(self, model_id: str) -> bool:
        return self.get(model_id) is not None
