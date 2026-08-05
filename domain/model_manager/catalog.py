"""model catalog.

The set of models ThinkStack knows how to fetch, which one ships inside the
installer, and which are worth offering on a given machine for a given job.

The baseline model is BUNDLED so a fresh install works completely offline with
no download and no account -- that is the whole premise of the product. Every
other entry is optional: fetched only when the hardware can run it AND the user
explicitly agrees, because downloading a gigabyte of weights without asking is
not something an offline-first app does.

Every URL here has been checked to return 200 with a plausible content-length.
That is not pedantry: a wrong URL is a download that fails for every user who
clicks it, and two of the first six candidates written for this file were dead.
Re-check before adding one.

``tasks`` is AUTHORITATIVE, not descriptive
------------------------------------------
The registry seeds a model's task assignments from this field, so listing a task
here means "this model should be CHOSEN for that job". It used to be loose
metadata, and when the base model claimed ``latex_writer`` the 0.5B began
outranking the 1.5B for Scribe -- silently undoing the deliberate routing
documented at ``ollama_client.TASK_MODEL_MAP``.

The rule: claim a task only if you are the best model here for it. The base
model is the fallback for EVERYTHING and the router guarantees that, so it never
needs to claim a task in order to be used for one.
"""

from dataclasses import dataclass

# Ordered worst to best, so a tier can be compared with `>=` via TIER_RANK.
TIERS = ("low", "medium", "high")
TIER_RANK = {t: i for i, t in enumerate(TIERS)}


@dataclass(frozen=True)
class ModelSpec:
    """one model ThinkStack can use."""

    name: str            # gguf filename, the id used everywhere else
    label: str           # human-readable, shown in the UI
    size_gb: float       # download / on-disk size, verified against the host
    url: str             # where to fetch it when it is not bundled
    bundled: bool        # ships inside the installer?

    # Jobs this model should be CHOSEN for when it is installed. See the module
    # docstring: this drives routing, so claim a task only if this is the best
    # model in the catalog for it.
    tasks: tuple[str, ...] = ()

    # Minimum *available* RAM (gb) before we offer this model, compared against
    # the hardware budget, which already reserves headroom for other apps.
    min_ram_gb: float = 0.0

    # Machine tiers where this is a sensible recommendation. A 4B model is
    # runnable on a medium machine but painfully slow, so "can run it" and
    # "should be told about it" are different questions and get different
    # fields. Empty means "every tier".
    good_on_tiers: tuple[str, ...] = ()

    # Relative capability, used to pick between two models that both fit and
    # both claim a task. Roughly tracks parameter count, but not exactly --
    # a newer 1B can beat an older 3B on instruction following.
    quality: int = 0

    description: str = ""

    def runs_on_tier(self, tier: str) -> bool:
        """whether this is a model worth suggesting on ``tier``."""
        return not self.good_on_tiers or tier in self.good_on_tiers


# ── the baseline ───────────────────────────────────────────────────────
# Bundled in the installer; the app is fully functional with only this.
# Keep in sync with release.config.json's model list.
BASE_MODEL = ModelSpec(
    name="qwen2.5-0.5b-instruct-q4_k_m.gguf",
    label="Qwen2.5 0.5B (base)",
    size_gb=0.46,
    url="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
    bundled=True,
    # ONLY general. It is the fallback for everything by construction; claiming
    # a structured task would let it beat a model chosen on purpose. See the
    # module docstring and tests/test_model_reconcile.py.
    tasks=("general",),
    min_ram_gb=0.0,
    quality=10,
    description="Ships with the app. Fast, runs on any machine, works offline immediately.",
)

# ── optional upgrades, smallest first ──────────────────────────────────
# The 0.5B rambles and emits invalid JSON on summarize / claims / themes / gap
# analysis, so these exist to take over the structured work.

ANALYSIS_MODEL = ModelSpec(
    name="qwen2.5-1.5b-instruct-q4_k_m.gguf",
    label="Qwen2.5 1.5B",
    size_gb=1.04,
    url="https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF/resolve/main/qwen2.5-1.5b-instruct-q4_k_m.gguf",
    bundled=False,
    tasks=("analysis", "gap_analysis", "latex_writer"),
    min_ram_gb=2.5,
    quality=30,
    description="The smallest model that reliably returns structured output. "
                "A large improvement on summaries, claims and gap analysis.",
)

GEMMA_1B = ModelSpec(
    name="gemma-3-1b-it-Q4_K_M.gguf",
    label="Gemma 3 1B",
    size_gb=0.75,
    url="https://huggingface.co/unsloth/gemma-3-1b-it-GGUF/resolve/main/gemma-3-1b-it-Q4_K_M.gguf",
    bundled=False,
    # Deliberately claims nothing. It is an ALTERNATIVE to the base model for
    # people who prefer Gemma's writing, not an upgrade that should take over a
    # job -- and claiming one would make it outrank Qwen2.5 1.5B on a machine
    # where both are installed.
    tasks=(),
    min_ram_gb=2.0,
    good_on_tiers=("low", "medium"),
    quality=20,
    description="A small alternative to the bundled model. Similar speed, "
                "different writing style.",
)

