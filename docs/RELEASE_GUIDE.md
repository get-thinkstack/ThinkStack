# release, distribution & updates guide

the single reference for shipping thinkstack: what a release contains, how users
download and install it, how to cut a release, how installed apps update
themselves, and how the landing page is hosted. written for the team, so anyone
can ship a build without re-deriving all of this.

- [pipeline architecture](#pipeline-architecture)
- [what a release contains](#what-a-release-contains)
- [release channels (stable / beta / nightly)](#release-channels-stable--beta--nightly)
- [how users download and install](#how-users-download-and-install)
- [cutting a release](#cutting-a-release)
- [how updates reach installed apps](#how-updates-reach-installed-apps)
- [supply-chain artifacts (checksums, sbom, provenance)](#supply-chain-artifacts-checksums-sbom-provenance)
- [signing keys](#signing-keys)
- [extending the pipeline](#extending-the-pipeline)
- [hosting the landing page](#hosting-the-landing-page)
- [testing on other operating systems](#testing-on-other-operating-systems)
- [build internals and known issues](#build-internals-and-known-issues)

## pipeline architecture

the release pipeline is built to scale: one place holds the settings, the build
logic lives in reusable workflows, and each release channel is a thin caller. so
adding a platform, a channel, or a second product does not mean rewriting ci.

```
release.config.json          ← single source of truth
  repo · platform matrix · channels · model list · supply-chain toggles
        │
        ├─ scripts/release.sh                 reads it to tag the right channel
        │
        └─ .github/workflows/
             _build-desktop.yml   (reusable)  matrix + freeze + tauri build + sign
             _publish-release.yml (reusable)  manifest + checksums + sbom + release
                  ▲            ▲
                  │            │  callers (thin — trigger + version, that's it):
             release-stable.yml   tag v1.2.3           → stable channel
             release-beta.yml     tag v1.2.3-beta.N    → beta channel
             nightly.yml          schedule / dispatch  → nightly channel
```

why it is shaped this way:

- **one config file.** [release.config.json](../release.config.json) holds the
  repo, the OS/arch matrix, the channels, the models to bundle, and which
  supply-chain artifacts to emit. the workflows and `scripts/*.sh` read it, so
  they never disagree and a new platform is one array entry.
- **reusable workflows.** `_build-desktop.yml` and `_publish-release.yml` use
  `workflow_call`. the build knowledge (cpu-only torch, the pyinstaller flags,
  the appimage workaround) is written once. bumping a build step fixes every
  channel at once.
- **thin channel callers.** `release-stable.yml`, `release-beta.yml`, and
  `nightly.yml` are ~40 lines each: a trigger, a version, and a call to the two
  reusable workflows. a new channel (say `canary`) is a copy of one of these
  plus one entry in `release.config.json`.

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

## release channels (stable / beta / nightly)

the pipeline ships three channels, each its own "pipeline" with its own updater
manifest, so testers can run ahead of stable users without either disturbing the
other. channels are defined in [release.config.json](../release.config.json) and
each maps to one caller workflow.

| channel | how it's triggered | github release | updater endpoint | who runs it |
|---------|--------------------|----------------|------------------|-------------|
| stable | tag `vX.Y.Z` (`release.sh X.Y.Z`) | versioned, marked *latest* | `releases/latest/download/latest.json` | everyone |
| beta | tag `vX.Y.Z-beta.N` (`release.sh X.Y.Z --beta N`) | rolling prerelease `beta` | `releases/download/beta/latest.json` | opt-in testers |
| nightly | schedule (05:00 UTC) or manual dispatch | rolling prerelease `nightly` | `releases/download/nightly/latest.json` | opt-in testers |

the mechanics:

- **stable** is the repo's *latest* release; the landing page and stable apps
  point at it. this is the only channel that bumps the hard-coded version and
  moves the landing page's download links.
- **beta / nightly** publish to a *rolling* release (a fixed tag that gets
  replaced each build), so their updater endpoint is a stable URL even though
  the version inside changes. they are marked prerelease, which keeps them out of
  `releases/latest` so stable users never see them.
- a build in a non-stable channel has its updater endpoint rewritten at build
  time (`_build-desktop.yml` → "Set updater channel endpoint"), so an installed
  beta app checks the beta manifest and self-updates within its own channel.

> **version caveat.** windows msi (WiX) requires a numeric `major.minor.patch`
> version, so the *bundle* version is always the numeric core (a `-beta.N` /
> `-nightly.DATE` suffix is stripped). the full channel version is carried in the
> updater manifest instead. within a channel the manifest version still increases
> build-to-build; just don't expect a beta app to compare its own numeric version
> against the suffixed manifest string — verify the update loop on one real signed
> build per channel before relying on it (same open item stable already has).

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

pushing the `v0.2.0` tag triggers `.github/workflows/release-stable.yml`, which
calls the reusable build + publish workflows: it builds all three installers,
signs them, and publishes them plus `latest.json` to a versioned github release.
use the next unused version number, and only tag a build you have downloaded and
confirmed runs, because a tag is public and the updater treats the newest release
as current.

`release.sh` updates the version in `src-tauri/tauri.conf.json`, `landing.html`,
and `src-tauri/Cargo.toml`. it refuses a dirty tree or an existing tag.

### cutting a beta

a beta goes to the opt-in beta channel and does not touch stable or the landing
page. tag it with a `--beta` counter:

```bash
scripts/release.sh 0.2.0 --beta 1 --push   # tags v0.2.0-beta.1 → beta channel
scripts/release.sh 0.2.0 --beta 2 --push   # next beta
```

this triggers `release-beta.yml`, which publishes to the rolling `beta`
prerelease. a beta tag is cut at the current `HEAD` with no version-file bump.

nightlies need no tag at all: `nightly.yml` runs at 05:00 UTC and skips itself if
there were no commits that day. run it on demand from the actions tab
(workflow_dispatch, tick `force` to build regardless).

### a test build without publishing

to get installers without creating a public release, open the actions tab and run
`release-stable.yml` by hand (workflow_dispatch) with a throwaway version. the
build job still runs and the installers appear as workflow artifacts you can
download. this is the memory-safe way to get a build without running the heavy
compile on your own machine.

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
| signed build + manifest | `_build-desktop.yml` + `_publish-release.yml` + `scripts/compose-updater-manifest.sh` |

the check is a no-op in the web build (`dev.sh`) and never throws, so a flaky
network cannot block startup. the version in `tauri.conf.json` must increase
every release or clients will not see the update.

## supply-chain artifacts (checksums, sbom, provenance)

alongside the installers, `_publish-release.yml` attaches the artifacts an
enterprise or security-conscious user expects. each is toggled in the
`supply_chain` block of [release.config.json](../release.config.json), so a team
that does not want them flips one boolean.

| artifact | file | what it is | how a user verifies |
|----------|------|------------|---------------------|
| checksums | `checksums.txt` | sha-256 of every published installer + manifest | `sha256sum -c checksums.txt` |
| sbom | `sbom.spdx.json` | spdx software bill of materials of the source tree (via syft) | feed to any spdx-aware scanner |
| provenance | (github attestation) | signed, verifiable statement that these binaries came from this repo + workflow run | `gh attestation verify <file> --repo <owner>/ThinkStack` |

sbom and provenance are best-effort (`continue-on-error`): a failure there logs a
warning but never blocks the release. provenance uses github's
`attest-build-provenance`, which needs the `id-token: write` and
`attestations: write` permissions the caller workflows already grant.

### os-level code signing (enterprise hook)

updater signing (above) is separate from the OS developer signing that stops
gatekeeper / smartscreen warnings. the build workflow already threads the env
vars through, gated on secrets — add the secrets and the next build signs itself,
no workflow edit:

| os | secrets to add | effect |
|----|----------------|--------|
| macos | `APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID` | tauri signs + notarizes the `.app`/`.dmg`; no gatekeeper prompt |
| windows | wire an authenticode cert into a signing step (placeholder; azure trusted signing or an `.pfx`) | no smartscreen prompt |

without them the build is unsigned (fine for a student project; users click
through the one-time warning).

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

## extending the pipeline

the point of the reusable-workflow layout is that the common changes are small
and local. concretely:

- **add an OS / architecture** (e.g. linux arm64, windows arm64): add one entry
  to the `platforms` array in `release.config.json` with its `os`, `target`,
  `label`, and `bundles`. the matrix picks it up; no workflow edit. (a new
  *target triple* the runners can't cross-compile natively may still need a
  toolchain/runner tweak in `_build-desktop.yml`.)
- **add a channel** (e.g. `canary`): add a `channels.canary` block to the config
  (its `prerelease`, `rolling_tag`, `endpoint`), then copy `release-beta.yml` to
  `release-canary.yml` and change the trigger + the `channel:` inputs. ~40 lines.
- **change the bundled models**: edit the `models` array in the config — the
  build downloads exactly that list.
- **move to an org / new repo**: change `repo` in the config, the updater
  `endpoints` pubkey stays, and update the hardcoded `get-thinkstack/ThinkStack`
  references noted under [hosting the landing page](#hosting-the-landing-page).
- **ship a second product** from the same repo: give it its own
  `release.config.<product>.json` and a parallel set of callers that pass a
  config path into the reusable workflows (add a `config` input to them). the
  reusable build/publish logic is unchanged.
- **enterprise / air-gapped distribution**: point a channel's `endpoint` at an
  internal host and publish the manifest + installers there instead of github;
  the reusable publish job's release step is the only thing that changes.

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

after transferring, update the hardcoded `get-thinkstack/ThinkStack` references (the
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
