"""Models ThinkStack knows how to fetch, and which are worth offering here.

The baseline is BUNDLED so a fresh install works offline with no download and
no account. Everything else is fetched only when the hardware can run it AND
the user agrees.

Three rules for anyone editing this file:

**Check the URL.** A wrong one is a download that fails for every user who
clicks it. Two of the first six written here were dead.

**No reasoning model in the bundled slot.** Structured output is constrained by
a GBNF grammar permitting only JSON from the first token, so a model emitting a
``<think>`` block has nowhere to put it and closes the object immediately,
returning ``{}``. This passes every structural check -- verified URL, right
size, valid GGUF, JSON that ``json.loads`` accepts -- and is empty. Only
running a generation and READING THE OUTPUT catches it. Validity is not
usefulness.

**``tasks`` is AUTHORITATIVE.** The registry seeds assignments from it, so
listing a task means "choose this model for that job". When the base model
claimed ``latex_writer``, the 0.5B silently outranked the 1.5B for Scribe.
Claim a task only if you are the best model here for it -- the base model is
the fallback for everything already, guaranteed by the router.
"""

from dataclasses import dataclass

# The largest model, in GB of q4 weights, that answers in a tolerable time with
# no GPU acceleration.
#
# Memory is not the binding constraint on a machine without a usable GPU;
# throughput is. A q4 model's CPU speed falls roughly with its parameter count,
# so on a typical laptop processor a 0.5B answers at conversational speed, a
# 1.5B is noticeably slower but usable, and a 3B or 4B takes minutes per
# summary. A machine with 20 GB free can hold a 4B comfortably and should still
# not be told to fetch one: it would fit, and then disappoint.
#
# Above this size a model is only suggested when the engine can offload it to a
# GPU that has room for it.
CPU_COMFORTABLE_GB = 1.2


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

    # What the user GETS, in their language. The model's name answers "which
    # weights"; this answers "why would I want it", which is the only question
    # a researcher actually has. Shown first; the name is a details line.
    outcome: str = ""

    description: str = ""

    def speed_words(self, gpu_gb: float = 0.0) -> str:
        """How long this feels to use, in plain words.

        Deliberately vague: this is shown BEFORE anything is installed, so a
        precise figure would be invented from a formula and quietly wrong.
        Honest imprecision beats false precision.
        """
        accelerated = gpu_gb > 0 and self.size_gb <= gpu_gb
        if accelerated or self.size_gb <= 0.5:
            return "answers in a few seconds"
        if self.size_gb <= CPU_COMFORTABLE_GB:
            return "about half a minute per paper"
        if self.size_gb <= 2.0:
            return "a minute or two per paper"
        return "several minutes per paper"

    def runs_on_tier(self, tier: str) -> bool:
        """whether this is a model worth suggesting on ``tier``."""
        return not self.good_on_tiers or tier in self.good_on_tiers

    def runs_well_on(self, gpu_gb: float = 0.0) -> bool:
        """Whether this answers in a tolerable time here.

        A model fitting in `gpu_gb` runs accelerated and its size stops
        mattering much; one that does not runs on the processor, where size is
        the whole story.
        """
        if gpu_gb > 0 and self.size_gb <= gpu_gb:
            return True
        return self.size_gb <= CPU_COMFORTABLE_GB


