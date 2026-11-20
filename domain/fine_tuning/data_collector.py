"""Training pairs for a future task-specific model, kept on this machine.

Scribe's generate route appends each prompt -> LaTeX pair, in chat format, to
`<data dir>/training/<task>.jsonl`. `save_gap_analysis_pair` exists but nothing
calls it yet. `tools/finetune.py` reads these files.
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
    """Append one example to `<task_type>.jsonl`; returns the file path."""
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
    """Append one gap-analysis example. Not called anywhere yet."""
    return save_latex_pair(
        prompt=paper_content,
        system=system,
        generated_latex=analysis_result,
        task_type="gap_analysis",
    )


def export_training_data(task_type: str = "latex_generation") -> list[dict]:
    """Every saved example for `task_type`."""
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
