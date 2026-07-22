"""verify that analysis inference actually runs on the gpu.

usage:
    python scripts/verify_gpu.py

prints the resolved model, whether the installed llama-cpp-python build
supports gpu offload, and a short generation's tokens/sec so you can confirm
the gpu -- not the cpu -- is doing the work. exits non-zero if the model
cannot be loaded on the gpu.
"""

import sys
import time
from pathlib import Path

# allow running as a plain script from anywhere in the repo.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings  # noqa: E402


def main() -> int:
    print("=" * 60)
    print("thinkstack gpu verification")
    print("=" * 60)
    print(f"provider   : {settings.llm_provider}")
    print(f"model path : {settings.llm_model_path}")
    print(f"gpu layers : {settings.llm_gpu_layers}  (-1 = all on gpu, 0 = cpu)")
    print(f"ctx size   : {settings.llm_ctx_size}")

    try:
        from llama_cpp import llama_supports_gpu_offload
        supported = llama_supports_gpu_offload()
        print(f"gpu build  : {supported}")
        if not supported:
            print("\nFAIL: installed llama-cpp-python is a CPU-only build.")
            print("install the CUDA build, then re-run this script.")
            return 1
    except ImportError:
        print("gpu build  : unknown (older binding, cannot pre-verify)")

    print("\nloading model (first load compiles/uploads to vram)...")
    from infrastructure.ollama_client import OllamaClient

    client = OllamaClient()
    t_load = time.perf_counter()
    llama = client._get_llama()  # raises if gpu required but unavailable
    print(f"loaded in {time.perf_counter() - t_load:.1f}s")

    prompt = (
        "Summarize in three short bullet points why retrieval-augmented "
        "generation improves factual accuracy in research assistants."
    )
    t0 = time.perf_counter()
    out = llama.create_completion(prompt=prompt, max_tokens=160, temperature=0.1)
    dt = time.perf_counter() - t0

    text = out["choices"][0]["text"].strip()
    n_tok = out.get("usage", {}).get("completion_tokens") or len(text.split())

    print("\n--- sample output ---")
    print(text[:500])
    print("\n--- speed ---")
    print(f"{n_tok} tokens in {dt:.2f}s = {n_tok / dt:.1f} tok/s")
    print("\ntip: watch VRAM live in another terminal with:")
    print("     nvidia-smi -l 1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
