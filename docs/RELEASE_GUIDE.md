# release, distribution & updates guide

the single reference for shipping thinkstack: what a release contains, how users
download and install it, how to cut a release, how installed apps update
themselves, and how the landing page is hosted. written for the team, so anyone
can ship a build without re-deriving all of this.

- [what a release contains](#what-a-release-contains)
- [how users download and install](#how-users-download-and-install)
- [cutting a release](#cutting-a-release)
- [how updates reach installed apps](#how-updates-reach-installed-apps)
- [signing keys](#signing-keys)
- [hosting the landing page](#hosting-the-landing-page)
- [testing on other operating systems](#testing-on-other-operating-systems)
- [build internals and known issues](#build-internals-and-known-issues)

## what a release contains

each release publishes one installer per operating system to github releases,
plus the signed update manifest (`latest.json`). the installers are:

| os | file | notes |
|----|------|-------|
| macos | `ThinkStack_<v>_universal.dmg` | one universal build for apple silicon and intel |
| windows | `ThinkStack_<v>_x64-setup.exe` | nsis installer; `..._x64_en-US.msi` is also published for managed installs |
| linux | `ThinkStack_<v>_amd64.AppImage` | portable, runs on any distro; `.deb` and `.rpm` are also published |

every installer bundles the whole app: the tauri shell, the pyinstaller-frozen
python backend, the built react frontend, and two gguf models (0.5b for chat,
search, and the paper writer; 1.5b for the analysis tasks). nothing is
downloaded at runtime except the sentence-transformer embedding model on first
launch, which is cached afterwards.

### linux packaging, explained

linux has no single package that installs on every distro, so tauri produces
three artifacts and the user picks:

| format | what the user does | installs into the system menu? | works on |
|--------|--------------------|-------------------------------|----------|
| `.AppImage` | mark it executable, double-click | no; it runs in place (portable) | any distro |
| `.deb` | double-click or `sudo apt install ./file.deb` | yes | debian, ubuntu |
| `.rpm` | double-click or `sudo dnf install ./file.rpm` | yes | fedora, rhel |

the appimage is a single self-contained executable, not an archive to unzip and
not a web app. it is the closest thing to "download it and run it" that works
everywhere, which is why the landing page offers it as the default linux
download. users who want a menu entry install the `.deb` or `.rpm` for their
distro instead (both are linked from the releases page).

## how users download and install

the landing page ([landing.html](../landing.html)) shows one recommended
download per os. each button links directly to the matching release asset
(`github.com/<owner>/ThinkStack/releases/latest/download/<file>`), so the browser
downloads the file immediately; it does not open the releases page. the "other
formats" line below the grid links to the releases page for the `.msi`, `.deb`,
`.rpm`, and checksums.

- **macos:** open the `.dmg`, drag thinkstack to applications. on first launch,
  right-click the app and choose open (unsigned builds trip gatekeeper once).
- **windows:** run the `.exe`. if smartscreen warns, click "more info" then
  "run anyway" (unsigned builds).
- **linux:** either make the `.AppImage` executable and double-click it, or
  install the `.deb` / `.rpm` for a menu entry.

macos and windows warnings come from the builds being unsigned by an
os-level developer certificate (apple/microsoft), which is separate from the
tauri update signing below. code-signing certificates cost money and are
optional for a student project.

## cutting a release

releases are cut from `main`. land the work on `main`, then run the release
script, which bumps the version everywhere it is hardcoded, commits, tags, and
optionally pushes:

```bash
git checkout main && git merge --ff-only <feature-branch>
git push origin main
scripts/release.sh 0.2.0 --push    # bump + tag v0.2.0 + push (asks before pushing)
```

pushing the `v0.2.0` tag triggers `.github/workflows/build-release.yml`, which
builds all three installers, signs them, and publishes them plus `latest.json`
to a github release. use the next unused version number, and only tag a build you
have downloaded and confirmed runs, because a tag is public and the updater
treats the newest tag as current.

`release.sh` updates the version in `src-tauri/tauri.conf.json`, `landing.html`,
and `src-tauri/Cargo.toml`. it refuses a dirty tree or an existing tag.

### a test build without publishing

to get installers without creating a public release, open the actions tab, run
`build-release.yml` by hand (workflow_dispatch), and leave "create a github
release" unchecked. the installers appear as workflow artifacts you can download.
this is the memory-safe way to get a build without running the heavy compile on
your own machine.

### hotfixes

a hotfix is just a patch release: commit the fix on `main`, then
`scripts/release.sh 0.1.1 --push`. installed apps pick it up on their next launch
through the updater, so there is no manual re-download for users.

## how updates reach installed apps

thinkstack uses tauri's built-in updater with github releases as the host.

```
  you tag v0.2.0
    |
    v
  ci builds installers, signs them with the private key, emits per-platform
  *.sig files, and publishes the installers plus latest.json (version + per-os
  download url + signature)
    |
    v
  the installed app, on launch, fetches
  github.com/<owner>/ThinkStack/releases/latest/download/latest.json
    |
    v
  if that version is newer than the app's own version:
     1. prompt "ThinkStack 0.2.0 is available, install now?"
     2. download the matching platform bundle
     3. verify it against the public key baked into the app
     4. install and relaunch
```

the pieces:

| piece | location |
|-------|----------|
| updater plugin (rust) | `src-tauri/Cargo.toml`, registered in `src-tauri/src/lib.rs` |
| public key + manifest endpoint | `src-tauri/tauri.conf.json`, `plugins.updater` |
| permissions | `src-tauri/capabilities/default.json` |
| launch-time check | `frontend/src/utils/updater.js`, called from `App.jsx` |
| signed build + manifest | `build-release.yml` + `scripts/compose-updater-manifest.sh` |

the check is a no-op in the web build (`dev.sh`) and never throws, so a flaky
network cannot block startup. the version in `tauri.conf.json` must increase
every release or clients will not see the update.

## signing keys

the updater only installs a bundle whose signature matches the public key
compiled into the app. this is what stops a malicious server from pushing a fake
update. the keypair is generated once:

```bash
npx tauri signer generate -w ~/.tauri/thinkstack-updater.key
```

- the **public key** is committed in `src-tauri/tauri.conf.json`
  (`plugins.updater.pubkey`). safe to share.
- the **private key** stays at `~/.tauri/thinkstack-updater.key` and is never
  committed (gitignored via `*.key`).

### adding the key to github (actions secrets, not variables)

repo settings, secrets and variables, actions, the "secrets" tab, "new
repository secret". add two:

| name | value |
|------|-------|
| `TAURI_SIGNING_PRIVATE_KEY` | the entire contents of `~/.tauri/thinkstack-updater.key` |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | the key's password (blank for this key) |

or from the cli, which never prints the key:

```bash
gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.tauri/thinkstack-updater.key
gh secret set TAURI_SIGNING_PRIVATE_KEY_PASSWORD --body ""
```

use the "secrets" tab, not "variables" (variables are readable in logs), and
repository secrets, not environment secrets. without these, ci still builds and
publishes installers, but unsigned, so `latest.json` is skipped and auto-update
stays off until the secrets are added and the next release is cut.

### backing up the private key

losing this key means you can never update already-installed apps, because they
only trust signatures from the matching key. it is 348 bytes; keep it in at least
two of these:

1. a password manager, as a secure note (paste the output of
   `cat ~/.tauri/thinkstack-updater.key`).
2. an encrypted file on a drive or usb:
   ```bash
   gpg --symmetric --cipher-algo AES256 ~/.tauri/thinkstack-updater.key
   # restore: gpg --decrypt thinkstack-updater.key.gpg > ~/.tauri/thinkstack-updater.key
   ```

never commit it, paste it in chat or email, or store it unencrypted in the
cloud. rotating a lost key means shipping a normal update that carries the new
public key first, then signing future updates with the new key.

## hosting the landing page

the landing page is a single static html file. `.github/workflows/deploy-pages.yml`
publishes it to github pages as the site's `index.html` on every push that
touches it. one-time setup: repo settings, pages, source "github actions". after
that the page redeploys automatically.

### keeping a personal name out of the url

a personal pages site is served from `<user>.github.io/thinkstack`, and the
release and updater urls are `github.com/<user>/thinkstack/...`. on a team
project, prefer a **github organization**: create a free org, transfer the repo
into it, and both the page url (`<org>.github.io/thinkstack`) and the release
urls (`github.com/<org>/thinkstack`) drop the personal name. the release flow is
unchanged, and teammates join the org as members so the project is shared rather
than tied to one account.

after transferring, update the hardcoded `Rithesh077/ThinkStack` references (the
`REPO` const in `landing.html`, the updater `endpoint` in `tauri.conf.json`, and
the urls in the workflows and this guide) to `<org>/ThinkStack`. github redirects
the old path, but the hardcoded references should point at the new one.

a lighter alternative that avoids transferring the repo is cloudflare pages: it
serves the page at a neutral `thinkstack.pages.dev` and redeploys on every push,
but the release download links still read `github.com/<user>/...`, so it only
fixes the visible page url.

the download buttons work only once a release exists (the `releases/latest`
urls 404 until then), so deploy the page and cut a first release together.

## testing on other operating systems

a linux machine can build for linux only, and the ci matrix builds all three but
only proves they compile, not that they run. to actually test:

- **windows:** a free windows 11 dev vm from microsoft, or virtualbox with a
  windows eval iso. install the `.exe` there.
- **macos:** apple licenses macos on apple hardware only, so borrow a mac for a
  smoke test, or document macos as built-by-ci and runtime-tested elsewhere.
  macos vms on non-apple hardware are a licensing gray area.

for the local (linux) test: download the `.AppImage` from the deployed page or
the release, `chmod +x` it, and run it. confirm the app opens, finds a model
(chat responds), and ingests a pdf (search returns results).

## build internals and known issues

`scripts/build.sh` runs the pipeline locally (each step is skippable):

1. build the react frontend into `frontend/dist/`.
2. freeze the backend with `pyinstaller --onedir` into `dist/thinkstack-api/`.
   `--onedir` (not `--onefile`) matches how `tauri.conf.json` bundles the backend
   as the `api/` resource; a onefile build would re-extract a multi-gb payload to
   a temp dir on every launch. `--collect-all llama_cpp` and `--collect-all
   sentence_transformers` are required: neither has a pyinstaller hook, so
   without them the frozen build drops llama.cpp's shared libraries and the
   embedding model's data.
3. verify the frozen backend (no sidecar copy; tauri bundles the directory).
4. compile the tauri app into `src-tauri/target/release/bundle/`.

`file_manager.seed_bundled_models()` copies the bundled models into the writable
models dir on first run, since a frozen build ships them read-only.

### memory during a local build

a tauri release build links large binaries and can spike ram well past what
`cargo check` or `rust-analyzer` use. combined with a model loaded at runtime,
this has caused oom pressure on a 16 gb machine. before building: check `free -h`
(free memory if "available" is under about 6 gb), close a second ide so only one
`rust-analyzer` runs, do not build and run a model-loaded instance at the same
time, and if still tight cap parallelism with `CARGO_BUILD_JOBS=4 ./scripts/build.sh`.
the memory-safe alternative is to let ci build (see the test-build note above).

### open items before a public release

- **the updater needs one real signed build to verify** the
  download-verify-install-relaunch loop end to end.
- **the embedding model is not bundled**, so first-run embeddings need internet
  (a one-time hugging face download, then cached). to make first run fully
  offline, add `all-MiniLM-L6-v2` to the ci model download and the pyinstaller
  `--add-data`.
- **installer size.** the build installs cpu-only torch (the default torch wheel
  on linux/windows drags in ~4gb of unused cuda libraries: `nvidia/*`, `triton`,
  and the cuda build of torch). with that removed the app payload is roughly 1gb;
  the bundled 0.5b + 1.5b models add ~1.6gb, so the installer is about 1.5 to 2gb.
  to shrink further, bundle only the 0.5b model (the gap finder then needs the
  1.5b added manually), or replace torch-based embeddings with an onnx runtime.

## troubleshooting

- **the app builds but will not start:** confirm the onedir backend was bundled;
  `dist/thinkstack-api/thinkstack-api` must exist at build time. `lib.rs` falls
  back to `python -m uvicorn` from `.venv` only in dev, not in a packaged build.
- **no gpu offload on a machine with an nvidia card:** `nvidia-smi` must be on
  `PATH`; `lib.rs` shells out to it and falls back to cpu (safe, slower) if it is
  missing.
- **download button 404s:** no release has been published yet, or the asset
  filename changed (a tauri upgrade can rename bundles). update the `VERSION` or
  the `DOWNLOAD_LINKS` map in `landing.html` to match the actual release assets.
