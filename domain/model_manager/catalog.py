"""model catalog.

the set of models ThinkStack knows how to use, which one ships inside the
installer, and which extras a given machine can actually run.

the baseline model is BUNDLED so a fresh install works completely offline with
no download and no account -- that is the whole premise of the product. heavier
models are optional: they are only ever fetched when the hardware can run them
AND the user explicitly agrees (see routes_models.py), because downloading a
gigabyte of weights without asking is not something an offline-first app does.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSpec:
    """one model ThinkStack can use."""

    name: str            # gguf filename, the id used everywhere else
    label: str           # human-readable, shown in the UI
    size_gb: float       # download / on-disk size
    url: str             # where to fetch it when it is not bundled
    bundled: bool        # ships inside the installer?
    # tasks this model is good for. the base model handles everything; the
    # analysis model exists because the 0.5b produces unparseable json on
    # structured-output tasks.
    tasks: tuple[str, ...] = ()
    # minimum *available* RAM (gb) before we offer this model. compared against
    # the hardware budget, which already reserves headroom for other apps.
    min_ram_gb: float = 0.0
    description: str = ""


# the baseline. bundled in the installer; the app is fully functional with only
# this. keep this in sync with release.config.json's `bundled_models`.
BASE_MODEL = ModelSpec(
    name="qwen2.5-0.5b-instruct-q4_k_m.gguf",
    label="Qwen2.5 0.5B (base)",
    size_gb=0.47,
    url="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
    bundled=True,
    tasks=("general", "chat", "search", "latex_writer"),
    min_ram_gb=0.0,
    description="Ships with the app. Fast, runs on any machine, works offline immediately.",
)

# optional upgrade. the 0.5b rambles and emits invalid json on summarize/claims/
# themes/gap-analysis, so these route to a larger model when one is available.
ANALYSIS_MODEL = ModelSpec(
    name="qwen2.5-1.5b-instruct-q4_k_m.gguf",
    label="Qwen2.5 1.5B (analysis)",
    size_gb=1.1,
    url="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
    bundled=False,
    tasks=("analysis", "gap_analysis"),
    min_ram_gb=2.5,
    description="Optional. Much more reliable on summaries and gap analysis. Downloaded only if you allow it.",
)

CATALOG: tuple[ModelSpec, ...] = (BASE_MODEL, ANALYSIS_MODEL)


def by_name(name: str) -> ModelSpec | None:
    """look up a catalog entry by its gguf filename."""
    for spec in CATALOG:
        if spec.name == name:
            return spec
    return None


def bundled_models() -> list[ModelSpec]:
    """models that ship inside the installer."""
    return [s for s in CATALOG if s.bundled]


def optional_models() -> list[ModelSpec]:
    """models that are downloaded on demand, never shipped."""
    return [s for s in CATALOG if not s.bundled]


def runnable_on(budget_gb: float) -> list[ModelSpec]:
    """catalog entries this machine has the memory to run.

    args:
        budget_gb: the hardware memory budget (available RAM minus headroom for
            other apps, plus VRAM) -- see infrastructure.hardware.

    returns:
        every spec whose min_ram_gb fits the budget. a budget of 0 means
        "unknown", in which case only the bundled baseline is considered safe.
    """
    if budget_gb <= 0:
        return bundled_models()
    return [s for s in CATALOG if s.min_ram_gb <= budget_gb]


def suggested_upgrade(budget_gb: float, installed: set[str]) -> ModelSpec | None:
    """the best optional model worth offering, or None.

    returns None when the machine cannot run any upgrade, or when every model it
    could run is already present -- so the UI only ever prompts when there is a
    real, actionable improvement available.

    args:
        budget_gb: hardware memory budget in gb.
        installed: gguf filenames already available on this machine (from any
            source: bundled, previously downloaded, ollama, lm studio).
    """
    candidates = [
        s for s in optional_models()
        if s.name not in installed and s.min_ram_gb <= budget_gb
    ]
    if not candidates:
        return None
    # largest model the machine can handle is the most capable one
    return max(candidates, key=lambda s: s.size_gb)
