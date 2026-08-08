<div align="center">

# ThinkStack

**An offline research assistant that runs entirely on your machine.**

Ingest papers, search them, analyse them, map them, and write LaTeX.
No account, no subscription, no network. Nothing you open ever leaves your computer.

Three sections, in the order the work happens:
**Library** (collect) → **LitGraph** (understand) → **Scribe** (write), with
**Bench** for what your machine can run and what it runs it with.

[![Release](https://img.shields.io/github/v/release/get-thinkstack/ThinkStack?label=release&color=95ff00)](https://github.com/get-thinkstack/ThinkStack/releases/latest)
[![CI](https://img.shields.io/github/actions/workflow/status/get-thinkstack/ThinkStack/ci.yml?branch=main&label=CI)](https://github.com/get-thinkstack/ThinkStack/actions)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey)](https://github.com/get-thinkstack/ThinkStack/releases/latest)
[![Python](https://img.shields.io/badge/python-3.12-3776AB)](requirements.txt)
[![Offline](https://img.shields.io/badge/inference-100%25%20local-success)](#privacy)

[Download](https://get-thinkstack.github.io/ThinkStack/) ·
[User guide](docs/ABOUT.md) ·
[Features](docs/FEATURES.md) ·
[Contributing](CONTRIBUTING.md) ·
[Architecture decisions](docs/ADR.md)

</div>

---

## What it is

ThinkStack is a desktop application for students and independent researchers
working with a personal library of research papers. It runs as a native desktop
window, or as a local server you open in your own browser. Either way it is bound
to `127.0.0.1` and hosted nowhere.

Language model inference, text embedding, retrieval, encryption and PDF
typesetting all happen locally. The installer carries everything needed: a frozen
Python runtime, a quantised language model, embedding weights, and a TeX engine.

**Install it on a computer with nothing else on it, disconnect the network, and
every feature still works.**

## Features

| | |
|---|---|
| **Ingest** | PDF extraction with PyMuPDF and pdfplumber, sentence-transformer embeddings, file-based vector store |
| **Search** | dense semantic retrieval across every chunk of every paper, with a small exact-token bonus so rare literal terms stay findable |
| **LitGraph** | a map of your collection: papers placed by meaning (PCA over embedding centroids), linked by similarity, grouped into theme territory, with research gaps drawn as markers wired to the papers that evidence them. The map is also the selector — lasso a region and run summarize, claims, themes or gap-finding on exactly those papers |
| **Analyse** | summaries, key-claim extraction, thematic clustering — precomputed at ingest, off the request path |
| **Gap finder** | surfaces under-explored areas and suggests research directions |
| **Scribe** | AI-assisted LaTeX. A paper is a folder — add figures, split it into sections, keep a `.bib` beside it. Select plain English, press `Ctrl+Enter`, and it becomes LaTeX at your cursor. Compiles locally with no account, no queue and no time limit |
| **Vault** | password-based encryption with Argon2id and AES-256-GCM |
| **Updates** | signed, and only when you ask for them |

## Privacy

This is the reason the project exists, so it is worth being exact about.

- **No inference leaves the device.** Models run through `llama.cpp` on your CPU.
- **No embeddings leave the device.** Sentence encoding is local.
- **No telemetry.** None is collected or sent.
- **No update check on launch.** The only outbound request the application ever
  makes is an update check, and it happens only when you press the button. An
  offline-first application that contacts a server on every start is not offline
  in any sense a user would recognise.

## Install

Download from the [releases page](https://github.com/get-thinkstack/ThinkStack/releases/latest)
or the [download page](https://get-thinkstack.github.io/ThinkStack/).

| OS | File | Note |
|---|---|---|
| **Linux** | `.AppImage` or `.deb` | `chmod +x` the AppImage, then run it |
| **macOS** | `.dmg` | unsigned build: **System Settings → Privacy & Security → Open Anyway** on first launch |
| **Windows** | `.msi` | unsigned build: SmartScreen → **More info** → **Run anyway** |

Builds are not code-signed yet, so both macOS and Windows warn once on first
launch. See [docs/ABOUT.md](docs/ABOUT.md) for the full walkthrough.

## What ships inside the installer

| Component | Size | Purpose |
|---|---|---|
| Frozen Python backend | ~1.7 GB uncompressed | no Python needed on the machine |
| Qwen2.5 0.5B Instruct (Q4_K_M) | 469 MB | general tasks, metadata, Scribe |
| all-MiniLM-L6-v2 | 88 MB | embeddings for ingestion and search |
| Tectonic + warmed package cache | 70 MB | LaTeX compilation with no TeX install |

**Graphics acceleration is not bundled either.** The inference engine ships
processor-only so the installer works on every machine. If yours has graphics
hardware ThinkStack can use — NVIDIA, AMD, Intel or integrated, via Vulkan —
Bench offers to add the ~90 MB graphics engine on request. Your graphics driver
is already installed and is never downloaded.

A larger model improves analysis quality. None of these are bundled:
the application offers it once, only if your machine can run it, and reuses a
copy you already have through Ollama or LM Studio rather than downloading again.

## Build from source

```bash
git clone https://github.com/get-thinkstack/ThinkStack.git && cd ThinkStack
./scripts/setup.sh          # system deps, rust, python venv, node
./scripts/install-hooks.sh  # shared git hooks
./scripts/fetch-tex.sh      # the TeX engine the installers bundle

mkdir -p data/models
huggingface-cli download Qwen/Qwen2.5-0.5B-Instruct-GGUF \
  qwen2.5-0.5b-instruct-q4_k_m.gguf --local-dir data/models

./scripts/dev.sh            # backend + vite with hot reload
./scripts/dev.sh --tauri    # ... plus the desktop window
./scripts/build.sh          # production installers, into local/
```

**Requirements:** Python 3.11+, Node 18+, Rust (desktop build only).

## Architecture

```text
main.py            fastapi app: serves the react spa and /api
config.py          pydantic-settings config (env prefix: THINKSTACK_)
api/               12 routers
domain/            ingestion · knowledge_base · search · litgraph · analysis
                   gap_finder · paper_writer · encryption · model_manager
                   fine_tuning
infrastructure/    llm client · vector store · hardware profiler · file manager
                   background job queue
frontend/          react 19 + vite spa
src-tauri/         tauri 2 desktop shell (rust): diagnosis, supervision, updates
scripts/           devops: setup, dev, preflight, build, promote, release
tests/             839 tests across 41 modules
```

The desktop shell diagnoses the machine, launches the backend as a supervised
child process, and reports startup progress. Only one model is resident at a
time; the runtime swaps on demand and sizes models against *available* memory,
so analysis degrades gracefully rather than exhausting the machine.

## Quality gates

Every build validates the **packaged installer**, not just the source, because
users run an installer.

| Tier | Runs on | Establishes |
|---|---|---|
| `preflight.sh` | your machine, every push | lint, 839 tests, shellcheck, actionlint, cargo |
| CI | every push | the same on a clean machine |
| `validate_bundle.py` | **Linux, macOS, Windows**, every build | the packaged app starts, resolves models, ingests a PDF, searches, infers, compiles a PDF, embeds a user-supplied figure, builds an index, and reports its graphics hardware coherently |
| GUI smoke test | Linux, every build | the launched application is still alive 45 seconds later |

## Documentation

| Document | For |
|---|---|
| [docs/ABOUT.md](docs/ABOUT.md) | users: install and use each feature |
| [docs/FEATURES.md](docs/FEATURES.md) | the detailed feature reference |
| [docs/FUTURE_WORK.md](docs/FUTURE_WORK.md) | what is planned, and how far off it is |
| [docs/ADR.md](docs/ADR.md) | every architecture decision, and why |
| [CONTRIBUTING.md](CONTRIBUTING.md) | setup, branches, releasing, beta testing |
| [scripts/README.md](scripts/README.md) | the devops runbook |
| [CHANGELOG.md](CHANGELOG.md) | what changed in each release |

## Tech stack

`Tauri 2` · `Rust` · `React 19` · `Vite` · `Python` · `FastAPI` · `llama.cpp` ·
`GGUF` · `sentence-transformers` · `PyMuPDF` · `NumPy` ·
`Tectonic` · `Argon2id` · `AES-256-GCM` · `PyInstaller`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Work happens on `dev`, is validated on
`beta`, and is released from `main`. Branches never build installers; tags do.

## License

[MIT](LICENSE). Third-party components redistributed inside the installer are
listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
