# deployment & updates guide

How ThinkStack reaches users and how they get new versions, hotfixes, and
features after install. Read this with [RELEASE_GUIDE.md](RELEASE_GUIDE.md)
(which covers the build pipeline itself); this doc covers **distribution and
updates**.

- [1. How users download the right file for their OS](#1-per-os-download)
- [2. "Should I install the app locally so my changes show up?"](#2-installing-locally)
- [3. How updates work (Tauri auto-updater)](#3-how-updates-work)
- [4. Cutting a release / hotfix — the actual steps](#4-cutting-a-release)
- [5. Signing keys (one-time setup + safety)](#5-signing-keys)
- [6. Known issues to resolve before the next real build](#6-known-issues)

---

## 1. per-OS download

**This already works — no per-OS server logic is needed.** The landing page
([landing.html](../landing.html)) has one download button per platform, each
`href` wired at runtime to the matching GitHub Release asset:

| Button | Asset | Why |
|---|---|---|
| macOS | `ThinkStack_<v>_universal.dmg` | one universal binary runs on Apple Silicon + Intel |
| Windows | `ThinkStack_<v>_x64-setup.exe` / `_x64_en-US.msi` | NSIS installer / MSI |
| Linux | `ThinkStack_<v>_amd64.AppImage` / `_amd64.deb` | AppImage runs anywhere; .deb for Debian/Ubuntu |

**Why clicking downloads instead of opening:** browsers download any file they
can't render, and none can render a `.dmg`/`.msi`/`.exe`/`.AppImage`/`.deb`.
So a plain `<a href="…/ThinkStack_….exe">` *is* the download — no JS, no
`download` attribute needed. The `<script>` at the bottom of `landing.html`
only fills in the URLs from `REPO` + `VERSION` constants.

**Optional nicety (not required):** auto-detect the visitor's OS from
`navigator.userAgent` / `navigator.userAgentData.platform` and highlight or
reorder that platform's card first. The other buttons must always stay visible
(user-agent detection is unreliable, and people download for *other* machines).

**To make the page live:** it's a single static HTML file — host it anywhere
(GitHub Pages, Netlify, Vercel, a university web host). Deployment is deferred
until the app is tested end-to-end (see git history / ADR).

---

## 2. installing locally

> "Should I install the app on my machine so that every update gets reflected…
> or is it unnecessary?"

**For your own development: unnecessary, and counterproductive.**

The installed app is a **frozen snapshot** — the Python backend is PyInstaller-
frozen and the Rust shell is compiled. It does **not** pick up source changes.
Reinstalling on every change would be slow and pointless.

Use the right tool for each goal:

| Goal | Use | Reflects code changes? |
|---|---|---|
| Develop / see your changes live | `./scripts/dev.sh` (web) or `./scripts/dev.sh --tauri` (desktop) | ✅ yes, on reload/restart |
| Smoke-test the *final installer artifact* | install the built `.deb`/`.AppImage`/… once | ❌ frozen snapshot |
| End users getting new versions | the auto-updater (below) | ✅ via signed releases |

"Every update gets reflected automatically" is a concept for **end users**, not
for a developer's own edits — and that's exactly what the auto-updater provides.

---

## 3. how updates work

ThinkStack uses **Tauri's built-in auto-updater** with **GitHub Releases** as
the host. Flow:

```
   you tag v0.2.0
        │
        ▼
  CI builds installers for all 3 OSes, SIGNS them with the private key,
  emits per-platform *.sig files, and publishes:
        • the installers (.dmg/.msi/.exe/.AppImage/.deb)
        • latest.json  (the update manifest: version + per-OS url + signature)
        │
        ▼
  installed app on a user's machine, on launch, fetches:
     https://github.com/Rithesh077/ThinkStack/releases/latest/download/latest.json
        │
        ▼
  if latest.json.version > the app's own version:
        → prompt "ThinkStack 0.2.0 is available — install now?"
        → download the matching platform bundle
        → VERIFY it against the public key baked into the app
        → install + relaunch
```

**The pieces, and where they live:**

| Piece | Location |
|---|---|
| Updater plugin (Rust) | `src-tauri/Cargo.toml`, registered in `src-tauri/src/lib.rs` |
| Public key + manifest endpoint | `src-tauri/tauri.conf.json` → `plugins.updater` |
| Permissions | `src-tauri/capabilities/default.json` (`updater:default`, `process:default`) |
| Launch-time check (JS) | `frontend/src/utils/updater.js`, called from `App.jsx` |
| Signed build + manifest | `.github/workflows/build-release.yml` + `scripts/compose-updater-manifest.sh` |

The check is a **no-op in the web build** (`dev.sh`) — the plugins only exist
inside the desktop shell — and never throws, so a flaky network can't block
startup.

---

## 4. cutting a release

Bumping/tagging is scripted. One command does the version bump, commit, and tag:

```bash
scripts/release.sh 0.2.0          # bump version everywhere + commit + tag (local)
scripts/release.sh 0.2.0 --push   # ... and push the tag (triggers CI, confirmed)
```

`release.sh` bumps the version in **`tauri.conf.json`**, **`landing.html`**
(and `docs/landing/index.html` if present), and **`src-tauri/Cargo.toml`** — the
three places it's hard-coded — then tags `v0.2.0`. Pushing the tag runs
`build-release.yml`, which builds + signs + publishes the release **and**
`latest.json`. Installed apps pick it up on their next launch.

### hotfixes / immediate fixes

A hotfix is just a patch release: commit the fix, then
`scripts/release.sh 0.1.1 --push`. Because every installed app checks
`latest.json` on launch, users get the fix automatically the next time they
open the app — no manual re-download, no announcement needed. For a *critical*
fix you can also post the direct installer link from the release page.

### version discipline

The updater compares versions, so `tauri.conf.json`'s version **must increase**
every release or clients won't see the update. `release.sh` enforces `X.Y.Z`
and refuses a tag that already exists.

---

## 5. signing keys

The updater will only install a bundle whose signature matches the **public
key** compiled into the app. This is what stops a malicious server from pushing
a fake "update." Set up once:

```bash
# generate a keypair (already done once for this repo; regenerate only to rotate)
npx tauri signer generate -w ~/.tauri/thinkstack-updater.key
```

- **Public key** → committed in `src-tauri/tauri.conf.json` (`plugins.updater.pubkey`). Safe to share.
- **Private key** → lives at `~/.tauri/thinkstack-updater.key`, **never committed**
  (gitignored via `*.key`). Add it — and its password — as GitHub repo secrets so
  CI can sign:
  - `TAURI_SIGNING_PRIVATE_KEY` = the contents of the private key file
  - `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` = its password (empty string if none)

  ```bash
  gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.tauri/thinkstack-updater.key
  gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD --body ""
  ```

> ⚠️ **If you lose the private key you can't ship updates to already-installed
> apps** — they only trust signatures from the matching key. Back it up
> somewhere safe (a password manager). Rotating the key means shipping a normal
> update first that carries the new pubkey, then future updates sign with the new key.

Without the secrets, CI still builds and publishes installers — they just won't
be signed, so `latest.json` is skipped and auto-update is inactive until you add
the secrets and cut the next release.

---

## 6. known issues

Surfaced during the demo→v1 merge; **resolve before the next real bundle**
(bundling itself is deferred, so these are not yet fixed/verified):

1. ~~onefile vs onedir packaging mismatch.~~ **Fixed.** `scripts/build.sh` and
   `build-release.yml` now freeze with `--onedir` to match
   `tauri.conf.json`'s `resources: { "../dist/thinkstack-api/": "api/" }` and
   `lib.rs`'s `api/` resolution. The sidecar-placement steps were removed
   (Tauri bundles the onedir directly). Still needs one real build to confirm
   the onedir layout + resource paths resolve at runtime.
2. **`createUpdaterArtifacts` needs a real signed build to verify.** The updater
   wiring (plugin, config, CI, manifest script) is in place but has only been
   unit-checked (`compose-updater-manifest.sh` output validated locally). The
   first tagged build with the signing secrets set is what proves it end-to-end.
3. **`latest.json` platform keys assume the default bundle names.** If a Tauri
   upgrade changes bundle filenames, update the `find_asset` patterns in
   `scripts/compose-updater-manifest.sh` and the button URLs in `landing.html`.
4. **Bundled model may not be found on first run (demo packaging gap).**
   `config.py` points `models_dir` at the writable `STATE_DIR/models`, but CI
   bundles the gguf into the read-only `BUNDLE_DIR/data/models` (via PyInstaller
   `--add-data`). There is no first-run "seed" that copies the bundled model
   into `STATE_DIR`, so a freshly installed app would see an empty models dir.
   Options before shipping: (a) add a first-run copy from `BUNDLE_DIR` →
   `STATE_DIR` in the backend startup, (b) point `models_dir` at `BUNDLE_DIR`
   and only write user-added models to `STATE_DIR`, or (c) have the desktop
   shell pass `THINKSTACK_LLM_MODEL_PATH` to the bundled model dir. The
   **embedding model** already handles this (`embedding_service.py` prefers
   `bundled_embedding_dir` if present, else downloads from HF), but CI does not
   yet bundle it — so first run currently needs internet for embeddings.