LLAMA_3B = ModelSpec(
    name="Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    label="Llama 3.2 3B",
    size_gb=1.88,
    url="https://huggingface.co/unsloth/Llama-3.2-3B-Instruct-GGUF/resolve/main/Llama-3.2-3B-Instruct-Q4_K_M.gguf",
    bundled=False,
    tasks=("analysis", "gap_analysis", "latex_writer"),
    min_ram_gb=4.0,
    good_on_tiers=("medium", "high"),
    quality=40,
    description="Stronger reasoning than the 1.5B, at roughly twice the size. "
                "Noticeably better on long papers.",
)

QWEN_3B = ModelSpec(
    name="qwen2.5-3b-instruct-q4_k_m.gguf",
    label="Qwen2.5 3B",
    size_gb=1.96,
    url="https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/qwen2.5-3b-instruct-q4_k_m.gguf",
    bundled=False,
    tasks=("analysis", "gap_analysis", "latex_writer"),
    min_ram_gb=4.0,
    good_on_tiers=("medium", "high"),
    quality=45,
    description="A larger Qwen with the same structured-output reliability. "
                "A good default when memory allows.",
)

QWEN3_4B = ModelSpec(
    name="Qwen3-4B-Q4_K_M.gguf",
    label="Qwen3 4B",
    size_gb=2.33,
    url="https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf",
    bundled=False,
    tasks=("analysis", "gap_analysis", "latex_writer"),
    min_ram_gb=5.5,
    good_on_tiers=("high",),
    quality=60,
    description="The most capable model ThinkStack suggests. Best summaries and "
                "gap analysis, and slow on anything but a roomy machine.",
)

CATALOG: tuple[ModelSpec, ...] = (
    BASE_MODEL,
    GEMMA_1B,
    ANALYSIS_MODEL,
    LLAMA_3B,
    QWEN_3B,
    QWEN3_4B,
)


# ── lookup ─────────────────────────────────────────────────────────────


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


def _installed_key_match(spec: ModelSpec, installed: set[str]) -> bool:
    """whether ``installed`` already contains these weights, under any name."""
    from domain.model_manager.discovery import model_key

    return spec.name in installed or model_key(spec.name) in installed


def suggested_upgrade(
    budget_gb: float, installed: set[str], tier: str = ""
) -> ModelSpec | None:
    """the best optional model worth offering ON THIS MACHINE, or None.

    Applies BOTH hardware constraints, because they answer different questions:

        min_ram_gb    can this machine hold the weights at all?
        good_on_tiers is running it here a good experience?

    A 4B model fits comfortably in a 16 GB machine's budget and is still a poor
    suggestion for a low-tier laptop, where it would produce one summary every
    few minutes. Offering it because it *fits* is how you get a user who
    concludes the app is broken.

    Returns None when the machine can run nothing better, or when everything it
    could run is already present -- so the UI only prompts when there is a real,
    actionable improvement available.

    args:
        budget_gb: hardware memory budget in gb.
        installed: gguf filenames already available on this machine, from any
            source (bundled, previously downloaded, Ollama, LM Studio).
        tier: "low" | "medium" | "high" from the hardware profile. Empty means
            unknown, which applies no tier constraint -- refusing to suggest
            anything because we could not classify the machine is worse than
            suggesting something slightly ambitious.
    """
    candidates = [
        s for s in optional_models()
        if not _installed_key_match(s, installed)
        and s.min_ram_gb <= budget_gb
        and (not tier or s.runs_on_tier(tier))
        # An upgrade has to UPGRADE something. A model claiming no tasks is an
        # alternative to the bundled one, not an improvement on it, so offering
        # it as "your machine can run a better model" would have the user
        # download weights that then sit doing nothing.
        and s.tasks
    ]
    if not candidates:
        return None
    # Most capable, not simply largest. Size was a decent proxy while the
    # catalog held one upgrade; with several families in it, a newer small
    # model can beat an older larger one.
    return max(candidates, key=lambda s: (s.quality, s.size_gb))


def suggest_for_task(
    task: str, budget_gb: float, tier: str = "", installed: set[str] | None = None
) -> ModelSpec | None:
    """the model this catalog would pick for ``task`` on this machine.

    This is ADVICE, not routing. The router answers "what will actually run",
    from what is installed; this answers "what should you get", from what
    exists. Bench shows the second next to the first, which is how a user finds
    out that their gap analysis could be better.

    Prefers a model that explicitly claims the task; falls back to the most
    capable model that fits, since a stronger general model still helps.
    Anything already installed is skipped -- suggesting what someone has is
    noise.
    """
    installed = installed or set()
    affordable = [
        s for s in CATALOG
        if s.min_ram_gb <= budget_gb
        and not s.bundled
        and not _installed_key_match(s, installed)
        and (not tier or s.runs_on_tier(tier))
    ]
    if not affordable:
        return None

    claimed = [s for s in affordable if task in s.tasks]
    pool = claimed or affordable
    return max(pool, key=lambda s: (s.quality, s.size_gb))


def default_tasks_for(name: str) -> tuple[str, ...]:
    """the jobs a freshly installed ``name`` should take on.

    Used when a download completes, so a model the user just fetched starts
    doing the work they fetched it for instead of sitting unassigned.
    """
    spec = by_name(name)
    return spec.tasks if spec else ()
