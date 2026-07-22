# release & bundling guide

how to cut a new ThinkStack desktop release: what ships, how the pipeline works,
the exact steps to run it locally or via CI, and what to update each time.
this is the reference for "how do we ship a build" — read it before tagging a release.

## what gets bundled

| piece | source | notes |
|---|---|---|
| frontend | `frontend/` → `frontend/dist/` (vite build) | served by fastapi, embedded in the desktop shell |
| backend | `main.py` + `api/` + `domain/` + `infrastructure/` | frozen to a single binary with PyInstaller |
| base model | `data/models/qwen2.5-0.5b-instruct-q4_k_m.gguf` | the **only** model baked into the installer (see below) |
| desktop shell | `src-tauri/` | Tauri 2 (Rust); starts/supervises the backend as a sidecar |

### why only the 0.5B model ships

CI used to download and bundle both Qwen2.5-0.5B and Qwen2.5-1.5B into every
installer. As of 2026-07-22 only the **0.5B** model (`qwen2.5-0.5b-instruct-q4_k_m.gguf`,
~470 MB) is bundled:

- keeps the installer small and the download fast
- keeps idle RAM/VRAM footprint low so the app doesn't strain low-end machines
- users who want better quality can drop a larger GGUF (1.5B, 4B, ...) into
  `data/models/` themselves and select it as the active model — see the
  "download a model" section in [README.md](../README.md)

If you want to change the default bundled model, update it in **three** places
(all three must agree or the installer/download page will be wrong):

1. `.github/workflows/build-release.yml` → the "Download Qwen2.5 base model" step
2. `scripts/build.sh` → nothing to change here, it bundles whatever is in `data/models/`
3. `README.md` → "download a model" section

## the pipeline (4 steps)

`scripts/build.sh` runs all four; each is skippable for iterating:

1. **frontend build** — `npm --prefix frontend run build` → `frontend/dist/`
2. **freeze backend** — `pyinstaller` freezes `main.py` (+ `frontend/dist`, + `data/models/*.gguf`
   if present) into `dist/thinkstack-api` (one file, one binary)
3. **place sidecar** — copies `dist/thinkstack-api` to
   `src-tauri/bin/thinkstack-api-<target-triple>` (Tauri's naming convention for
   `externalBin` sidecars — it picks the right one for the host at runtime)
4. **compile desktop app** — `npm run tauri build` produces the final installers
   under `src-tauri/target/release/bundle/` (`.deb`/`.rpm`/`.AppImage` on Linux,
   `.dmg` on macOS, `.msi`/`.exe` on Windows)

```bash
./scripts/build.sh                     # full pipeline
./scripts/build.sh --skip-pyinstaller  # reuse dist/thinkstack-api, just rebuild tauri
./scripts/build.sh --skip-tauri        # stop after freezing the backend
```

## building locally

A local build only produces installers for **your current OS/arch** (a Linux
machine cannot cross-compile a `.msi` or `.dmg`). Use this to sanity-check a
change before pushing a tag; use CI (below) for the full cross-platform matrix.

```bash
mkdir -p data/models
huggingface-cli download Qwen/Qwen2.5-0.5B-Instruct-GGUF \
  qwen2.5-0.5b-instruct-q4_k_m.gguf --local-dir data/models

source "$HOME/.cargo/env"   # if rust was installed this session
./scripts/build.sh
```

Install and smoke-test the result before tagging:

```bash
# Debian/Ubuntu
sudo dpkg -i src-tauri/target/release/bundle/deb/ThinkStack_*.deb
# or run the AppImage directly, no install needed
chmod +x src-tauri/target/release/bundle/appimage/ThinkStack_*.AppImage
./src-tauri/target/release/bundle/appimage/ThinkStack_*.AppImage
```

### ⚠️ memory during the build — read this before running on a dev laptop

A Tauri release build (`cargo build --release`) links large binaries and can
spike RAM well beyond what `cargo check`/`rust-analyzer` uses. Combined with an
LLM loaded at runtime, this **has caused OOM/thrashing risk** on a 16 GB dev
machine when other heavy tools were also running. Before building:

- **check `free -h` first.** if "available" is under ~6 GB, free memory before
  building — don't just start it and hope.
