# Future work

Planned work, split by how much of it exists. **Finishing** reuses working
components: verification, a pass over stored data, or a file already on disk
that nothing reads. **New capability** needs research, training, or components
that do not exist yet. Built work is described in [FEATURES.md](FEATURES.md),
not here.

Each item lands on its own `feat/` branch, one capability per branch. That is
what the versioning needs: a landing is a merge commit whose branch name is the
only input the version number has, so work done in place on `dev` produces no
version movement and no build that reaches a tester. It also keeps half-finished
work out of beta, where testers cannot tell it from a defect.

---

## Finishing what is built

### Verification on Windows and macOS

The current interface and the citation feature are validated automatically on
all three platforms and driven by hand on Linux. Automation cannot see layout:
the citation list once shipped rendering correctly and 1382px below the window
with every test green. A person on each OS has to drive it.

### Source ↔ PDF position sync

`domain/paper_writer/synctex.py` reads the `main.synctex.gz` every compile
writes, and `api/routes_paper_files.py` serves both directions
(`/projects/{id}/sync/forward` and `/sync/reverse`). The interface does not call
them yet. Two steps remain: clicking the PDF moves the cursor to the source
line, and moving the cursor highlights the page region.

### Reference data for papers already ingested

arXiv ids and DOIs are extracted only for papers ingested after the citation
work landed. Older papers cite as a generic entry with no preprint link, and
their author lists come from the old storage format (wrong wherever a name was
stored surname-first). Every PDF is on disk, so this is a re-read of stored files,
not a re-ingestion: no embedding is recomputed.

### Retrieval quality

Search returns the right papers but scores them low (top similarity around 0.21
on unambiguous queries). The ordering is useful; the number is not, and the
map's match rings display it. Candidates: the embedding model, the chunk size, the
lack of a reranking pass. Isolating which is the work.

### Structural validation of generated LaTeX

The malformed-table defect in ISSUES is now *detected* (`compiler._check_tables`
counts cells against the column spec and names the row). Preventing it is two
repairs that compose:

- **Constrained decoding.** The JSON grammar machinery already exists. A grammar
  that reads a `tabular` column spec and then permits exactly that many cells per
  row makes the error *unrepresentable*. Start narrow: `tabular`, then `align`,
  then `algorithm`. A grammar for all of LaTeX is neither achievable nor wanted.
- **Compile before showing.** Tectonic is bundled and driven from the compiler,
  so a fragment can be compiled first and regenerated if it fails: "sometimes
  broken" becomes "compiles, or says it could not".

Both constrain *form*, never *truth*: a table that compiles, not one whose
numbers mean anything.

### Model integrity checks

Detect a corrupted model file at startup rather than at first use.

---

## New capability

### Small models per task, written here

The clearest quality limit is a general small model on structured output. Asked
to plot a function, the 0.5B produced `\includegraphics{chart.png}` (a file that
does not exist); the 1.5B produced a correct `pgfplots` axis from the same
prompt. Even the 1.5B ignores "write only the fragment" and repeats surrounding
sections, which the backend strips deterministically.

**The direction:** one small model per task, with the architecture written here
rather than fine-tuned from someone else's weights. Fine-tuning a 0.5B would
likely be better sooner, but every question about why it behaves as it does
would end in a checkpoint nobody here produced. For a project whose premise is
that computation happens on your own machine, being able to answer that from the
source is the consistent position.

**Scope:** it will not beat Qwen2.5 at general language and does not need to.
The target is one task, a narrow output shape, and training data from the app's
own use. In ascending difficulty:

1. **LaTeX writing**, on instruction → markup pairs already collected by
   `domain/fine_tuning/`. The router already has a `latex_writer` task, so adopting
   one means supplying weights.
2. **Analysis**, on the structured summary and claim formats the app parses.
3. **Citations and references:** splitting author lines into people, naming the
   venue, getting the year right. What defeats the rules is formatting (job
   titles, membership grades, addresses on the author line), which suits a small
   learned model.

**Grammars come first and do not compete.** Where the requirement is structural,
a grammar guarantees it; a model earns its cost on whether the content is good.
Output that always parses also makes cleaner training pairs.

