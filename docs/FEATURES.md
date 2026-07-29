# ThinkStack — Features

A detailed reference for everything ThinkStack does. For "what is it and how do I
get started", see [ABOUT.md](ABOUT.md). For shipping releases, see
[../scripts/README.md](../scripts/README.md).

ThinkStack is an **offline, edge-AI research assistant**: a cross-platform desktop
app that ingests papers, searches and analyses them, finds research gaps, and
helps you write LaTeX — all running locally with no cloud dependency.

- [Document ingestion](#document-ingestion)
- [Offline knowledge base](#offline-knowledge-base)
- [Hybrid search](#hybrid-search)
- [Analysis & gap finder](#analysis--gap-finder)
- [Local LLM inference](#local-llm-inference)
- [AI-assisted paper writer (LaTeX)](#ai-assisted-paper-writer-latex)
- [Paper encryption](#paper-encryption)
- [Hardware-aware model loading](#hardware-aware-model-loading)
- [Fine-tuning data collection](#fine-tuning-data-collection)
- [Auto-updates](#auto-updates)
- [Roadmap](#roadmap)
- [Known limitations](#known-limitations)

## Document ingestion

Turns a PDF into searchable, analysable knowledge.

- **Cascading PDF parser** — tries PyMuPDF (fast) first, falls back to pdfplumber
  for scanned or complex layouts.
- **Chunking** — splits text into overlapping chunks that respect paragraph and
  sentence boundaries, keeping page numbers via word-overlap scoring.
- **Metadata extraction** — pulls title, authors, abstract, and year via regex
  heuristics, with a small-language-model fallback for non-standard formatting.

## Offline knowledge base

- **Custom NumPy vector store** — embeddings and metadata are stored as JSON on
  disk with cosine-similarity search in NumPy. No external database (no ChromaDB,
  no server) — it just works offline for collections up to a few thousand chunks.
- **Local embeddings** — `sentence-transformers` (`all-MiniLM-L6-v2`), a 22M-param
  model that runs on the CPU (a 64-chunk batch embeds in ~0.2s).

## Hybrid search

Combines two complementary strategies and fuses them:

- **Semantic search** — cosine similarity over embeddings (meaning-based).
- **Keyword search** — BM25 token matching (exact-term based).
- **Reciprocal Rank Fusion (RRF)** — merges both ranked lists by rank position, so
  it's robust to the two methods' different score scales.

## Analysis & gap finder

- Single- and multi-paper comparative **summarization**.
- **Thematic clustering** across a set of papers.
- **Gap analysis** — surfaces contradictions, methodological gaps, and missing
  validation, then proposes actionable research directions.

## Local LLM inference

- **Dual runtime** — supports both `llama.cpp` (direct GGUF loading) and Ollama.
- **Structured output** — a GBNF grammar constrains `llama.cpp` output to strict
  JSON or LaTeX where the task needs it.
- **Task-based model routing** — light tasks (chat, search, paper writing) use a
  fast 0.5B model; structured-JSON analysis tasks route to a heavier 1.5B model
  that produces reliable JSON. Only one model is resident at a time; the runtime
  swaps on demand to cap memory.

## AI-assisted paper writer (LaTeX)

The most-loved feature: write ideas in plain language and get compilable LaTeX.

- **Editor** — a built-in editor inside the desktop app. Write prompts/ideas in a
  `.ths` (ThinkStack) file and the local model translates them in place to LaTeX.
- **Two-tab preview** — a client-side **Live Preview** (KaTeX renders sections,
  math, tables, and lists instantly as you type, no compile needed) alongside the
  real **Compiled PDF** tab (`pdflatex` output).
- **Auto-save** — saves incrementally ~2s after you stop typing; manual save too.
- **Auto-healing compiler** — this is what makes it robust. When compilation would
  fail it:
  - injects missing `\usepackage` lines the body needs (tikz, pgfplots, booktabs,
    …) — no more "Environment tikzpicture undefined";
  - wraps a bare AI snippet into a complete document;
  - isolates a single broken figure/table behind a placeholder so the rest of the
    paper still produces a PDF (Overleaf-style graceful degradation), and as a
    last resort neutralizes all figures rather than failing outright.
- **Error surfacing** — when a compile fails, the parsed `pdflatex` diagnostics
  (and missing-TeX-package install hints) show directly in the UI.

## Paper encryption

Optional password protection for a paper's text, done with modern authenticated
encryption:

- **Key derivation** — Argon2id turns your password into a 256-bit key, with a
  fresh random salt per paper (tuned to ~0.3–0.6s to resist brute force).
- **Cipher** — AES-256-GCM; decrypting with the wrong password fails loudly (the
  authentication tag check) rather than returning corrupted text.
- **Self-contained envelope** — everything needed to decrypt except the password
  travels in one versioned `TSENC1` string (KDF params + salt + nonce +
  ciphertext), so an encrypted paper is portable and future-proof.

## Hardware-aware model loading

ThinkStack sizes itself to the machine it runs on.

- On launch the native Tauri shell runs a **hardware diagnosis** (RAM, CPU, GPU
  via `nvidia-smi` under a timeout) and hands it to the backend — so the app never
  has to import heavy ML libraries just to detect hardware.
- **Specification-based model selection** — a heavier model is loaded only if it
  fits the available-RAM budget (with headroom reserved for your other running
  apps); otherwise it gracefully downgrades to a lighter model instead of running
  out of memory.
- **CPU-only by default** — runs on any machine with no GPU drivers. GPU offload
  is used automatically when a usable CUDA GPU is present, with a CPU fallback on
  out-of-memory.
- You can **change the active model** yourself; the choice persists across
  restarts.

**Optional NVIDIA acceleration (advanced).** The shipped build is CPU-only, which
is why AMD and Apple Metal are reported but not used for offload — attempting it
would fail at model load. To run analysis on an NVIDIA GPU from a source
checkout, install the CUDA build and repair the two DLL issues the prebuilt wheel
has on toolkit-less machines:

```bash
pip install llama-cpp-python \
  --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124
python tools/fix_gpu_dlls.py   # installs CUDA runtime DLLs, swaps a compatible CPU backend
python tools/verify_gpu.py     # prints tokens/sec and confirms offload
```

`fix_gpu_dlls.py` is idempotent — re-run it after any reinstall of
llama-cpp-python. Set `THINKSTACK_LLM_GPU_LAYERS=-1` to force full offload, or
`0` to force CPU.

### Reusing models you already have

If you already run **Ollama** or **LM Studio**, ThinkStack finds those models and
uses them instead of downloading its own copy. Nothing is ever fetched that your
machine already stores.

This matters because every runtime names the same weights differently:

| Where it came from | What it's called |
|--------------------|------------------|
| Ollama | `qwen2.5:1.5b` |
| LM Studio | `Qwen2.5-1.5B-Instruct-Q4_K_M.gguf` |
| ThinkStack | `qwen2.5-1.5b-instruct-q4_k_m.gguf` |

All three are the same model. ThinkStack reduces them to a canonical
`family/size` key (`qwen2.5/1.5b`) so they compare equal, then loads the copy you
already have. Quantisation is ignored on purpose — a `q4` and a `q8` of the same
model do the same job here, and re-downloading one because you have the other is
exactly the waste this avoids.

Models are discovered from ThinkStack's own directory, a running Ollama server,
Ollama's on-disk store (so it works even when Ollama isn't running), and LM
Studio. Every probe is optional and independently guarded: a missing tool or an
unreadable directory simply finds nothing, and never delays startup.

## Fine-tuning data collection

- Every AI generation passively logs a prompt→output training pair as JSONL under
  `data/training/`, in chat format (system/user/assistant), ready for future
  QLoRA fine-tuning.
- Separate datasets for `latex_generation` and `gap_analysis`. It's privacy-safe:
  the data stays on your device and never leaves it.

## Auto-updates

Installed apps check a signed manifest on launch and can update themselves in
place — no manual re-download. Three channels exist: **stable** (everyone),
**beta**, and **nightly** (opt-in testers). See [../scripts/README.md](../scripts/README.md).

## Roadmap

Planned and in-progress work:

- **Feature-specific SLMs on CPU** — quantized small models downloaded and
  selected based on the user's hardware (the hardware-aware loading above is the
  foundation for this).
- **Federated cloud fine-tuning** — train QLoRA adapters on cloud GPUs, then sync
  tiny `.gguf` adapters down to apply over the local base model.
- **Bundled Tectonic** — ship a self-contained TeX engine so the paper writer
  needs no system `pdflatex` install.
- **Secure P2P sharing** — share papers/drafts/analysis directly with specific
  peers via libp2p + public-key signatures, no central server.
- **Citation visualization** — a graph of how papers cite one another, surfacing
  foundational papers and research clusters.

## Known limitations

- **BM25 rebuild per query** — the keyword index is built from scratch each search.
  Fine for a small corpus; a bottleneck as the document count grows.
- **LaTeX needs system `pdflatex`** — a full TeX install must be on `PATH` until
  Tectonic is bundled. A missing `pdflatex` fails gracefully with a clear message.
- **Live preview scope** — the instant client-side preview handles common paper
  elements but not TikZ diagrams, complex tables, or custom macros; those render
  only in the Compiled PDF tab.
- **Ollama JSON retries** — GBNF makes `llama.cpp` output reliable, but there's no
  extensive retry logic if the optional Ollama runtime returns malformed JSON.
