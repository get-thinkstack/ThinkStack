# Rithesh: contributions

A record of the parts of ThinkStack I worked on, written mainly so the rest of
the team (and future me) can find the reasoning behind the decisions.

## Paper writer

Scribe is the LaTeX side of the app: an editor, an AI draft helper, a
compiler, and a live preview. The pieces I own:

- `domain/paper_writer/compiler.py`: the pdflatex wrapper. It parses compiler
  errors, injects missing packages, and degrades gracefully, so a broken figure
  or table still produces a PDF instead of failing the whole document.
- `api/routes_papers.py`: the project endpoints (create, read, save, generate,
  compile, download, delete).
- `frontend/src/components/Scribe.jsx`: the editor, the AI prompt bar, and
  the preview tabs.
- `frontend/src/components/LatexPreview.jsx`: a client-side LaTeX-to-HTML
  renderer that uses KaTeX for math, so the "Live Preview" tab updates as you
  type without waiting on a compile. The "Compiled PDF" tab shows the real
  pdflatex output.

## Fine-tuning data pipeline

`domain/fine_tuning/data_collector.py` records every prompt-to-LaTeX pair a
generate call produces, as JSONL under `data/training/`. Nothing consumes it
yet; the intent is to have a dataset ready if we later fine-tune a small model
for the LaTeX and gap-analysis tasks.

## Desktop app and packaging

The desktop shell is Tauri (`src-tauri/`). `src/lib.rs` starts the Python
backend, waits for it to come up behind a loading screen, and shuts it down when
the window closes. In a packaged build the backend is a PyInstaller onedir
bundle shipped as a Tauri resource; in development it falls back to running
uvicorn from the project venv.

Two packaging corrections are worth recording:

- The build freezes the backend with `--onedir`, not `--onefile`. A onefile
  build re-extracts its multi-gigabyte payload to a temp directory on every
  launch; onedir unpacks once at install and matches how `tauri.conf.json`
  bundles the backend as the `api/` resource.
- PyInstaller needs `--collect-all llama_cpp` and `--collect-all
  sentence_transformers`. Neither ships a PyInstaller hook, so without those
  flags the frozen build silently drops llama.cpp's shared libraries and the
  embedding model's data. I confirmed the fix by building a frozen backend
  locally and running ingest, search, and chat against it.

## Model bundling and routing

The installer bundles one model - a 0.5B for chat, search, and Scribe.
The 0.5B is fast and light but produces malformed JSON on the structured-output
tasks (summarize, claims, gap-finder), so those route to a 1.5B when one is
available; it is fetched on consent or reused from an existing Ollama/LM Studio
install rather than shipped, which kept installers clear of GitHub's 2 GiB asset
limit. Analysis degrades to the 0.5B when no larger model is present.

To keep memory bounded, `ollama_client.py` keeps only one model resident at a
time and swaps on demand rather than holding both.
`file_manager.seed_bundled_models()` copies the bundled model into the
writable data directory on first run, since a frozen build ships it read-only.

## Machine capability and diagnosis

`infrastructure/capability.py` is the single place that answers "what can this
machine do". Before it, that question was answered in about ten places, and two
of them disagreed: `src-tauri/src/diagnosis.rs` classified the machine and chose
GPU layers, `infrastructure/hardware.py` did the same again in Python, and the
Rust answer won at runtime -- so the Python one was unreachable code that still
looked authoritative.

The split is now Rust detects, Python decides. Rust reports facts about the
machine; every derived number -- tier, context size, GPU layers, output tokens,
how much prompt fits -- comes from `capability.py`. Callers ask it; they no
longer compute.

Two bugs this fixed:

- **Summarization could not fit in its own context window.** 6000 characters of
  paper (~1500 tokens) plus 1024 tokens of reply needs ~2650 tokens; a low-tier
  machine is given 2048. The request failed before the model was asked to think,
  and the error handler then told the reader the response "could not be read",
  which was untrue. Nobody owned the arithmetic, so nobody noticed it was wrong.
  Both summarizers now size the prompt from the context the model was actually
  loaded with, and fall back to map-reduce when a paper will not fit in one pass.
