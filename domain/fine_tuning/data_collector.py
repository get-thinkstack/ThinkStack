"""
training data collector for fine-tuning.

captures prompt → latex pairs from the paper writer's generate endpoint
so they can later be used to fine-tune a local slm (qlora) for better
latex generation and research gap analysis.

data is stored as jsonl files in data/training/ and can be exported
for cloud fine-tuning or used locally.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

TRAINING_DIR = settings.data_dir / "training"


def _ensure_dir() -> Path:
    """create the training data directory if it doesn't exist."""
    TRAINING_DIR.mkdir(parents=True, exist_ok=True)
    return TRAINING_DIR


def save_latex_pair(
    prompt: str,
    system: str,
    generated_latex: str,
    current_source: str = "",
    grounding_context: str = "",
    task_type: str = "latex_generation",
) -> Path:
    """persist a single training example (prompt → completion) to disk.

    args:
        prompt: the user's natural language request.
        system: the system prompt used.
        generated_latex: the ai-generated latex output.
        current_source: the document source at the time of generation.
        grounding_context: any rag context that was injected.
        task_type: one of 'latex_generation' or 'gap_analysis'.

    returns:
        path to the jsonl file the example was appended to.
    """
    _ensure_dir()
    filepath = TRAINING_DIR / f"{task_type}.jsonl"

    example = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task_type": task_type,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": generated_latex},
        ],
        "metadata": {
            "source_length": len(current_source),
            "grounding_length": len(grounding_context),
            "output_length": len(generated_latex),
        },
    }

    try:
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
        logger.debug("saved training example to %s", filepath)
    except Exception as e:
        logger.warning("failed to save training example: %s", e)

    return filepath


def save_gap_analysis_pair(
    paper_content: str,
    system: str,
    analysis_result: str,
) -> Path:
    """persist a gap analysis training example.

    args:
        paper_content: the combined paper summaries / claims text.
        system: the system prompt used for analysis.
        analysis_result: the ai's gap analysis output (json string).

    returns:
        path to the jsonl file the example was appended to.
    """
    return save_latex_pair(
        prompt=paper_content,
        system=system,
        generated_latex=analysis_result,
        task_type="gap_analysis",
    )


def export_training_data(task_type: str = "latex_generation") -> list[dict]:
    """load all saved training examples for a given task type.

    args:
        task_type: which dataset to export.

    returns:
        list of training example dictionaries.
    """
    filepath = TRAINING_DIR / f"{task_type}.jsonl"
    if not filepath.exists():
        return []

    examples = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    examples.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return examples


def training_stats() -> dict:
    """return counts of collected training examples by task type."""
    _ensure_dir()
    stats = {}
    for jsonl_file in TRAINING_DIR.glob("*.jsonl"):
        task = jsonl_file.stem
        count = sum(1 for line in open(jsonl_file) if line.strip())
        stats[task] = count
    return stats
