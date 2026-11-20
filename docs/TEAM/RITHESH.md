# Rithesh: contributions

A record of the parts of ThinkStack I worked on, written mainly so the rest of
the team (and future me) can find the reasoning behind the decisions.

## Paper writer

Scribe is the LaTeX side of the app: a file tree, an editor, an AI draft helper,
and a compiler. The pieces I own:

- `domain/paper_writer/compiler.py`: the engine wrapper. Tectonic when it is
  bundled, `pdflatex` when it is not. It parses compiler errors, injects missing
  packages, and degrades gracefully, so a broken figure or table still produces
  a PDF instead of failing the whole document.
- `domain/paper_writer/files.py`: a project is a directory, and this is the
  boundary around it. See the section below.
- `domain/paper_writer/indexing.py`: generates the `.ind` an index needs.
- `api/routes_papers.py` and `api/routes_paper_files.py`: the project endpoints
  and the file endpoints.
- `frontend/src/components/Scribe.jsx` and `FileTree.jsx`: the tree, the editor,
  the AI prompt bar, and the PDF preview.

There was a second preview once: `LatexPreview.jsx` rendered the source to HTML
with KaTeX so a "Live Preview" tab could update without compiling. I removed it,
along with the KaTeX dependency. It was a second, worse renderer that disagreed
with the real PDF, which meant the thing you were looking at while writing was
never the thing you would publish. The compiled PDF is the only preview now, and
it rebuilds a moment after you stop typing.

## A paper is a folder

A colleague's paper would not compile: the engine could not load a figure, then
divided by zero. The second message was the first one's consequence — the
graphics package reading a width from a file it had never opened.

The compiler was not at fault, which took some looking to establish. A project
had been a directory on disk since the first version, and compilation always ran
with that directory as its working directory, so the relative path in
`\includegraphics` resolved correctly. What was missing was any way to put a
second file into the folder. `main.tex` was the only file the application could
reach, so a figure could be referenced and never supplied.

I exposed the directory that already existed — list, read, write, upload,
rename, move, copy, delete — and replaced the row of project chips with a file
tree that has the papers themselves as its top level. The chips had been a
second picker for the upper level of the same hierarchy, with no way at all to
reach the level below.

The part I would want reviewed is the boundary. This API is reachable from the
webview, which Tauri treats as remote content, so a filename arriving here is
untrusted input in the same sense a download URL is: `../../../.ssh/id_rsa` is a
filename. Every operation resolves its argument against the project directory
and refuses anything landing outside. Resolution happens *before* the check
rather than a string test for `..`, because that is what catches a symlink —
nothing about the name `notes.tex` says it points at `/etc`. I disabled the
containment check deliberately to confirm the tests fail.

## Indexes, and what not to depend on

The same paper failed a second way: `\printindex` produced `Undefined control
sequence \indexentry`. An index needs two passes with an external step between
them, and the bundled engine performs that step for bibliographies but not for
indexes — so the intermediate file was never converted and `imakeidx` fell back
to reading the raw entry list as markup.

The obvious fix was to call `makeindex`. It is installed on my machine and would
be installed on no user's, which is the same error as assuming a system TeX —
exactly what bundling an engine was meant to eliminate. So the index is
generated in Python instead. It is a small, stable format, and it fits what the
compiler already does: repair what it is given rather than refuse it.

Both failures are now checks in `validate_bundle.py`, run against the packaged
app on all three platforms. The figure check inspects the PDF for an image
XObject rather than trusting `status: compiled`, because a compile that silently
drops the figure reports success too.

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
  locally and running ingest, search, and generation against it.

## Model bundling and routing

The installer bundles one model - a 0.5B for general tasks, search, and Scribe.
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

**Bench** is where this surfaces. The capability report and the model picker
were two sidebar buttons opening modals; they answer two halves of one question,
so they are one section now. It is deliberately thin: HuggingFace acquisition,
per-task model suggestions and the registry are being built separately and land
here, rather than being mocked up against a data shape that does not exist yet.

`tests/test_capability.py` covers it against fabricated machines rather than
real ones, so an 8 GB M1 and a 64 GB workstation are both testable on CI with no
GPU present.

## CI/CD and auto-updates

the release pipeline is config-driven: `release.config.json` holds the repo,
platform matrix, channels, and models; `.github/workflows/_build-desktop.yml`
and `_publish-release.yml` are reusable (`workflow_call`) and hold all the
build/publish logic; and `release.yml` is the single entry point.