- **Every Mac was pinned to CPU.** GPU layers were decided by
  `has_cuda && vram_gb >= 2.0`. Apple Silicon reports no CUDA and 0 GB of
  dedicated VRAM -- both true, because its GPU shares system memory -- so the
  test could never pass whatever the machine could do. `HardwareProfile` could
  not express "unified memory", so three consumers each guessed and all three
  guessed wrong. Capability asks `llama_supports_gpu_offload()` instead: a fact
  about the binary we shipped, which is the only thing that decides whether
  offload works.

Detection no longer imports torch. Torch is bundled for embeddings, not
inference -- the SLMs run on llama.cpp -- and torch having CUDA says nothing
about our llama.cpp build. `nvidia-smi` and the platform answer the same
question in 0.18s rather than 0.82s.

`POST /api/system/diagnose` re-examines the machine on request, behind the
**Diagnose my machine** button. The profile is cached at startup, which is
right -- hardware does not change while the app runs -- but a user who frees
memory, or who upgraded from a build predating this, had no way to make the app
look again. The button is that way. It reads the local machine, sends nothing,
and changes no setting, so the click is the consent.

`tests/test_capability.py` covers it against fabricated machines rather than
real ones, so an 8 GB M1 and a 64 GB workstation are both testable on CI with no
GPU present.

## CI/CD and auto-updates

the release pipeline is config-driven and split into reusable workflows:
`release.config.json` holds the repo, platform matrix, channels, and models;
`.github/workflows/_build-desktop.yml` and `_publish-release.yml` are reusable
(`workflow_call`) and hold all the build/publish logic; and the thin channel
callers `release-stable.yml`, `release-beta.yml`, and `nightly.yml` trigger them
for the stable / beta / nightly channels. each builds installers for Linux,
macOS, and Windows and publishes them to GitHub Releases. Updates use Tauri's
updater: the installed app checks a signed `latest.json` on each launch and
installs a newer version if one exists (each channel has its own manifest URL).
The signing key stays out of the repo (the private key lives at `~/.tauri` and as
a CI secret; only the public key is committed). The supporting scripts are
`scripts/compose-updater-manifest.sh`, which builds the manifest, and
`scripts/release.sh`, which bumps the version and tags the release. See
[../ADR.md](../ADR.md) for the decisions and [../../scripts/README.md](../../scripts/README.md)
for the runbook.

## Model discovery and reuse

`domain/model_manager/` decides which model the app uses and whether it needs to
fetch anything. The baseline 0.5B ships inside the installer so a fresh install
works offline immediately; heavier models are optional and only fetched with
explicit consent (`api/routes_models.py`).

The part worth recording is the matching. **Aditya spotted that a model the user
already had could be downloaded again**, and the cause was that we compared
filenames. Every runtime names the same weights differently:

    ollama      qwen2.5:1.5b
    lm studio   Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
    ours        qwen2.5-1.5b-instruct-q4_k_m.gguf

so a copy pulled through Ollama never matched our catalog entry and we offered a
1.1 GB download for weights already on disk. No OS blocks that — it would have
silently succeeded and wasted the space. `discovery.model_key()` now reduces all
of them to a canonical `family/size` (`qwen2.5/1.5b`), ignoring quantisation
since a q4 and a q8 are the same capability here.

`ollama_client._find_external_model()` closes the other half: the loader used to
look only in our own directory, so an analysis task degraded to the base model
even when the right weights sat in LM Studio's folder. It now loads that copy
instead.

## Backend reconciliation

When merging the backend branches, `infrastructure/ollama_client.py` arrived in
a state that would not import, and `routes_gaps.py` had a duplicated keyword
argument. I reconciled the client into a single working version and kept the
useful infrastructure from the other branch (frozen-build paths, `.env` support,
the `max_tokens` caps, and the onedir packaging) rather than taking it as-is.

## Scripts, tests, and docs

- `scripts/` holds the devops scripts only (bootstrap, run, build, validate,
  release); non-devops utilities moved to `tools/`. See `scripts/README.md`.
- `tests/` is the automated `pytest` suite (run `pytest`), gated in CI by
  `.github/workflows/ci.yml`. `tools/test_paper_writer.py` remains as a manual
  end-to-end paper-writer integration check (real pdflatex compile).
- `scripts/README.md` is the runbook for cutting a release and for how
  downloads and updates work. I also maintain the landing page (`landing.html`)
  and the ADR entries for the decisions above.