**Why it is tractable:** the pairs come from use, so no labelling; the evaluation
exists and is honest (`local/eval_metadata.py` scores random arXiv papers against
arXiv's own catalogue); and routing is per task, so a model worse than the
current one is simply deselected in Bench. Nothing ships until it wins.

Training one larger model to do everything is deliberately not the plan: the
installer's size budget is why models are not bundled at all.

### Cheaper inference on the machine it runs on

No training, GPU or new model needed, so the cheapest quality available:

- **A memory budget calculated, not estimated.** The KV cache dominates, and its
  size is exact from the GGUF header: 2 × layers × KV heads × head dim × context ×
  bytes per element. That turns "probably fits" into a number Bench can show when
  it explains a downgrade.
- **Reuse the prompt prefix.** Gap analysis and summaries prepend the same corpus
  context call after call; prefill is compute-bound on a CPU, so caching a shared
  prefix removes most of the repeated cost.
- **A quantised KV cache** (8-bit) roughly halves it, buying context on a 16 GB
  machine. Measure the quality cost on this app's own evaluation first.
- **Threads and instruction sets.** Threads should follow physical cores
  (hyperthreads contend for the same FP units); CPU throughput mostly depends on
  which SIMD extensions the build targets.
- **Not yet: speculative decoding.** It pays when the target model is large; here
  it is already small. Revisit if a 3B+ analysis model ships.

The precondition is a baseline: tokens/s, time to first token and peak memory on
a fixed prompt set, before and after each change.

### What Bench should tell you

What a model will actually cost here, and what was given up when a smaller one
was chosen. Including the same model at several quantisations (Q8_0, Q4_K_M,
Q2_K): size, speed and quality side by side, instead of picking a filename.

### A layout classifier for metadata extraction

Rules over page geometry have plateaued on a long tail of conventions (ISSUES,
Limits by design). The established answer is a small classifier over the *same*
features the rules read (font size, position, capitalisation, punctuation, row
order) labelling each row title / author / affiliation / body. GROBID does this
with a CRF at around 90% F1. Kilobytes, CPU-instant, and it degrades gracefully on
unseen templates. GROBID needs a JVM and a server, Nougat a GPU: **nobody
optimises this for a CPU-only, offline machine**, which makes it a research
question whether the answer is "close" or "here is where it breaks".

A cheaper step first, with no model: **remember corrections.** Store the page's
layout fingerprint against a user's fix; papers come in clusters from a few
venues, so one correction pays repeatedly.

### A wider model catalogue and adapters

A catalogue drawn from Hugging Face with selection driven by the hardware
profile (the downloader, discovery and HF search exist). Distribute **adapters**
rather than whole models, so an upgrade costs megabytes, not gigabytes.

### Citation edges in LitGraph

Reference lists are not parsed, so every edge is semantic similarity. Citation
edges would sit alongside them.

### A LaTeX editor built from scratch

The editing surface is a plain text area over LaTeX source. The intent is one
window where LaTeX and direct editing coexist: syntax awareness, bracket
matching and diagnostics against the line that caused them; headings, lists,
tables and emphasis that behave like a word processor while staying LaTeX
underneath; raw command entry for what only LaTeX expresses; and source ↔ PDF
sync (above). `Ctrl+K` does not reach editor operations (compile, link,
save-as) yet; that waits for this rewrite. The file panel's scope stays file
management and the editor's own commands, never a second interface to the
library. Existing editor components each solve part of this; none solves the
combination. This is the largest planned piece.

**Watch the filesystem while the app runs.** Links already survive renames by
file identity when opened (FEATURES, Scribe). A watcher (Rust's `notify` crate)
would catch renames and moves as they happen, leaving the identity search only
for changes made while the app was closed. The cases no method solves: a copy
has a new identity; a move across filesystems loses the inode; editors that save
by write-temp-and-rename change it.

### Deployment beyond one machine

A direction, not a commitment. The groundwork exists: the release pipeline is
config-driven, so an institutional build is a config entry, not a fork. A shared
library on the institution's own hardware is a storage question (only
`local_vector_store.py` knows how chunks are persisted); shared models already work through
discovery; updates on the institution's schedule mean serving the updater
manifest from elsewhere. One constraint governs all of it: **nothing leaves
machines the institution controls.** That rules out the usual shape of this
feature.

### Peer-to-peer sharing

Share papers, drafts or analysis directly with chosen peers (libp2p and public-key
signatures, ADR 2026-06-19), with no central server.

### Federated learning

Improve the models from real use by training on the user's own machine, with
only model updates leaving the device, and only with consent. A possibility, not
a commitment; it must not weaken the privacy guarantee.

---

## Also planned

- **Code signing and notarisation** for macOS and Windows. Both OSes obstruct the
  first launch of an unsigned app, which reads as the software being broken.
- **A design system for the interface,** agreed by the team first, then the
  interface refactored to it.
- **GUI verification on macOS and Windows in CI,** extending the Linux window test.