it used to be five entry points -- `release-stable`, `release-beta`,
`release-on-main`, `release-on-beta` and `nightly` -- which differed only in
what started them and how the version was worked out. their build and publish
halves were byte-identical, and two even shared a concurrency group. one
workflow with three triggers replaced them: merging into beta cuts a beta,
merging into main publishes what beta validated, and the cron cuts a nightly.
Ten workflows became six.

a merge is the decision to release; the tag is the record of what was built.
tags trigger nothing, because while they did, `git push origin v1.2.3`
published a release to every user without the merge being reviewed.

each build produces installers for Linux, macOS, and Windows and publishes them
to GitHub Releases. Updates use Tauri's updater, but only when the user asks:
the check is behind the sidebar button rather than on launch, because an
offline-first app should not contact the network unprompted (each channel has
its own manifest URL).
The signing key stays out of the repo (the private key lives at `~/.tauri` and as
a CI secret; only the public key is committed). The supporting scripts are
`scripts/compose-updater-manifest.sh`, which builds the manifest, and
`scripts/release.sh`, which bumps the version and tags the release. See
[../ADR.md](../ADR.md) for the decisions and [../../CONTRIBUTING.md](../../CONTRIBUTING.md#releasing)
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
  release); non-devops utilities moved to `tools/`. See `CONTRIBUTING.md`.
- `tests/` is the automated `pytest` suite (run `pytest`), gated in CI by
  `.github/workflows/ci.yml`. `tools/check_paper_writer.py` remains as a manual
  end-to-end paper-writer integration check (real pdflatex compile). It is
  named `check_` rather than `test_` so it cannot be mistaken for part of the
  automated suite: `pytest.ini` sets `testpaths = tests`, so a `test_*.py`
  living in `tools/` is never collected and would imply coverage that does
  not run.
- `scripts/README.md` (since merged into `CONTRIBUTING.md`) is the runbook for cutting a release and for how
  downloads and updates work. I also maintain the landing page (`landing.html`)
  and the ADR entries for the decisions above.

## Model management (Bench)

Bench is where the machine's capability and the models that use it live
together. The parts I own:

- `domain/model_manager/registry.py`: the user's model choices, persisted
  through `atomic_io`. Two flags carry most of the safety. `managed` says
  whether ThinkStack created a file, so nothing here can delete weights we did
  not write — an imported model is referenced where it already is, never
  copied, because a 7 GB import must not cost 14 GB on a machine we already
  know is constrained. `user_assigned` says whether a human chose the tasks, so
  an update can refresh what a release assigned but never overwrite a choice
  somebody made on purpose.

- `domain/model_manager/router.py`: which model answers a given task, on this
  machine, right now. Every dependency is passed in rather than imported, which
  is what makes routing testable against fabricated hardware with no llama.cpp
  present. It returns a `Resolution` carrying the *reason*, not a bare path —
  the old code put its reasoning in a log line and threw it away, so when
  analysis quietly ran on the smaller model the interface had no way to say so.

- `domain/model_manager/manifest.py` and `reconcile.py`: what this build
  bundled, and what to do about it on an update. The `replaces` field is what
  makes an upgrade work rather than just an install; without it, retirement has
  to infer intent from absence, which is how the `beta-latest` installs got
  stranded.

- `domain/model_manager/huggingface.py`: search and acquisition, the only part
  of the app that reaches the network. Download URLs are constructed from a
  repository id and a filename, never accepted — the local API is reachable
  from the webview, so an endpoint that fetched whatever it was handed would be
  a general-purpose downloader aimed by anything that could reach it.

- `scripts/make_bundled_manifest.py`: the build writes what it shipped beside
  the weights, so exchanging the bundled model is one edit to
  `release.config.json` rather than four coordinated source changes.

### What this taught me