# ── the smallest optional baseline ─────────────────────────────────────
# Models are deliberately never shipped in the installer. Bench is the consent
# boundary: it offers this compact baseline for an explicit download after
# install, or users can reuse an equivalent Ollama/LM Studio model.
#
# Chosen for the FLAGSHIP features rather than for summarisation. Gap finding
# and Scribe produce structured output, and ollama_client constrains that with
# a GBNF grammar -- a small model cannot emit malformed JSON, so only content
# quality varies, and on constrained, templated output a 0.6B does well.
# Summarisation is open-ended prose over a whole paper: the one job that
# genuinely wants a larger model, and the reason the optional entries exist.
#
# Measured, not assumed. A bake-off against Qwen3 0.6B, Gemma 3 1B and
# Llama 3.2 1B on the two flagship jobs put this model first: joint-best gap
# recall (4 of 6 stated limitations), valid LaTeX, and the fastest of the set.
# Qwen3 0.6B was smaller and newer and returned `{}` -- see the reasoning-model
# note above.
BASE_MODEL = ModelSpec(
    name="qwen2.5-0.5b-instruct-q4_k_m.gguf",
    label="Qwen2.5 0.5B",
    size_gb=0.46,
    url="https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf",
    bundled=False,
    # Claims the structured jobs it is good at, and `general`. NOT `analysis`:
    # summaries are where a bigger model earns its download, and claiming that
    # here would stop us ever suggesting one.
    tasks=("general", "gap_analysis", "latex_writer"),
    min_ram_gb=0.0,
    quality=15,
    outcome="Smallest download offered",
    description="The lightest model Bench offers. Good at finding gaps and "
                "drafting LaTeX; summaries will be rough.",
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
    outcome="Reliable summaries",
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
    outcome="A different writing style",
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
    outcome="Better on long papers",
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
    outcome="Better summaries and gap finding",
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
    outcome="The best quality offered",
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
    """Entries this machine has the memory to run.

    A budget of 0 means "could not measure", and yields only the lightest
    model. Answering "nothing runs" would leave a machine we merely failed to
    measure with no options at all.
    """
    if budget_gb <= 0:
        # A failed hardware measurement must not make Bench blank. Offer the
        # smallest download, but leave the user to consent to it.
        return [min(CATALOG, key=lambda s: s.size_gb)]
    return [s for s in CATALOG if s.min_ram_gb <= budget_gb]


def _installed_key_match(spec: ModelSpec, installed: set[str]) -> bool:
    """whether ``installed`` already contains these weights, under any name."""
    from domain.model_manager.discovery import model_key

    return spec.name in installed or model_key(spec.name) in installed


def suggested_upgrade(
    budget_gb: float, installed: set[str], tier: str = "", gpu_gb: float = 0.0
) -> ModelSpec | None:
    """The best optional model worth offering ON THIS MACHINE, or None.

    Applies BOTH constraints, because they are different questions:
    `min_ram_gb` asks whether the weights fit, `good_on_tiers` whether running
    them here is tolerable. A 4B model fits a 16 GB laptop and still produces
    one summary every few minutes on it -- offering it because it *fits* is how
    a user concludes the app is broken.

    None when nothing better can run, or when everything that could is already
    installed, so the interface only prompts on a real improvement.

    An empty `tier` applies no tier constraint: suggesting something slightly
    ambitious beats suggesting nothing because we could not classify the
    machine. `gpu_gb` is what the ENGINE can offload to, which is zero both on
    a CPU-only build and on a GPU our llama.cpp cannot use.
    """
    # A catalog is still visible in Bench, but an automatic recommendation
    # needs a real memory measurement.  Do not turn an unknown machine into an
    # implicit request to download even the smallest model.
    if budget_gb <= 0:
        return None

    candidates = [
        s for s in optional_models()
        if not _installed_key_match(s, installed)
        and s.min_ram_gb <= budget_gb
        and (not tier or s.runs_on_tier(tier))
        # Memory is not the only constraint. Without a GPU the engine can use,
        # a model large enough to fit is still large enough to take minutes per
        # summary -- so a machine with plenty of free RAM and no acceleration
        # must not be told to fetch a 3B. See CPU_COMFORTABLE_GB.
        and s.runs_well_on(gpu_gb)
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
    task: str, budget_gb: float, tier: str = "",
    installed: set[str] | None = None, gpu_gb: float = 0.0
) -> ModelSpec | None:
    """What this catalog would pick for `task` here. ADVICE, not routing.

    The router answers "what will actually run" from what is installed; this
    answers "what should you get" from what exists. Bench shows them side by
    side, which is how a user learns their gap analysis could be better.

    Prefers a model claiming the task, else the most capable that fits.
    Installed models are skipped -- suggesting what someone has is noise.
    """
    installed = installed or set()
    affordable = [
        s for s in CATALOG
        if s.min_ram_gb <= budget_gb
        and not s.bundled
        and not _installed_key_match(s, installed)
        and (not tier or s.runs_on_tier(tier))
        and s.runs_well_on(gpu_gb)
    ]
    if not affordable:
        return None

    claimed = [s for s in affordable if task in s.tasks]
    pool = claimed or affordable
    return max(pool, key=lambda s: (s.quality, s.size_gb))


def default_tasks_for(name: str) -> tuple[str, ...]:
    """Jobs a freshly downloaded model should take on, so it does the work it
    was fetched for rather than sitting unassigned."""
    spec = by_name(name)
    return spec.tasks if spec else ()
