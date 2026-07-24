# Rithesh: contributions

A record of the parts of ThinkStack I worked on, written mainly so the rest of
the team (and future me) can find the reasoning behind the decisions.

## Paper writer

The paper writer is the LaTeX side of the app: an editor, an AI draft helper, a
compiler, and a live preview. The pieces I own:

- `domain/paper_writer/compiler.py`: the pdflatex wrapper. It parses compiler
  errors, injects missing packages, and degrades gracefully, so a broken figure
  or table still produces a PDF instead of failing the whole document.
- `api/routes_papers.py`: the project endpoints (create, read, save, generate,
  compile, download, delete).
- `frontend/src/components/PaperWriter.jsx`: the editor, the AI prompt bar, and
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

The app bundles two models: a 0.5B for chat, search, and the paper writer, and a
1.5B for the analysis tasks (summarize, claims, gap-finder). The 0.5B is fast
and light but produces malformed JSON on the structured-output tasks, which is
why those route to the larger model. To keep memory bounded, `ollama_client.py`
keeps only one model resident at a time and swaps on demand rather than holding
both. GPU is used when available, with a CPU fallback so the app still runs on
machines without a usable CUDA setup. `file_manager.seed_bundled_models()`
copies the bundled models into the writable data directory on first run, since a
frozen build ships them read-only.

## CI/CD and auto-updates

`.github/workflows/build-release.yml` builds installers for Linux, macOS, and
Windows on a version tag and publishes them to GitHub Releases. Updates use
Tauri's updater: the installed app checks a signed `latest.json` on each launch
and installs a newer version if one exists. The signing key stays out of the
repo (the private key lives at `~/.tauri` and as a CI secret; only the public
key is committed). The supporting scripts are
`scripts/compose-updater-manifest.sh`, which builds the manifest, and
`scripts/release.sh`, which bumps the version and tags the release.

## Backend reconciliation

When merging the backend branches, `infrastructure/ollama_client.py` arrived in
a state that would not import, and `routes_gaps.py` had a duplicated keyword
argument. I reconciled the client into a single working version and kept the
useful infrastructure from the other branch (frozen-build paths, `.env` support,
the `max_tokens` caps, and the onedir packaging) rather than taking it as-is.

## Scripts, tests, and docs

- `scripts/setup.sh`, `scripts/dev.sh`, `scripts/build.sh`, `scripts/validate.sh`:
  bootstrap, run, build, and pre-commit checks.
- `scripts/test_paper_writer.py`: unit and integration tests for the compiler
  and the paper API.
- `docs/RELEASE_GUIDE.md` is the single guide for cutting a release and for how
  downloads and updates work. I also maintain the landing page (`landing.html`)
  and the ADR entries for the decisions above.
