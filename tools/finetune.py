#!/usr/bin/env python3
"""
thinkstack: local fine-tuning script for task-specific models.

uses qlora (quantized low-rank adaptation) to fine-tune the base
qwen2.5 model on locally collected training pairs. all data stays
on the user's machine - nothing is uploaded anywhere.

prerequisites (not in requirements.txt - install only if fine-tuning):
    pip install transformers>=4.46 trl>=0.12 peft>=0.13 \
                datasets>=3.0 bitsandbytes>=0.44 accelerate>=1.0

usage:
    python scripts/finetune.py --task latex_generation
    python scripts/finetune.py --task gap_analysis
    python scripts/finetune.py --task latex_generation --epochs 5 --lr 2e-4

after fine-tuning, the script:
    1. merges the lora adapter into the base model
    2. quantizes to gguf using llama.cpp's convert script
    3. copies the final gguf into data/models/ where the app auto-detects it

privacy: this script reads ONLY from data/training/*.jsonl (local files).
         no network requests are made during training.
"""

import argparse
import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── paths ──
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TRAINING_DIR = PROJECT_ROOT / "data" / "training"
MODELS_DIR = PROJECT_ROOT / "data" / "models"
OUTPUT_DIR = PROJECT_ROOT / "data" / "finetune_output"

# ── task → output model name mapping ──
TASK_MODEL_NAMES = {
    "latex_generation": "latex-writer",
    "gap_analysis": "gap-analysis",
}

# ── base model (huggingface id) ──
DEFAULT_BASE_MODEL = "Qwen/Qwen2.5-1.5B-Instruct"


def load_training_data(task: str) -> list[dict]:
    """load training examples from the local jsonl file.

    args:
        task: task type (latex_generation, gap_analysis).

    returns:
        list of training examples in chat format.
    """
    filepath = TRAINING_DIR / f"{task}.jsonl"
    if not filepath.exists():
        logger.error("no training data found at %s", filepath)
        logger.info(
            "use the app to generate latex / run gap analysis first. "
            "training pairs are collected automatically."
        )
        sys.exit(1)

    examples = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                # extract the chat messages for sft
                messages = data.get("messages", [])
                if len(messages) >= 2:
                    examples.append({"messages": messages})
            except json.JSONDecodeError:
                continue

    logger.info("loaded %d training examples from %s", len(examples), filepath)
    return examples


