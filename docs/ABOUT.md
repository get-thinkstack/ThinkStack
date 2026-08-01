# About ThinkStack

ThinkStack is an **offline, edge-AI research assistant** for your desktop. It
ingests research papers, lets you search and analyse them, finds gaps in the
literature, and helps you write LaTeX — all running **locally on your machine**,
with no account, no cloud, and no internet required after install.

If you've ever wanted a private "chat with my papers" that also drafts LaTeX and
never sends your work to someone else's server, that's ThinkStack.

For the full feature reference, see [FEATURES.md](FEATURES.md).

## Current release and stack

<!-- These values are maintained by scripts/update_docs.py (the Sync doc facts
     workflow). Only the text between the markers is rewritten -- edit the
     surrounding sentences freely. Do not hand-edit the numbers: they will be
     overwritten on the next push, and they were wrong before this was
     automated (the docs claimed 1.0.0 while 1.6.10 was shipping). -->

| | |
|---|---|
| Latest release | **v<!-- autodoc:version -->1.6.11<!-- /autodoc -->** |
| Desktop shell | Tauri <!-- autodoc:tauri -->2<!-- /autodoc --> (Rust, edition <!-- autodoc:rust_edition -->2021<!-- /autodoc -->) |
| Interface | React <!-- autodoc:react -->19.2.6<!-- /autodoc -->, built with Vite <!-- autodoc:vite -->8.0.12<!-- /autodoc --> |
| Backend | Python <!-- autodoc:python -->3.12<!-- /autodoc --> (FastAPI) |
| Build toolchain | Node <!-- autodoc:node -->22<!-- /autodoc --> |

## Why offline / on-device?

- **Privacy** — your papers, drafts, and analysis never leave your computer.
- **No running cost** — no API keys, no subscription; the models run locally.
- **Works anywhere** — on a plane, behind a firewall, or on a lab machine with no
  internet, it keeps working.

## Installing

Download the installer for your OS from the releases page (or the landing page's
Download button, which auto-detects your OS).

| OS | File | How to install |
|----|------|----------------|
| **macOS** | `ThinkStack_<v>_universal.dmg` | Open the `.dmg`, drag ThinkStack to Applications. macOS will refuse the first launch (see below). |
| **Windows** | `ThinkStack_<v>_x64-setup.exe` (or `.msi`) | Run it. If SmartScreen warns, click **More info → Run anyway** (one-time, unsigned build). |
| **Linux** | `ThinkStack_<v>_amd64.AppImage` | `chmod +x` it and double-click. Or install the `.deb` / `.rpm` for a menu entry. |

### macOS: "Apple could not verify ThinkStack is free of malware"

ThinkStack is not yet **notarized** — that requires a paid Apple Developer
account, which this project does not have. macOS therefore blocks the first
launch. The app is unmodified; macOS simply has no Apple signature to check.

On **macOS 15 (Sequoia) and newer**, the old right-click → Open trick no longer
works. Do this instead:

1. Try to open ThinkStack. Let macOS refuse.
2. Open **System Settings → Privacy & Security**.
3. Scroll to Security. You will see *"ThinkStack was blocked…"* — click
   **Open Anyway**, then confirm.

On **macOS 14 and earlier**, right-click the app → **Open** → **Open** works.

Either way it is a one-time step. If you prefer the terminal:

```bash
xattr -d com.apple.quarantine /Applications/ThinkStack.app
```

### Windows: SmartScreen

Same cause — the build is unsigned. Click **More info** → **Run anyway**. One
time only.

Everything the app needs to work — the backend, the interface, and an AI model —
is in the installer, so it runs offline the moment it opens.

Two things it does **not** bundle:

- **A larger analysis model.** The built-in model handles chat, search and the
  paper writer well. Summaries and gap analysis are noticeably better on a bigger
  model, so on a machine with room to spare the app *offers* to fetch one on
  first run. Decline and everything still works — analysis just uses the built-in
  model. If you already run Ollama or LM Studio, ThinkStack uses a model you
  already have instead of downloading anything.
Nothing else is needed. The installer also carries a **TeX engine**, so the
paper writer compiles PDFs on a machine with no LaTeX installed.

The app also **updates itself**: when a new version is released, it offers to
install it on the next launch. Opt-in **beta** and **nightly** channels are
available for testers.

## First run

1. **Open the app.** On first launch it checks your hardware — RAM, CPU, and GPU
   — and picks a model that fits your machine's memory, leaving headroom for
   whatever else you're running. If your machine can comfortably run a better
   model than the built-in one, it asks once whether to download it; you can
   decline and never be asked again.
2. **Add papers.** Import PDFs — ThinkStack parses them, extracts the metadata
   (title, authors, abstract, year), and indexes them into its local knowledge
   base.
3. Now you can search, analyse, and write.

## Using the features

### Search your library
Ask a question or type keywords. ThinkStack runs **semantic** search (by meaning)
and **keyword** search (BM25) together and fuses the results, so you get relevant
chunks whether you remember the exact wording or just the idea.

### Summarize & find gaps
Pick one or more papers to get a comparative **summary** and **thematic
clusters**. The **gap finder** goes further: it points out contradictions,
methodological gaps, and missing validation across the papers, and suggests
concrete research directions.

### Write LaTeX (the paper writer)
Open the paper writer and write your ideas in plain language in a `.ths` file. The
local model turns them into compilable LaTeX **in place**. You get:
- a **Live Preview** tab that renders sections, math, and tables instantly as you
  type (no compile needed), and
- a **Compiled PDF** view, produced by the TeX engine shipped with the app.

It auto-saves as you go, and the compiler **auto-heals** common problems — missing
packages, bare snippets, a broken figure — so you still get a PDF instead of a
wall of errors.

### Protect a paper
You can encrypt a paper's text with a password (Argon2id + AES-256-GCM). Only
someone with the password can read it back; a wrong password fails cleanly.

### Change the model
ThinkStack auto-selects a model for your hardware, but you can switch to a
different local model yourself — your choice is remembered across restarts.

## Where your data lives

Everything stays on your device: imported PDFs, the vector index, your paper
projects, and any training pairs collected for future fine-tuning. Nothing is
uploaded. On a packaged build this lives in your OS's application-data directory;
from a source checkout it's under the project's `data/` folder.

## Getting help / contributing

- Feature details: [FEATURES.md](FEATURES.md)
- Cutting a release / how updates work: [../scripts/README.md](../scripts/README.md)
- Design decisions and rationale: [ADR.md](ADR.md)
