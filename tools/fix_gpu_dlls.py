"""make the CUDA build of llama-cpp-python actually load on this machine.

the prebuilt CUDA wheel from abetlen has two problems on a system without a
CUDA toolkit and without AVX-512 (e.g. AMD Zen 3/3+ laptops):

1. its bundled ``ggml-cuda.dll`` needs the CUDA 12 runtime DLLs (cudart /
   cublas / cublasLt), which aren't present without a CUDA toolkit.
2. its bundled ``ggml-cpu.dll`` is compiled with CPU instructions this CPU
   lacks, so context init crashes with 0xC000001D (illegal instruction).

this script fixes both, idempotently:
  * pip-installs the CUDA 12.4 runtime + cublas and copies their DLLs next to
    ggml-cuda.dll (Windows searches the loading DLL's own directory).
  * downloads the matching-version CPU-only wheel and swaps in its
    broadly-compatible ggml-cpu.dll (same llama.cpp version => ABI compatible).

re-run this after any `pip install/upgrade llama-cpp-python`.

usage:
    python scripts/fix_gpu_dlls.py
"""

import io
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from urllib.request import urlopen

CPU_WHEEL_URL = (
    "https://github.com/abetlen/llama-cpp-python/releases/download/"
    "v{ver}/llama_cpp_python-{ver}-py3-none-win_amd64.whl"
)


def _lib_dir() -> Path:
    import llama_cpp
    return Path(llama_cpp.__file__).parent / "lib"


def _pip(*args: str) -> None:
    subprocess.check_call([sys.executable, "-m", "pip", *args])


def ensure_cuda_runtime(lib: Path) -> None:
    """install CUDA 12.4 runtime DLLs and place them beside ggml-cuda.dll."""
    _pip("install", "nvidia-cuda-runtime-cu12~=12.4.0", "nvidia-cublas-cu12~=12.4.0")
    import nvidia  # noqa: F401  (provided by the packages above)
    site = Path(sys.modules["nvidia"].__file__).parent
    wanted = {
        "cudart64_12.dll": site / "cuda_runtime" / "bin" / "cudart64_12.dll",
        "cublas64_12.dll": site / "cublas" / "bin" / "cublas64_12.dll",
        "cublasLt64_12.dll": site / "cublas" / "bin" / "cublasLt64_12.dll",
    }
    for name, src in wanted.items():
        if not src.is_file():
            raise FileNotFoundError(f"expected CUDA DLL not found: {src}")
        shutil.copy2(src, lib / name)
        print(f"  placed {name}")


def swap_compatible_cpu_backend(lib: Path) -> None:
    """replace ggml-cpu.dll with the compatibility build from the CPU wheel."""
    import llama_cpp
    ver = llama_cpp.__version__
    url = CPU_WHEEL_URL.format(ver=ver)
    print(f"  downloading CPU wheel {ver} for a compatible ggml-cpu.dll ...")
    with urlopen(url) as resp:  # noqa: S310 - trusted release URL
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        dll = zf.read("llama_cpp/lib/ggml-cpu.dll")
    target = lib / "ggml-cpu.dll"
    backup = lib / "ggml-cpu.dll.cuda.bak"
    if target.is_file() and not backup.is_file():
        shutil.copy2(target, backup)
    target.write_bytes(dll)
    print(f"  swapped ggml-cpu.dll ({len(dll)} bytes)")


def main() -> int:
    lib = _lib_dir()
    print(f"llama_cpp lib dir: {lib}")
    print("1) CUDA runtime DLLs")
    ensure_cuda_runtime(lib)
    print("2) compatible CPU backend")
    swap_compatible_cpu_backend(lib)

    print("3) verify")
    from llama_cpp import llama_supports_gpu_offload
    ok = llama_supports_gpu_offload()
    print(f"   gpu_offload_supported = {ok}")
    if not ok:
        print("   FAILED: still no GPU support. Is the CUDA wheel installed?")
        print("   pip install llama-cpp-python --force-reinstall --no-deps \\")
        print("     --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124")
        return 1
    print("\ndone. run:  python scripts/verify_gpu.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
