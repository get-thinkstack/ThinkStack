"""every feature must ASK for the task it is, or the user's Bench choice is lost.

Bench lets a user assign a model per task. That assignment only takes effect if
the calling code names its task when it generates: `ollama_client` routes on the
`task_type=` argument, looking up whatever model the registry has for that task.

The argument defaults to `"general"`. That default is the trap. A caller that
forgets it does not crash, does not warn, and does not fall back to anything
obviously wrong -- it silently resolves the WRONG task, finds no assignment,
and uses the base model, while Bench keeps showing the model the user picked.
It looks exactly like a working feature.

This has now happened twice:

  * `latex_writer` -- Scribe was routed to the small model because the task was
    listed only against fine-tuned models that are not built or shipped.
  * `gap_analysis` -- gap finding was merged from two calls into one
    (`gap_pipeline`), and the merge dropped the `task_type=` the old
    `gap_analyzer` passed. Gap finding, a flagship feature, ran on the base
    model and ignored its Bench assignment entirely.

Both were invisible from the outside, which is why they need a test that reads
the request rather than the result. Each case below drives the real entry point
with the model stubbed out, then asserts on what the entry point ASKED FOR.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from domain.model_manager.registry import KNOWN_TASKS

# The task each user-facing feature must request. A feature missing from this
# map is a feature whose Bench assignment nobody has proven works.
EXPECTED_TASK = {
    "gap finding": "gap_analysis",
    "summarize one paper": "analysis",
    "summarize many papers": "analysis",
    "extract claims": "analysis",
    "cluster themes": "analysis",
    "scribe (latex)": "latex_writer",
}


def test_every_expected_task_is_a_real_task():
    """guards the map itself: a typo here would make every assertion vacuous."""
    for feature, task in EXPECTED_TASK.items():
        assert task in KNOWN_TASKS, f"{feature} names a task Bench cannot assign: {task}"


class TestFeaturesNameTheirTask:
    """drive each entry point and read back the task_type it requested."""

    @pytest.mark.asyncio
    async def test_gap_finding_requests_gap_analysis(self):
        from domain.gap_finder.gap_pipeline import analyze_gaps_and_suggestions

        payload = json.dumps({"gaps": [], "suggestions": []})
        with patch("infrastructure.ollama_client.ollama_client.generate_json",
                   new=AsyncMock(return_value=payload)) as m:
            await analyze_gaps_and_suggestions(
                [{"doc_id": "d1", "text": "a paper"}],
                [{"doc_id": "d1", "text": "a claim", "type": "finding"}],
                ["d1"],
            )
        assert m.call_args.kwargs.get("task_type") == EXPECTED_TASK["gap finding"]

    @pytest.mark.asyncio
    async def test_summarize_single_requests_analysis(self):
        from domain.analysis.summarizer import summarize_single

        payload = json.dumps({"summary": "s", "key_points": ["a"]})
        with patch("infrastructure.ollama_client.ollama_client.generate_json",
                   new=AsyncMock(return_value=payload)) as m:
            await summarize_single("d1", "some paper text")
        assert m.call_args.kwargs.get("task_type") == EXPECTED_TASK["summarize one paper"]

    @pytest.mark.asyncio
    async def test_extract_claims_requests_analysis(self):
        from domain.analysis.claim_extractor import extract_claims

        payload = json.dumps({"claims": []})
        with patch("infrastructure.ollama_client.ollama_client.generate_json",
                   new=AsyncMock(return_value=payload)) as m:
            await extract_claims("d1", "some paper text")
        assert m.call_args.kwargs.get("task_type") == EXPECTED_TASK["extract claims"]

    @pytest.mark.asyncio
    async def test_theme_clustering_requests_analysis(self):
        from domain.analysis import theme_clusterer

        payload = json.dumps({"themes": []})
        with patch("infrastructure.ollama_client.ollama_client.generate_json",
                   new=AsyncMock(return_value=payload)) as m:
            await theme_clusterer._label([["d1", "d2"]], {"d1": "text one", "d2": "text two"})
        assert m.call_args.kwargs.get("task_type") == EXPECTED_TASK["cluster themes"]


class TestNoFeatureSilentlyTakesTheDefault:
    """the source-level backstop.

    The behavioural tests above only cover entry points somebody remembered to
    add. This reads the code instead, so a NEW feature that forgets `task_type=`
    is caught the day it lands rather than whenever someone notices their Bench
    choice does nothing.

    `general` is a legitimate answer for genuinely generic work -- it just has to
    be written down, so that "no task" and "the general task" stop looking
    identical in the source.
    """

    def test_every_generation_call_states_its_task(self):
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        offenders = []

        for path in list((root / "domain").rglob("*.py")) + list((root / "api").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name not in ("generate", "generate_json"):
                    continue
                # only calls on the shared client route by task; a `generate`
                # method on some other object is not our business.
                target = getattr(fn, "value", None)
                target_name = getattr(target, "id", "") or getattr(target, "attr", "")
                if target_name != "ollama_client":
                    continue
                if not any(k.arg == "task_type" for k in node.keywords):
                    offenders.append(
                        f"{path.relative_to(root)}:{node.lineno} {name}() has no task_type="
                    )

        assert not offenders, (
            "these calls fall back to the 'general' task, so a model assigned to "
            "their feature in Bench is ignored:\n  " + "\n  ".join(offenders)
        )
