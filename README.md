<div align="center">

# ThinkStack

**An offline research assistant that runs entirely on your machine.**

Ingest papers, search them, analyse them, chat with them, and write LaTeX.
No account, no subscription, no network. Nothing you open ever leaves your computer.

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
| **Search** | dense semantic retrieval and BM25 keyword retrieval, combined by reciprocal rank fusion |
| **Analyse** | summaries, key-claim extraction, thematic clustering |
| **Gap finder** | surfaces under-explored areas and suggests research directions |
| **Chat** | a retrieval-grounded assistant over the papers you select |
| **Paper writer** | AI-assisted LaTeX. Select plain English, press `Ctrl+Enter`, and it becomes LaTeX at your cursor. The compiled PDF is the preview and rebuilds as you type |
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
| Qwen2.5 0.5B Instruct (Q4_K_M) | 469 MB | chat, search, paper writer |
| all-MiniLM-L6-v2 | 88 MB | embeddings for ingestion and search |
| Tectonic + warmed package cache | 70 MB | LaTeX compilation with no TeX install |

A larger 1.5B model improves analysis and LaTeX quality. It is **not** bundled:
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
api/               9 routers, <!-- autodoc:endpoints -->36<!-- /autodoc --> REST endpoints
domain/            ingestion · knowledge_base · search · analysis · gap_finder
                   chat · paper_writer · encryption · model_manager · fine_tuning
infrastructure/    llm client · vector store · hardware profiler · file manager
frontend/          react 19 + vite spa
src-tauri/         tauri 2 desktop shell (rust): diagnosis, supervision, updates
scripts/           devops: setup, dev, preflight, build, promote, release
tests/             <!-- autodoc:tests -->340 tests across 24 modules<!-- /autodoc -->
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
| `preflight.sh` | your machine, every push | lint, <!-- autodoc:test_count -->340<!-- /autodoc --> tests, shellcheck, actionlint, cargo |
| CI | every push | the same on a clean machine |
| `validate_bundle.py` | **Linux, macOS, Windows**, every build | the packaged app starts, resolves models, ingests a PDF, searches, infers, compiles a PDF |
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
`GGUF` · `sentence-transformers` · `PyMuPDF` · `rank_bm25` · `NumPy` ·
`Tectonic` · `Argon2id` · `AES-256-GCM` · `PyInstaller`

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Work happens on `dev`, is validated on
`beta`, and is released from `main`. Branches never build installers; tags do.

## License

[MIT](LICENSE). Third-party components redistributed inside the installer are
listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
