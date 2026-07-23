# Running analysis on the GPU (NVIDIA)

The analysis models (theme clustering, claim extraction, summarization) run
locally through `llama-cpp-python`. On CPU a 4B model manages ~5–10 tok/s; on a
modest laptop GPU it does 40–60+ tok/s. This doc is the exact setup used to make
inference run **entirely on the GPU** and refuse to silently fall back to CPU.

Verified system: **RTX 4050 Laptop (6 GB), Ryzen 7 7735HS, Windows, Python
3.13, CUDA driver 596.49.** Result: Qwen3-4B-Instruct Q4_K_M at **~60 tok/s**.

## How it's wired

- `config.py` reads a gitignored **`.env`** for machine-specific overrides.
- **`.env`** pins the model and forces GPU:
  ```
  THINKSTACK_LLM_MODEL_PATH=<path to your .gguf>
  THINKSTACK_LLM_GPU_LAYERS=-1     # -1 = all layers on GPU
  ```
- `infrastructure/ollama_client.py` loads **GPU-strict**: when
  `LLM_GPU_LAYERS != 0` it verifies the build supports GPU offload and **raises
  instead of falling back to CPU**. It also enables flash attention (faster,
  smaller KV cache).

## One-time install

The default `pip install llama-cpp-python` is **CPU-only**. Use the CUDA build:

```bash
# 1. CUDA build of llama-cpp-python (cu124 works with driver CUDA >= 12.4)
pip install llama-cpp-python --force-reinstall --no-deps \
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124

# 2. fix the two DLL problems the prebuilt CUDA wheel has on toolkit-less /
#    AVX-512-less machines (installs CUDA runtime DLLs + swaps a compatible
#    CPU backend). Idempotent - re-run after any reinstall of llama-cpp-python.
python scripts/fix_gpu_dlls.py

# 3. verify: prints tokens/sec and confirms GPU offload
python scripts/verify_gpu.py
```

### Why step 2 is needed

The abetlen CUDA wheel bundles `ggml-cuda.dll` (needs CUDA 12 runtime DLLs that
aren't present without a CUDA toolkit) and a `ggml-cpu.dll` built with CPU
instructions some AMD laptops lack (Zen 3/3+ have no AVX-512) - which crashes
context init with `0xC000001D` (illegal instruction). `fix_gpu_dlls.py`:

1. `pip install nvidia-cuda-runtime-cu12 nvidia-cublas-cu12` and copies
   `cudart64_12.dll`, `cublas64_12.dll`, `cublasLt64_12.dll` next to
   `ggml-cuda.dll` (Windows searches the loading DLL's own folder).
2. downloads the same-version CPU wheel and swaps its compatibility-built
   `ggml-cpu.dll` in (same llama.cpp version ABI-compatible). The original is
   backed up as `ggml-cpu.dll.cuda.bak`.

## Troubleshooting

- **`gpu_offload_supported: False`** CPU-only wheel; redo step 1.
- **`0xC000001D` on load** step 2 not applied (or overwritten by a reinstall);
  re-run `python scripts/fix_gpu_dlls.py`.
- **`RuntimeError: ... refusing to fall back to CPU`** intended: the GPU build
  isn't loading. Fix the build; don't set `LLM_GPU_LAYERS=0` unless you actually
  want CPU.
- **Out of VRAM** on a smaller card lower `THINKSTACK_LLM_CTX_SIZE` (e.g. 2048)
  or use a smaller quant.
