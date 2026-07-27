"""discover language models already present on this machine.

before offering to download a gigabyte of weights, look for models the user
already has. many researchers already run Ollama or LM Studio; re-downloading
the same weights would waste their bandwidth and disk for no benefit.

sources, in the order they are trusted:

  1. ThinkStack's own models dir  -- bundled baseline + anything downloaded before
  2. a running Ollama server      -- authoritative, reports what is actually loadable
  3. Ollama's on-disk blobs       -- catches Ollama installed but not running
  4. LM Studio's model dir        -- common alternative local runner

every probe is best-effort and individually guarded: a missing tool, a refused
connection, or an unreadable directory yields an empty list, never an error. a
failed probe must never block startup.
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ollama's http api. a short timeout on purpose: this runs during startup, and a
# hung probe would stall the setup screen.
_OLLAMA_TIMEOUT_S = 1.5


@dataclass(frozen=True)
class DiscoveredModel:
    """a model found somewhere on this machine."""

    name: str        # gguf filename, or the ollama tag
    source: str      # "thinkstack" | "ollama" | "ollama-disk" | "lmstudio"
    path: str = ""   # filesystem path, empty for models only ollama can load
    size_gb: float = 0.0

    @property
    def usable_directly(self) -> bool:
        """whether llama.cpp can load this file itself.

        ollama-managed models are stored as content-addressed blobs without a
        .gguf name, and ollama serves them over its own api, so they are used
        through the ollama provider rather than loaded from disk.
        """
        return self.source in ("thinkstack", "lmstudio") and bool(self.path)


def _size_gb(p: Path) -> float:
    try:
        return round(p.stat().st_size / (1024 ** 3), 2)
    except OSError:
        return 0.0


def find_thinkstack_models(models_dir: Path) -> list[DiscoveredModel]:
    """gguf files in ThinkStack's own models directory."""
    out: list[DiscoveredModel] = []
    try:
        if not models_dir.is_dir():
            return out
        for f in sorted(models_dir.glob("*.gguf")):
            out.append(DiscoveredModel(
                name=f.name, source="thinkstack", path=str(f), size_gb=_size_gb(f),
            ))
    except OSError as e:
        logger.warning("could not scan thinkstack models dir: %s", e)
    return out


def find_ollama_running(base_url: str) -> list[DiscoveredModel]:
    """models from a running Ollama server via /api/tags.

    returns an empty list when ollama is not installed or not running, which is
    the common case -- this is a bonus, not a requirement.
    """
    out: list[DiscoveredModel] = []
    try:
        import httpx

        resp = httpx.get(f"{base_url.rstrip('/')}/api/tags", timeout=_OLLAMA_TIMEOUT_S)
        resp.raise_for_status()
        for m in resp.json().get("models", []):
            name = m.get("name") or m.get("model") or ""
            if not name:
                continue
            out.append(DiscoveredModel(
                name=name,
                source="ollama",
                size_gb=round((m.get("size") or 0) / (1024 ** 3), 2),
            ))
    except Exception as e:  # noqa: BLE001 - any failure just means "no ollama"
        logger.debug("ollama not reachable at %s: %s", base_url, e)
    return out


def _ollama_root() -> Path:
    """where ollama keeps its models, honouring OLLAMA_MODELS."""
    env = os.environ.get("OLLAMA_MODELS")
    if env:
        return Path(env)
    return Path.home() / ".ollama" / "models"


def find_ollama_on_disk() -> list[DiscoveredModel]:
    """models ollama has pulled, read from its manifests.

    catches the case where ollama is installed with models pulled but the server
    is not currently running, so we still know not to re-download equivalents.
    the manifest tree is <root>/manifests/<registry>/<namespace>/<name>/<tag>.
    """
    out: list[DiscoveredModel] = []
    try:
        manifests = _ollama_root() / "manifests"
        if not manifests.is_dir():
            return out
        for tag_file in manifests.rglob("*"):
            if not tag_file.is_file():
                continue
            # .../<name>/<tag>  ->  "name:tag"
            name = f"{tag_file.parent.name}:{tag_file.name}"
            size = 0.0
            try:
                data = json.loads(tag_file.read_text(encoding="utf-8"))
                size = round(
                    sum(la.get("size", 0) for la in data.get("layers", [])) / (1024 ** 3), 2
                )
            except (json.JSONDecodeError, OSError, AttributeError):
                pass  # a manifest we cannot parse still proves the model exists
            out.append(DiscoveredModel(name=name, source="ollama-disk", size_gb=size))
    except OSError as e:
        logger.debug("could not scan ollama models on disk: %s", e)
    return out


def _lmstudio_roots() -> list[Path]:
    home = Path.home()
    return [
        home / ".cache" / "lm-studio" / "models",   # linux / older macOS
        home / ".lmstudio" / "models",              # newer layout
        home / "Library" / "Application Support" / "LM Studio" / "models",  # macOS
    ]


def find_lmstudio_models() -> list[DiscoveredModel]:
    """gguf files managed by LM Studio."""
    out: list[DiscoveredModel] = []
    for root in _lmstudio_roots():
        try:
            if not root.is_dir():
                continue
            for f in root.rglob("*.gguf"):
                out.append(DiscoveredModel(
                    name=f.name, source="lmstudio", path=str(f), size_gb=_size_gb(f),
                ))
        except OSError as e:
            logger.debug("could not scan lm studio dir %s: %s", root, e)
    return out


def discover_all(models_dir: Path, ollama_base_url: str) -> list[DiscoveredModel]:
    """every model found on this machine, de-duplicated by (name, source).

    never raises: each probe is independently guarded, so a broken ollama install
    or an unreadable directory degrades to "found nothing there".
    """
    found: list[DiscoveredModel] = []
    found.extend(find_thinkstack_models(models_dir))
    found.extend(find_ollama_running(ollama_base_url))

    # only fall back to reading ollama's disk layout when the server did not
    # answer; otherwise the same models would be listed twice.
    if not any(m.source == "ollama" for m in found):
        found.extend(find_ollama_on_disk())

    found.extend(find_lmstudio_models())

    seen: set[tuple[str, str]] = set()
    unique: list[DiscoveredModel] = []
    for m in found:
        key = (m.name, m.source)
        if key not in seen:
            seen.add(key)
            unique.append(m)

    logger.info(
        "model discovery: %d found (%s)",
        len(unique),
        ", ".join(sorted({m.source for m in unique})) or "none",
    )
    return unique


def installed_names(models: list[DiscoveredModel]) -> set[str]:
    """the set used to decide whether an upgrade is still worth offering.

    includes a normalised form of ollama tags ("qwen2.5:1.5b" -> "qwen2.5-1.5b")
    so an equivalent model already pulled through ollama suppresses the prompt to
    download our gguf of it.
    """
    names: set[str] = set()
    for m in models:
        names.add(m.name)
        base = m.name.replace(":", "-").replace("_", "-").lower()
        names.add(base)
        if base.endswith(".gguf"):
            names.add(base[: -len(".gguf")])
    return names