Three bugs in one day had the same shape: a legitimate `0.0` being read as "no
value". A size rounded before being compared against a budget; `measured or
declared` preferring a stale figure; and a budget that floors at zero on a
constrained machine, where zero already meant *unmeasured, therefore
unconstrained* — so the machine least able to run anything was told it could
run everything.

And two things that "passed" without working. Qwen3 0.6B cleared every
structural check and returned `{}`, because the JSON grammar leaves a reasoning
model's `<think>` block nowhere to go. A React render test I had just written
to catch a blank page did not catch it, because it mounted the page components
and never `App.jsx`, where the missing import actually was. Both were found by
deliberately breaking the code and checking the tests noticed — a test that has
never failed is a hypothesis, not evidence.

A third shape, found the day the file tree shipped: three menu items — new file,
new folder, new paper — did nothing at all. They were built on the browser's
`prompt()`, which the Tauri webview does not implement; it returns `null`, and
the code read that as the user cancelling. Deleting had the same dependency on
`confirm()`, where the failure is worse in a way worth stating: a guard written
as `if (!confirm(...)) return` either blocks the action forever or performs it
without ever asking, depending which way `undefined` falls.

Behind that sat a second defect that would have broken the menu even with a
working dialog — it dismissed on a capture-phase `pointerdown` without checking
whether the press was *inside* it, so pressing an item unmounted the button
before its own click arrived.

Neither is visible in the source, and neither would be caught by any test I
could reasonably have written: both are about what the *host* provides. The
lesson is narrower than "test more". A desktop web view is not a browser, and
the platform's absences are as much a part of the contract as its APIs. I had
tested the code; I had not run the product.

## Release engineering, and shipping to real users

Everything above is code that runs on a user's machine. This is the part that
gets it there, and it broke in more interesting ways than the app did.

- `scripts/ship.sh`: beta to production in one command. It replaced a merge and
  a separate workflow dispatch, and the reason is not tidiness — I did the merge
  and not the dispatch, so `main` sat un-released while I believed it had
  shipped. Two steps that must both happen are one step. Afterwards it asserts
  the outcome rather than assuming it: not a draft, not a prerelease,
  `latest.json` attached, four installers present, `/releases/latest` resolving
  to the new tag. Each of those had been wrong in a real release.

- `scripts/rollback.sh`: shaped entirely by a constraint I had not thought
  through. **You cannot un-ship.** The updater compares versions and only moves
  forward, so an app that already updated will never come back, and deleting the
  release does not reach it. That splits rollback into two different problems.
  Marking the bad release a prerelease makes `/releases/latest` fall back within
  seconds, which fixes everyone who has not updated yet; reaching the rest means
  publishing the *old* code under a *higher* number. Once I saw that, the design
  was forced.

- The downgrade hole: `release.yml` accepted a version override with no ordering
  check at all, so `-f version=1.0.0` would have tagged it and published it as
  "latest". The guard existed — in `release.sh`, which is not on the dispatch
  path anyone uses. I put it in both the script and the workflow, because I had
  just dispatched a release from my phone, which is exactly when no script is
  involved.

### The bug class I keep meeting

Three separate failures in two days had the same shape: **a check that tests for
silence, when the failure mode is confident wrongness.**

`draft: false` was a request, not a guarantee — the release reported every job
green and was invisible. `llama_supports_gpu_offload()` returned `False` on a
perfectly good 49 MB Vulkan library, because it reports whether a backend
*registered* at runtime, not whether one was *compiled in*, and a CI runner has
the SDK but no driver; the build failed its own verification. And the worst one:

```python
if use_slm and (not metadata.title or not metadata.abstract):
```

There is a working SLM fallback for metadata extraction that can never fire,
because the guard tests for an *empty* title and the regex always returns a
*wrong* one. On *Attention Is All You Need* it returns Google's copyright
notice, and on every paper we tried the author list contained the paper's own
title and its authors' employers. That metadata labels every node on the
LitGraph map.

I found it by refusing to build citations on a layer I could not vouch for, and
tracing one real PDF through every stage instead. The fix is not a rewrite: the
title is the largest horizontal text near the top of page one, which PyMuPDF
already knows and `extract_text()` throws away by flattening to a string.

The lesson I want to keep: **`0.0`, `False` and `""` are values, not absences.**
Every one of these bugs was a guard that could not tell the difference.

## Metadata extraction, and a number that was worth nothing

I rebuilt the extractor to read the page rather than a string, and split it in
two: one module that turns glyphs into rows of cells and knows nothing about
papers, and one that decides what a title or an author is.

The split earned itself immediately. Three of the four worst bugs were geometry,
not bibliography — rows grouped by the top of their bounding box instead of the
baseline they share, which turned a small-caps title into `A : A M S O`; a font
change mid-word, which put a space inside `ADAM`; and an accent stored as its own
glyph *before* its letter, leaving `Doll ´ar` where `Dollár` should be. None of
those are about research papers, and none are visible inside a function that is
also asking whether something is a name.

I pushed back on one thing hard: the obvious way to drop employers from author
lists is a list of employers. Google, Tsinghua, Mistral, NAVER — it is never
finished and it dates. We used structure instead. A *structural* word
(university, institute, research) condemns a whole row, not one cell, because
attention.pdf's affiliation row is `Google Brain | Google Brain | Google Research
| Google Research` and only half of those cells carry a word any list would hold.
The rule I am most pleased with is mine: **a phrase printed twice in the author
band is an address, because a name appears once per paper.** It needs no
vocabulary at all, and it is the only thing that separates "United Kingdom" from
"Kaiming He" — identical to any test of spelling.

Then the part I did not expect. On our test papers it was perfect: every title,
year and author exact. I asked for it to be tested on real papers we had not
picked, so we sampled 56 across 15 arXiv categories through the API and scored
against arXiv's own records. **62.5%.**

Every point of that gap was a typesetting convention nobody had looked at. One
physics template spaces a centred author line widely enough to read as columns,
so two authors arrived as five fragments and none of them was a name. Another
runs from affiliations straight into the abstract with no heading, so the search
carried on into the body and collected `I. Introduction` as an author. And a
margin cutoff I had added to kill an arXiv stamp was deleting the first line of
any centred title wide enough to start left of it. Fixing those took it to
**92.9% of titles and 85.7% of author lists exact**.

Our test set was not dishonest. It was one field, and a template is a convention
of a field. **A number measured over material you chose yourself describes your
choice, not your method.** That is the thing I want to remember from this more
than any of the rules.

I also stopped a change that looked like a win: counting a bare acronym like
`IEEE` as an institution fixes `Wang, Senior Member, IEEE` and costs more
elsewhere — 85.7% down to 83.9%. It is reverted, with the numbers in a comment,
so nobody re-adds it on the strength of the one case it helps.

What is left is a long tail of the same kind: mathematics inside titles,
publisher cover pages, submissions too new to carry a stamp. More rules will not
clear it. The established answer is a classifier over the same layout features —
which is what GROBID does, and is where I would stop expecting this approach to
improve.

## Supporting work on Library

**Library is Jitvan's module** — the screen, the document list, the encryption
controls and the overview panels are his. This section records what I changed
underneath them, because the faults were in layers I own (the model registry
contract, the ingest queue, the shell's layout) rather than in his interface.

The panel meant to show which model was in use did this:

```js
models.find((m) => m.status === 'ready') || models[0]
```

`'ready'` is not a status our backend emits — it says `'present'` — so the find
never matched and it silently fell through to whichever model was first. But
the deeper problem is that the question has no single answer. Routing is **per
task**, and which entry serves a task depends on every other entry. The backend
already computes that and had said so in a comment I wrote weeks earlier:
*"computed here, not in the UI: duplicating that rule in javascript would let
the two drift."* On my machine the 1.5B that actually serves Analysis was not
in the `models` array at all. It reads `routing` now.

Two of the four stat cards had been hardcoded `-` since they were written, and
a lone `-` was also standing in for "loading" and for "the request failed". The
same shape as the metadata guard from the day before: one value covering
several distinct facts, so the one you need cannot be seen.

The layout taught me something I did not expect. Scribe and LitGraph sized
themselves with `calc(100vh - 11rem)`, commented *"the header is ~2.1rem of
title plus its margin"*. That is a constant standing in for a measurement, and
it went wrong the moment we removed the page titles — silently, as a strip of
dead space. I replaced it with `flex: 1` and **broke it worse**, because there
is an unclassed `motion.div` between `<main>` and the page and a flex chain
dies at the first link that isn't a flex parent. Both pages collapsed to the
height of their own content, and I only found out from a screenshot.

The lesson is narrow and I want to keep it: **I swapped a mechanism without
checking what it sat inside.** The old code was fragile, but it was fragile in
a way that worked; my replacement was correct in principle and wrong in that
DOM. Three rounds of the same mistake followed — filling a column whose
neighbour then grew taller, then equalising panels with unequal content —
before I stopped positioning things by assumption and made the layout flow.

Also worth recording: the frontend unit tests froze the machine for an hour
during a push. Not a big suite — 175 tests, five seconds. Vitest defaults to
one worker per core, and on a 16-core laptop already running an editor that is
sixteen node processes each with its own jsdom. `preflight.sh` now passes
`--no-file-parallelism` locally; CI runners are small enough not to need it.
The checks were never the problem, the concurrency was.

## A type scale, and a sidebar that leaves something behind

Two shell-wide changes. Both surfaced while Jitvan was reviewing Library's
density — **that page and every decision about what it shows are his**; what
follows is the part that turned out to have nothing to do with Library.

**Twelve small font sizes.** `0.68`, `0.7`, `0.72`, `0.75`, `0.76`, `0.78`,
`0.8`, `0.82`, `0.84`, `0.85`, `0.9`, `0.95rem` — across two stylesheets and
161 declarations. Two-hundredths of a rem is not a decision anybody made; it is
what happens when each component picks its own number, and the result reads as
sloppy without any single value looking wrong. Six named steps now, and the
root is fluid — `clamp(16px, 0.15vw + 14.6px, 18px)` — so every rem grows with
the window instead of sitting at a fixed 16px on a 27" monitor.

I got this wrong once first: `clamp(17px … 20px)` resolved near 20 on a wide
display and read as *zoomed*, not legible. "Bigger" and "more readable" part
company quickly.

**The sidebar collapsed to zero.** Which sounds like the maximum amount of
room and is the opposite: the two things you still need — the logo to bring it
back, and the "i" explaining the page — then have to be drawn *on top of* the
content. Collapsing the sidebar to get it out of the way put two things in the
way. It collapses to a 64px rail now, and because `.main-content`'s margin
reads the same variable, the page steps aside for it with no second
measurement that could disagree.

One bug from that is worth writing down. Moving the guide onto the rail made it
disappear: the sidebar is `z-index: 100` and the guide is `40`, so on the rail
it rendered behind it — present, correct, and invisible. Nothing about "move
this 60px left" suggests a stacking problem, and nothing in the code says so
either. I found it by looking at the screen and noticing the button was simply
not there.

## Replacing the interface

The dark glass interface had reached the point where I was correcting the same
class of thing repeatedly — twelve ad-hoc type sizes, a sidebar that collapsed
to nothing, panes measured by subtracting a guess from the viewport. I proposed
replacing it rather than continuing to patch it. **Aditya built the
replacement** — *Paper and Ink*, a sheet of paper on a desk worked in ink — as
a parallel `new-frontend/` tree while the old one went on shipping. My part
after that was the migration: carrying the week's work across, proving parity,
and deleting the old tree.

**Two trees means every fix is made twice.** That is the real cost of replacing
a running interface, and it is not the rewrite — it is the fortnight where both
exist. The extractor work, the Library rebuild, the type scale and the rail all
landed in `frontend/` while `new-frontend/` was being written, and every one of
them had to be made again.

Copying would have been faster and wrong. The new tree names its *colours*
`--text`, `--text-2`, `--text-primary`, so the type scale had to be `--type-*`
there — a colour token answering to a size name is a trap someone falls into
six months later. Same for structure: the route wrapper is `.page-turn` there
and was `.page-frame` here, and Scribe's root had no class at all, so the
height chain had to be rebuilt rather than pasted.

**Proving it was safe to delete a working interface.** Three things, in
increasing strength:

- both clients called the same 44 routes
- the contract test passed over both trees
- `local/check_api_reach.py` called every route against a running backend

The third is the one that matters, and it is a different guarantee from the
first two. Reading both sides as text proves the paths **match**; only calling
them proves the handlers **run**. All 16 answered, including the metadata
patch returning 404 for an absent paper: a 405 would have meant the method was
never wired.

I also found a guard about to point at nothing. `test_api_contract.py`
hardcoded `frontend/src/utils/api.js`. The moment the replacement shipped it
would have gone on proving things about a directory nobody builds — passing,
while the live client called routes that did not exist. It takes the tree as a
parameter now, and skips one that is absent, so the next replacement cannot
repeat it.

A guard aimed at the wrong subject is worse than no guard, because it reports
success. That is the third time this month I have written that sentence about a
different piece of this codebase.

## Citations in Scribe

The interaction is mine: you are already typing when you decide to cite, so the
trigger is the word `cite` rather than a shortcut or a dialog. The library
drops down under the caret, filters as you keep typing, and Enter turns the
word into `\cite{key}`. Choose nothing and `cite` stays an ordinary word,
which compiles — nothing is committed by opening the list.

I had planned to track citation numbers and was talked out of it, correctly:
BibTeX renumbers every `\cite` on each recompile and orders the reference list
itself. That whole subsystem was free, and building it would have meant
maintaining a second, worse copy of something the toolchain already does.

Storage had to be fixed before any of it could work. Author lists were
flattened with `", ".join(authors)` into the vector store, and in BibTeX the
comma is *syntax* — `Vaswani, Ashish and Shazeer, Noam` is two people. Read
back for a bibliography, eight authors became sixteen half-names. Nothing
raised; it printed them. Same shape as the extractor bug I spent the week
before on, and it is the shape I look for first now: **the failure is confident
wrongness, not silence.**

Then there is the ceiling nothing in the feature can lift. Extraction is 93%
right on titles and 86% on author lists, so about one paper in seven cites
wrongly however good the citation code is. The Library can now edit authors and
the year, not only the title.

I put that in the Library and not in Scribe on purpose. The library holds the
record, so a fix there carries into every future citation, every node on the
map and every search hit; a fix in one project's `.bib` fixes one paper.
Scribe needs no editor of its own: `references.bib` is already a file in the
project tree, and entries carry a `thinkstackid` field that BibTeX ignores, so
a key or an author can be rewritten by hand and the link back to the library
survives.
