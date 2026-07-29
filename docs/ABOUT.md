# About ThinkStack

ThinkStack is an **offline, edge-AI research assistant** for your desktop. It
ingests research papers, lets you search and analyse them, finds gaps in the
literature, and helps you write LaTeX — all running **locally on your machine**,
with no account, no cloud, and no internet required after install.

If you've ever wanted a private "chat with my papers" that also drafts LaTeX and
never sends your work to someone else's server, that's ThinkStack.

For the full feature reference, see [FEATURES.md](FEATURES.md).

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
| **macOS** | `ThinkStack_<v>_universal.dmg` | Open the `.dmg`, drag ThinkStack to Applications. On first launch, right-click the app → **Open** (a one-time Gatekeeper prompt on unsigned builds). |
| **Windows** | `ThinkStack_<v>_x64-setup.exe` (or `.msi`) | Run it. If SmartScreen warns, click **More info → Run anyway** (one-time, unsigned build). |
| **Linux** | `ThinkStack_<v>_amd64.AppImage` | `chmod +x` it and double-click. Or install the `.deb` / `.rpm` for a menu entry. |

Everything the app needs — the AI models, the backend, the interface — is bundled
in the installer. The one thing it does **not** bundle yet is a TeX engine: to
compile LaTeX to PDF you need `pdflatex` on your system `PATH` (install TeX Live
or MiKTeX). The live preview works without it.

The app also **updates itself**: when a new version is released, it offers to
install it on the next launch. Opt-in **beta** and **nightly** channels are
available for testers.

## First run

1. **Open the app.** On first launch it detects your hardware and picks a model
   that fits your machine's memory (leaving headroom for your other apps), so it
   runs smoothly whether you have a dedicated GPU or not.
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
- a **Compiled PDF** tab showing the real `pdflatex` output.

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
