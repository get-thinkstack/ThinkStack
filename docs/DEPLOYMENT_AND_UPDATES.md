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

the landing page is a single static html file, so any static host works. the
download buttons point at `github.com/.../releases/latest/download/...`, which
works no matter where the page is hosted.

### the constraint: keep a personal name out of the url

a personal github pages site is served from `rithesh077.github.io/thinkstack`,
and the release and updater urls are `github.com/rithesh077/thinkstack/...`. on a
team project that name in the url is worth avoiding. the two hosting decisions
(the landing page, and the releases the updater points at) should be considered
together, because both carry the name.

| option | landing-page url | release/updater url | releases stay simple? | effort |
|--------|------------------|---------------------|-----------------------|--------|
| personal github pages | `rithesh077.github.io/...` | `github.com/rithesh077/...` | yes | low |
| **github organization** (recommended) | `<org>.github.io/thinkstack` | `github.com/<org>/thinkstack` | yes | one-time repo transfer |
| cloudflare pages | `thinkstack.pages.dev` | `github.com/rithesh077/...` | yes | connect repo, no transfer |
| custom domain (any host) | `thinkstack.app` etc. | can be proxied | yes | ~$10/yr + dns |

### recommendation: a github organization

create a free github organization (for example `thinkstack-app` or a team name)
and transfer the repo into it. this is the best fit for the stated needs:

- **neutral url everywhere.** both the pages url (`<org>.github.io/thinkstack`)
  and the release/updater urls (`github.com/<org>/thinkstack`) drop the personal
  name.
- **releases stay exactly as simple.** the whole flow is unchanged: tag a
  version, ci builds, github releases publishes the installers and `latest.json`.
  nothing moves off github.
- **shared ownership.** teammates join the org as members, so the project is not
  tied to one person's account. this is the direct answer to "they will point it
  out": it is now the team's repo, not one member's.

after transferring, update the hardcoded `Rithesh077/ThinkStack` references (the
`REPO` const in `landing.html`, the updater `endpoint` in `tauri.conf.json`, and
the urls in the ci workflow and these docs) to `<org>/ThinkStack`. github keeps a
redirect from the old path, but the hardcoded references should point at the new
canonical one.

enabling pages: in the org repo, settings, pages, serve from `/docs` and add
`landing.html` as `docs/index.html`, or from the branch root with a one-line
pages action that publishes `landing.html`.

**alternative without transferring the repo:** connect the existing repo to
**cloudflare pages**, which serves the landing page at a neutral
`thinkstack.pages.dev` and redeploys on every push. this fixes the visible page
url with almost no effort, but the release download links still read
`github.com/rithesh077/...`, so it only half-solves the naming. use the
organization if the release urls matter too.

deployment is deferred until the app is tested end-to-end (see the adr).

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

**Releases are always cut from `main`.** Flow: land your work on `main` (merge
the feature branch), then run `release.sh` **on `main`** so the tag points at a
`main` commit. CI triggers on any `v*` tag regardless of branch, but keeping
tags on `main` means the released code always matches `main`'s history.

```bash
git checkout main && git merge --ff-only v1/fixes   # land the work (fast-forward, no conflicts)
git push origin main
scripts/release.sh 1.0.0 --push                      # bump + tag v1.0.0 on main + push → CI
```

> **Version number:** use the *next* number for the first working, validated
> build (e.g. `1.0.0`). Don't tag until you've downloaded the CI artifact and
> confirmed it runs — a tag is public and the updater treats it as "the latest."

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
  (gitignored via `*.key`).

### where the keys go in GitHub — repo **secrets** (not variables)

These are **Actions secrets**, encrypted and only exposed to workflow runs.
Two ways:

**Via the web UI:**
`repo → Settings → Secrets and variables → Actions → the "Secrets" tab →
"New repository secret"`. Add two:

| Name | Value |
|---|---|
| `TAURI_SIGNING_PRIVATE_KEY` | the **entire contents** of `~/.tauri/thinkstack-updater.key` (a base64 blob) |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | the key's password — **empty** for this key (leave blank) |

