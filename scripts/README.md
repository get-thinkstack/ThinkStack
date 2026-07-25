# scripts/

DevOps scripts only — bootstrap, run, build, validate, and release. Anything that
isn't part of getting the app built, tested, or shipped lives elsewhere (`tools/`
for developer/GPU utilities, `tests/` for the pytest suite).

| script | what it does |
|--------|--------------|
| `setup.sh` | one-time environment bootstrap (system deps, toolchains, packages) |
| `dev.sh` | run the FastAPI backend + Vite frontend for local development |
| `validate.sh` | pre-push checks (python / frontend / rust) |
| `build.sh` | local production build (freeze backend, build frontend, compile Tauri) |
| `package-appimage.sh` | package the Tauri AppDir into a signed AppImage |
| `compose-updater-manifest.sh` | build the signed `latest.json` auto-updater manifest |
| `release.sh` | cut a release: bump version, tag the channel (stable / `--beta N`), push |

The release pipeline that consumes these runs in `.github/workflows/` and is
configured by `release.config.json`. See [../docs/RELEASE_GUIDE.md](../docs/RELEASE_GUIDE.md).

Non-devops utilities were moved to `tools/`: `finetune.py` (local fine-tuning),
`verify_gpu.py` / `fix_gpu_dlls.py` (GPU diagnostics), and `test_paper_writer.py`
(a manual end-to-end paper-writer integration check). The automated unit tests
live in `tests/` and run via `pytest`.
