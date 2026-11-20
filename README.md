<div align="center">

# ThinkStack

**An offline research assistant that runs entirely on your machine.**

Collect papers, map what they say, and write LaTeX.
No account, no subscription, no cloud. Nothing you open leaves your computer.

**Library** (collect) → **LitGraph** (understand) → **Scribe** (write), plus
**Bench** for what your machine can run and which models it runs.

[![Release](https://img.shields.io/github/v/release/get-thinkstack/ThinkStack?label=release&color=95ff00)](https://github.com/get-thinkstack/ThinkStack/releases/latest)
[![CI](https://img.shields.io/github/actions/workflow/status/get-thinkstack/ThinkStack/ci.yml?branch=main&label=CI)](https://github.com/get-thinkstack/ThinkStack/actions)
[![License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)
[![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20macOS%20%7C%20Windows-lightgrey)](https://github.com/get-thinkstack/ThinkStack/releases/latest)
[![Offline](https://img.shields.io/badge/inference-100%25%20local-success)](#privacy)

[Download](https://get-thinkstack.github.io/ThinkStack/) ·
[Features](docs/FEATURES.md) ·
[Contributing](CONTRIBUTING.md) ·
[Decisions](docs/ADR.md)

</div>

---

## What it is

A desktop application for students and independent researchers with a personal
library of papers. It runs as a native window, or as a local server you open in
your own browser. Either way it binds to `127.0.0.1` and is hosted nowhere.

Embedding, search, language-model inference, encryption and PDF typesetting all
happen on the machine. The installer carries a frozen Python backend, the
embedding model and a TeX engine, so a fresh install with no network can ingest,
search, read and compile. **Language models are not bundled**: you choose one in
Bench after install, or point ThinkStack at one you already have (Ollama, LM
Studio, or any `.gguf` file). Summaries, claims, theme names, gap finding,
Scribe's "write at the cursor" and the metadata fallback need one; ingesting,
search, the map's layout, reading and compiling do not.

## Privacy

This is why the project exists.

- **Inference and embeddings run locally**, through `llama.cpp` and
  `sentence-transformers`.
- **No telemetry.**
- **The internet is used only when you ask:** pressing *Update app*, searching
  or downloading a model in Bench, or adding the optional graphics engine. There
  is no check on launch. An offline app that phones home on every start is not
  offline.

## Features

| | |
|---|---|
| **Library** | Import PDFs. Title, authors and year are read from the page layout and can be corrected by hand. |
| **Search** | Meaning-based retrieval over every chunk of every paper. |
| **LitGraph** | A map of the collection: papers placed by meaning, linked by similarity, grouped into themes, with research gaps wired to the papers that evidence them. Draw a loop around papers to summarize, extract claims, cluster or find gaps in exactly that set. |
| **Scribe** | A LaTeX editor that compiles offline. A paper is a folder. Select plain English, press `Ctrl+Enter`, and it becomes LaTeX at the cursor. Type `cite` to cite from the library. |
| **Bench** | What this machine can run, which model does which job, and where to get more. |
| **Vault** | Encrypt a paper's text and PDF at rest with a password (Argon2id + AES-256-GCM). It stays on the map; its contents need the password. |
| **Updates** | Signed, and only when you press the button. |

Details: [docs/FEATURES.md](docs/FEATURES.md).

## Install

Download from the [download page](https://get-thinkstack.github.io/ThinkStack/)
(it detects your OS) or the [releases page](https://github.com/get-thinkstack/ThinkStack/releases/latest).

| OS | File | First launch |
|---|---|---|
| Linux | `.AppImage` or `.deb` | `chmod +x` the AppImage, then run it |
| macOS | `.dmg` (universal) | drag to Applications, then see below |
| Windows | `.msi` | SmartScreen: **More info → Run anyway** |

Builds are not code-signed yet (that needs paid Apple and Windows certificates),
so macOS and Windows warn once. The app is unmodified; the OS has no signature
to check.

**macOS 15 (Sequoia) and newer:** open the app and let macOS refuse, then
**System Settings → Privacy & Security → Open Anyway**. On macOS 14 and earlier,
right-click the app → **Open** → **Open**. Or, from a terminal:

```bash
xattr -d com.apple.quarantine /Applications/ThinkStack.app
```

### First run

1. The desktop shell reads your hardware (memory, processor, graphics) and shows
   each startup step on the loading screen.
2. A one-time note points you at Bench. Pick a model there, or reuse one you
   already have. You can skip this; ingesting, searching, reading and compiling
   work without a model.
3. Add papers in Library, or open Scribe and start writing. Scribe needs no
   library.

### Where your data lives

Imported PDFs, the vector index, paper projects, Bench settings and collected
training pairs stay on your device. A packaged build keeps them in the OS
application-data directory; a source checkout keeps them in `data/`.

## Build from source

```bash
git clone https://github.com/get-thinkstack/ThinkStack.git && cd ThinkStack
./scripts/setup.sh          # system deps, rust, python venv, node
./scripts/install-hooks.sh  # shared git hooks
./scripts/fetch-tex.sh      # the TeX engine the installers bundle

./scripts/dev.sh            # backend + vite with hot reload
./scripts/dev.sh --tauri    # ... plus the desktop window
./scripts/build.sh          # production installers, into local/
```

Python 3.12 (what CI freezes with), Node, and Rust for the desktop build. Full
setup, branches and releasing: [CONTRIBUTING.md](CONTRIBUTING.md).

## Architecture

Three processes. The **Tauri shell** (Rust) diagnoses the hardware, starts the
**backend** (Python, FastAPI, frozen by PyInstaller) as a supervised child, and
hosts the **interface** (React + Vite) in a webview. The interface talks to the
backend over HTTP on `127.0.0.1`.

```text
src-tauri/        desktop shell: diagnosis, backend supervision, updater
main.py           FastAPI app: serves the built interface and mounts /api
config.py         settings (env prefix THINKSTACK_)
api/              HTTP routes, one router per feature; logic lives in domain/
domain/           the logic, one package per capability
  ingestion/        PDF -> text, layout, metadata, chunks
  knowledge_base/   embeddings and the chunk repository
  search/           semantic search and grounding
  litgraph/         the map: positions, edges, themes, gaps
  analysis/         summaries, claims, themes, precompute at ingest
  gap_finder/       gaps and suggested directions
  paper_writer/     Scribe: project folders, links, compiler, bibliography
  encryption/       Argon2id KDF, AES-GCM, the TSENC1 envelope
  model_manager/    registry, router, catalog, discovery, downloads
  fine_tuning/      passive collection of prompt -> output pairs
infrastructure/   things the domain stands on: LLM client, vector store,
                  hardware facts, Vulkan, acceleration, jobs, atomic I/O
frontend/         the Paper and Ink interface
scripts/          devops: setup, dev, preflight, build, release
tools/            developer utilities (GPU checks, fine-tuning, manual checks)
tests/            pytest suite
```

Only one language model is resident at a time; the runtime swaps on demand and
sizes models against *available* memory, so a big job degrades to a smaller
model instead of exhausting the machine.

## Documentation

| Document | Answers |
|---|---|
| [docs/FEATURES.md](docs/FEATURES.md) | what each feature does, and how |
| [docs/ADR.md](docs/ADR.md) | why it is built this way: every decision, dated |
| [ISSUES.md](ISSUES.md) | what is broken or unfinished, and what past failures taught |
| [docs/FUTURE_WORK.md](docs/FUTURE_WORK.md) | what is planned |
| [CONTRIBUTING.md](CONTRIBUTING.md) | setup, branches, tests, releasing, beta testing |
| [CHANGELOG.md](CHANGELOG.md) | what changed in each release |

## License

[MIT](LICENSE). Third-party components redistributed in the installer are listed
in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
