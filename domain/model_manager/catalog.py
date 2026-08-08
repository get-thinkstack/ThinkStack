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

REASONING MODELS CANNOT BE THE BASELINE
--------------------------------------
``ollama_client`` constrains structured output with a GBNF grammar that permits
only JSON, from the first token. A reasoning model -- Qwen3, and anything else
that emits a ``<think>`` block before answering -- has nowhere to put that
block, so it closes the object immediately and returns ``{}``.

This is invisible to every structural check. Qwen3 0.6B had a verified URL, the
right size, valid GGUF magic, and returned JSON that ``json.loads`` accepted.
The JSON was empty. Only running a generation and READING THE CONTENT caught
it, and it would have shipped broken on gap finding and Scribe -- the two
features the baseline is chosen for.

Any model considered for the bundled slot must be run through
``local/notes/`` bakeoff first. Validity is not usefulness.


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
        """how long this feels to use on such a machine, in plain words.

        Deliberately vague. A precise figure would have to be measured, and
        this is shown before anything is installed -- so it says what a user
        can plan around ("a few seconds", "a minute or two") rather than a
        number invented from a formula and then quietly wrong.

        Replaced by a measured figure once the model has run once; see the
        estimator work. Until then, honest imprecision beats false precision.
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
        """whether this will answer in a tolerable time on such a machine.

        ``gpu_gb`` is memory the ENGINE can actually offload to -- zero on a
        CPU-only build, and zero on a machine whose GPU the shipped llama.cpp
        cannot use, which are different situations with the same consequence.

        A model that fits in that memory runs accelerated and its size stops
        mattering much. One that does not runs on the processor, where size is
        the whole story.
        """
        if gpu_gb > 0 and self.size_gb <= gpu_gb:
            return True
        return self.size_gb <= CPU_COMFORTABLE_GB


# ── the bundled baseline ───────────────────────────────────────────────
# Ships inside the installer so ThinkStack works the moment it opens, with no
# download and no account.
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
    bundled=True,
    # Claims the structured jobs it is good at, and `general`. NOT `analysis`:
    # summaries are where a bigger model earns its download, and claiming that
    # here would stop us ever suggesting one.
    tasks=("general", "gap_analysis", "latex_writer"),
    min_ram_gb=0.0,
    quality=15,
    outcome="Included with ThinkStack",
    description="Works the moment you open the app. Good at finding gaps and "
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
    """catalog entries this machine has the memory to run.

    args:
        budget_gb: the hardware memory budget (available RAM minus headroom for
            other apps, plus VRAM) -- see infrastructure.hardware.

    returns:
        every spec whose min_ram_gb fits the budget. a budget of 0 means
        "unknown", in which case only the lightest model is considered safe --
        it used to mean "the bundled one", but nothing is bundled now, and
        answering "nothing runs" would leave a machine we simply failed to
        measure with no options at all.
    """
    if budget_gb <= 0:
        return bundled_models()
    return [s for s in CATALOG if s.min_ram_gb <= budget_gb]


def _installed_key_match(spec: ModelSpec, installed: set[str]) -> bool:
    """whether ``installed`` already contains these weights, under any name."""
    from domain.model_manager.discovery import model_key

    return spec.name in installed or model_key(spec.name) in installed


def suggested_upgrade(
    budget_gb: float, installed: set[str], tier: str = "", gpu_gb: float = 0.0
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
        gpu_gb: memory the ENGINE can offload to, from
            ``capability.usable_gpu_memory_gb``. Zero on a CPU-only build and
            zero on a machine whose GPU the shipped llama.cpp cannot use.
    """
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
        and s.runs_well_on(gpu_gb)
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