def check_dependencies():
    """verify fine-tuning dependencies are installed."""
    missing = []
    for pkg in ["transformers", "trl", "peft", "datasets", "bitsandbytes", "accelerate"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        logger.error(
            "missing fine-tuning dependencies: %s\n"
            "install with: pip install %s",
            ", ".join(missing),
            " ".join(missing),
        )
        sys.exit(1)


def check_gpu():
    """check if cuda is available for training."""
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            vram_gb = torch.cuda.get_device_properties(0).total_mem / (1024 ** 3)
            logger.info("gpu detected: %s (%.1f gb vram)", gpu_name, vram_gb)
            if vram_gb < 4:
                logger.warning(
                    "low vram (%.1f gb). qlora requires ~4 gb minimum for 1.5b models. "
                    "training may be very slow or fail.",
                    vram_gb,
                )
            return True
        else:
            logger.warning(
                "no cuda gpu detected. training will be extremely slow on cpu. "
                "consider using a machine with a gpu or google colab."
            )
            return False
    except ImportError:
        logger.warning("torch not installed with cuda support")
        return False


def run_finetune(
    task: str,
    base_model: str,
    epochs: int,
    learning_rate: float,
    batch_size: int,
    lora_r: int,
    lora_alpha: int,
):
    """run qlora fine-tuning on the collected training data.

    args:
        task: task type.
        base_model: huggingface model id for the base model.
        epochs: number of training epochs.
        learning_rate: learning rate.
        batch_size: per-device training batch size.
        lora_r: lora rank.
        lora_alpha: lora alpha scaling.
    """
    from datasets import Dataset
    from peft import LoraConfig, TaskType, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
    )
    from trl import SFTTrainer

    # ── load data ──
    examples = load_training_data(task)
    if len(examples) < 5:
        logger.error(
            "only %d examples found. need at least 5 for meaningful fine-tuning. "
            "use the app more to collect data first.",
            len(examples),
        )
        sys.exit(1)

    dataset = Dataset.from_list(examples)
    logger.info("dataset: %d examples", len(dataset))

    # ── output directory ──
    task_output = OUTPUT_DIR / task
    task_output.mkdir(parents=True, exist_ok=True)

    # ── quantization config (4-bit qlora) ──
    import torch
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )

    # ── load base model ──
    logger.info("loading base model: %s", base_model)
    tokenizer = AutoTokenizer.from_pretrained(base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)

    # ── lora config ──
    lora_config = LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=lora_r,
        lora_alpha=lora_alpha,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                         "gate_proj", "up_proj", "down_proj"],
        bias="none",
    )

    model = get_peft_model(model, lora_config)
    trainable, total = model.get_nb_trainable_parameters()
    logger.info(
        "lora: %d trainable / %d total params (%.2f%%)",
        trainable, total, 100 * trainable / total,
    )

    # ── training args ──
    training_args = TrainingArguments(
        output_dir=str(task_output / "checkpoints"),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=max(1, 4 // batch_size),
        learning_rate=learning_rate,
        warmup_ratio=0.1,
        weight_decay=0.01,
        logging_steps=10,
        save_strategy="epoch",
        bf16=torch.cuda.is_available(),
        report_to="none",  # no wandb/tensorboard - offline only
        remove_unused_columns=False,
    )

    # ── train ──
    trainer = SFTTrainer(
        model=model,
        args=training_args,
        train_dataset=dataset,
        tokenizer=tokenizer,
    )

    logger.info("starting fine-tuning (%d epochs, lr=%.2e)", epochs, learning_rate)
    trainer.train()

    # ── save adapter ──
    adapter_path = task_output / "adapter"
    model.save_pretrained(str(adapter_path))
    tokenizer.save_pretrained(str(adapter_path))
    logger.info("adapter saved to %s", adapter_path)

    return adapter_path


def merge_and_quantize(
    task: str,
    base_model: str,
    adapter_path: Path,
):
    """merge lora adapter into base model and quantize to gguf.

    args:
        task: task type (for naming the output file).
        base_model: huggingface model id.
        adapter_path: path to the saved lora adapter.
    """
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    model_name = TASK_MODEL_NAMES.get(task, task)
    merged_path = OUTPUT_DIR / task / "merged"

    # ── merge adapter ──
    logger.info("merging adapter into base model...")
    tokenizer = AutoTokenizer.from_pretrained(str(adapter_path))
    base = AutoModelForCausalLM.from_pretrained(
        base_model,
        device_map="cpu",
        trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(base, str(adapter_path))
    model = model.merge_and_unload()

    merged_path.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(merged_path))
    tokenizer.save_pretrained(str(merged_path))
    logger.info("merged model saved to %s", merged_path)

    # ── quantize to gguf ──
    gguf_output = MODELS_DIR / f"{model_name}.gguf"
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    # try llama.cpp's convert script
    convert_script = shutil.which("convert_hf_to_gguf") or shutil.which("convert_hf_to_gguf.py")
    if convert_script is None:
        # try to find it in common locations
        for candidate in [
            Path.home() / "llama.cpp" / "convert_hf_to_gguf.py",
            Path("/usr/local/bin/convert_hf_to_gguf.py"),
        ]:
            if candidate.exists():
                convert_script = str(candidate)
                break

    if convert_script:
        logger.info("quantizing to gguf (Q4_K_M)...")
        cmd = [
            sys.executable, str(convert_script),
            str(merged_path),
            "--outfile", str(gguf_output),
            "--outtype", "q4_k_m",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            logger.info("gguf model saved to %s", gguf_output)
            file_size = gguf_output.stat().st_size / (1024 ** 3)
            logger.info("model size: %.2f gb", file_size)
            logger.info(
                "\n✅ done! the app will auto-detect '%s' on next restart.\n"
                "the model will be used for '%s' tasks automatically.",
                gguf_output.name, task,
            )
            return gguf_output
        else:
            logger.error("gguf conversion failed: %s", result.stderr)
    else:
        logger.warning(
            "llama.cpp's convert_hf_to_gguf.py not found.\n"
            "to quantize manually:\n"
            "  1. clone https://github.com/ggerganov/llama.cpp\n"
            "  2. python llama.cpp/convert_hf_to_gguf.py %s "
            "--outfile %s --outtype q4_k_m",
            merged_path, gguf_output,
        )

    logger.info("merged model at %s (needs manual gguf conversion)", merged_path)
    return merged_path


def main():
    parser = argparse.ArgumentParser(
        description="thinkstack: fine-tune a local model on your collected data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
examples:
    # fine-tune for latex generation (default)
    python scripts/finetune.py --task latex_generation

    # fine-tune for gap analysis with more epochs
    python scripts/finetune.py --task gap_analysis --epochs 5

    # use a smaller base model (0.5b) for faster training
    python scripts/finetune.py --base-model Qwen/Qwen2.5-0.5B-Instruct

privacy:
    all training data comes from data/training/*.jsonl (local only).
    no data is uploaded anywhere. the fine-tuned model stays on your machine.
        """,
    )
    parser.add_argument(
        "--task",
        choices=["latex_generation", "gap_analysis"],
        default="latex_generation",
        help="which task to fine-tune for (default: latex_generation)",
    )
    parser.add_argument(
        "--base-model",
        default=DEFAULT_BASE_MODEL,
        help=f"huggingface model id (default: {DEFAULT_BASE_MODEL})",
    )
    parser.add_argument("--epochs", type=int, default=3, help="training epochs (default: 3)")
    parser.add_argument("--lr", type=float, default=2e-4, help="learning rate (default: 2e-4)")
    parser.add_argument("--batch-size", type=int, default=2, help="batch size (default: 2)")
    parser.add_argument("--lora-r", type=int, default=16, help="lora rank (default: 16)")
    parser.add_argument("--lora-alpha", type=int, default=32, help="lora alpha (default: 32)")
    parser.add_argument(
        "--merge-only",
        type=str,
        default=None,
        help="skip training; merge an existing adapter at this path",
    )

    args = parser.parse_args()

    print("=" * 55)
    print("  thinkstack: local fine-tuning")
    print("=" * 55)
    print(f"  task:       {args.task}")
    print(f"  base model: {args.base_model}")
    print("  privacy:    all data stays on this machine")
    print("=" * 55)

    if args.merge_only:
        adapter_path = Path(args.merge_only)
        if not adapter_path.exists():
            logger.error("adapter path not found: %s", adapter_path)
            sys.exit(1)
        merge_and_quantize(args.task, args.base_model, adapter_path)
        return

    check_dependencies()
    check_gpu()

    adapter_path = run_finetune(
        task=args.task,
        base_model=args.base_model,
        epochs=args.epochs,
        learning_rate=args.lr,
        batch_size=args.batch_size,
        lora_r=args.lora_r,
        lora_alpha=args.lora_alpha,
    )

    merge_and_quantize(args.task, args.base_model, adapter_path)


if __name__ == "__main__":
    main()