- Use the **"Secrets"** tab, **not "Variables"** (variables are plaintext, readable in logs).
- Use **Repository** secrets, not Environment secrets (unless you add a deploy environment).
- Names must match the workflow **exactly** (`build-release.yml` references them verbatim).

**Via the CLI** (never prints the key — it streams the file straight to GitHub):
```bash
gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.tauri/thinkstack-updater.key
gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD --body ""
```
Verify: `gh secret list` should show both names (values are never shown).

### backing up the private key

> ⚠️ **Lose this key and you can never update already-installed apps** — they
> only trust signatures from the matching key. It's 348 bytes; back it up in
> **at least two** of these:

1. **Password manager** (best) — 1Password / Bitwarden / KeePass: paste the file
   contents into a "secure note" titled `thinkstack-updater private key`.
   ```bash
   cat ~/.tauri/thinkstack-updater.key   # copy the output into the secure note
   ```
2. **Encrypted file on cloud/USB** — encrypt, then store the `.gpg` anywhere:
   ```bash
   gpg --symmetric --cipher-algo AES256 ~/.tauri/thinkstack-updater.key
   # → thinkstack-updater.key.gpg  (put on Drive / a USB stick; remember the passphrase)
   # restore: gpg --decrypt thinkstack-updater.key.gpg > ~/.tauri/thinkstack-updater.key
   ```
3. **GitHub secret itself** doubles as a copy — but you can't read it back out, so
   never rely on it as your *only* backup.

Never: commit it to the repo, paste it in chat/email/Slack, or store it
unencrypted in cloud storage. Rotating a leaked/lost key means shipping a normal
update first that carries the *new* pubkey, then signing future updates with the new key.

Without the secrets, CI still builds and publishes installers — they just won't
be signed, so `latest.json` is skipped and auto-update is inactive until you add
the secrets and cut the next release.

---

## 6. build correctness & known issues

Most of the demo→v1 packaging gaps are now fixed and locally validated. What
remains needs the **first CI build** to confirm end-to-end.

**Fixed + validated:**

1. ~~onefile vs onedir packaging mismatch.~~ **Fixed.** `scripts/build.sh` and
   `build-release.yml` freeze with `--onedir` to match `tauri.conf.json`'s
   `resources: { "../dist/thinkstack-api/": "api/" }` and `lib.rs`'s `api/`
   resolution; the dead sidecar-placement steps were removed.
2. ~~Missing native libs in the freeze.~~ **Fixed + validated locally.**
   `--collect-all llama_cpp --collect-all sentence_transformers` are now passed
   (neither has a PyInstaller hook). A local onedir freeze + run confirmed the
   frozen backend bundles llama_cpp's `lib/*.so`, and passed **ingest + search +
   chat** with zero import errors. torch/transformers/sklearn come via their hooks.
3. ~~Bundled model not found on first run.~~ **Fixed.**
   `file_manager.seed_bundled_models()` copies the ggufs from the read-only
   `BUNDLE_DIR/data/models` into the writable `STATE_DIR/models` on first launch
   (no-op in a source checkout). CI bundles **both** the 0.5b and 1.5b models so
   chat *and* gap analysis work offline.

**Still open (need the first CI build / a decision):**

4. **The updater needs one real signed build to verify.** The wiring (plugin,
   config, CI signing, `latest.json` via `compose-updater-manifest.sh`) is in
   place and unit-checked, but only a tagged build with the signing secrets set
   proves the download→verify→install→relaunch loop.
5. **Embedding model isn't bundled** — `embedding_service.py` prefers a bundled
   `all-MiniLM-L6-v2` but CI doesn't ship it, so **first-run embeddings need
   internet** (one-time HF download, then cached). To make first run fully
   offline, add the embedding model to the CI download + `--add-data`.
6. **Installer size ~3.7 GB** (torch + both ggufs). Fine for a demo; if you want
   a smaller download later, drop the 1.5b (gap analysis degrades) or fetch it
   on demand.
7. **`latest.json` platform keys assume the default bundle names** — if a Tauri
   upgrade renames bundles, update `find_asset` in
   `scripts/compose-updater-manifest.sh` and the URLs in `landing.html`.