- **close redundant tooling.** running two IDEs on this repo at once (e.g. VS
  Code *and* another editor) means two separate `rust-analyzer` instances
  indexing the same Rust project — each can hold 2GB+. keep one.
- **don't build and run a model-loaded instance of the app at the same time**
  if you're tight on RAM — finish the `cargo build`, then launch the built app.
- if you're still tight, cap cargo's parallelism: `CARGO_BUILD_JOBS=4 ./scripts/build.sh`
  (default is one job per core, which maximizes peak memory on multi-core
  laptops during linking).

## cutting a release (CI matrix — Linux + macOS + Windows)

`.github/workflows/build-release.yml` already does the cross-platform matrix
build (3 runners) and drafts a GitHub Release. To trigger it:

```bash
# 1. bump the version everywhere it's hardcoded (see checklist below)
# 2. commit those bumps
git tag v0.2.0
git push origin v0.2.0     # pushing the tag triggers the workflow
```

Or trigger a dry run (build artifacts, no release published) from the Actions
tab: **workflow_dispatch** → leave "Create a GitHub Release" unchecked.

**Pushing a tag is a shared, remote action** — it kicks off CI on GitHub and,
on success, publishes a public release. Don't do it as a side effect of an
unrelated change; confirm with whoever owns the repo state first if you're
not sure the tag is ready.

### version bump checklist

these are not derived from one source of truth today — bump all of them together:

- [ ] `src-tauri/tauri.conf.json` → `"version"`
- [ ] `landing.html` → `const VERSION = '...'` (download link wiring script, near the bottom)
- [ ] `docs/landing/index.html` → `const VERSION = '...'` (same pattern, if this page is still in use)
- [ ] tag pushed matches, e.g. `tauri.conf.json` version `0.2.0` → tag `v0.2.0`

### after the release publishes

Verify the actual asset filenames match what the landing page expects:

```
https://github.com/Rithesh077/ThinkStack/releases/latest
```

Tauri's bundler names files as `ThinkStack_<version>_<arch>.<ext>` — e.g.
`ThinkStack_0.1.0_amd64.deb`, `ThinkStack_0.1.0_universal.dmg`,
`ThinkStack_0.1.0_x64-setup.exe`, `ThinkStack_0.1.0_x64_en-US.msi`. If a
filename ever differs (Tauri version bump can change bundler conventions),
update the `DOWNLOAD_LINKS`/`LINKS` map in the landing page's `<script>` block.

## the landing page(s)

There are currently **two** landing pages with download-link wiring — this is
duplication, not intentional redundancy:

- `landing.html` (repo root) — the fuller marketing page; **this is the one
  intended for deployment** as of 2026-07-22 (see [ADR.md](ADR.md)). Not yet
  hosted anywhere; hosting comes after the app has been tested end-to-end.
- `docs/landing/index.html` — a simpler download-only page, originally built
  for GitHub Pages `/docs` deployment. Left as-is for now; consolidate or
  delete once `landing.html` is confirmed as the sole page going forward.

Both wire `href`s at runtime via a small script keyed off `REPO`/`VERSION`
constants — update `VERSION` in whichever page(s) are live, per the checklist
above.

## troubleshooting

- **`cargo: command not found`** — `source "$HOME/.cargo/env"`, or install rust
  via `./scripts/setup.sh`.
- **model download drops partway through (HTTP/2 stream reset)** — Hugging
  Face's CDN can reset large transfers. Retry with `curl -L --http1.1 -C - ...`
  (forces HTTP/1.1, resumes from where it stopped) rather than restarting from
  zero. Always verify the final size against the remote `Content-Length`
  before trusting the file — a truncated `.gguf` will fail to load (or worse,
  crash the backend) at runtime rather than failing loudly at download time.
- **no GPU offload happening on a machine with an NVIDIA card** — check
  `nvidia-smi` is on `PATH`; `src-tauri/src/lib.rs`'s `detect_gpu_layers()`
  shells out to it and silently falls back to CPU-only (`0`) if it's missing,
  which is safe but slower.
- **installer builds but app won't start** — check the sidecar binary exists
  at `src-tauri/bin/thinkstack-api-<target-triple>` and is executable; `lib.rs`
  falls back to `python -m uvicorn` from `.venv` only in dev, not in a bundled
  release.
