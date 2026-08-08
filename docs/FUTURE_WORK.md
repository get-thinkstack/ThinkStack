# Future work

Planned work, divided by how much of it already exists.

The division matters. The first group is mostly **consolidation**: the
capabilities are built, tested and shipping, and the work is joining them into
one coherent thing. The second group is **new capability**, including model
training and a text editor written from scratch, and is measured in months
rather than weeks.

---

## Near term: consolidation of what already works

These reuse existing, working components. Little new machinery is required.

### LitGraph

Today the **gap finder**, **semantic search** and the **encrypted vault** are
three separate screens that already operate on the same corpus, the same
embedding index and the same model runtime. Reaching them separately makes the
user do the joining work.

LitGraph merges them into a single view where the literature is a connected
structure rather than a list of files:

- ask a question, see the passages that answer it, see how the papers containing
  them relate, and see where the literature is thin, as one continuous activity;
- **data handling stays separate.** Encrypted papers remain encrypted and are
  decrypted only on demand. Merging the interface must not merge the storage or
  weaken the vault's guarantees, which is the one hard constraint on this work;
- relationships between papers become first-class, which is the foundation a
  citation graph needs later.

Retrieval, gap detection and the vault already share their inputs, so this
removes duplicated computation as well as duplicated interface.

### Library

A single place showing everything the user has done: papers ingested, searches
run, analyses produced, drafts written, models downloaded.

The data already exists. Analysis runs, gap analyses and paper projects are
already persisted with timestamps in the run histories. This is presentation
over records that are already being kept, not new collection, and nothing leaves
the machine.

---

## Longer term: new capability

These require research, training, or building components that do not exist yet.

### Feature-specific fine-tuned models

The clearest quality limit today is a general-purpose small model on structured
output. Measured: asked to plot a function, the 0.5B model produced
`\includegraphics{chart.png}`, a reference to a file that does not exist. The
1.5B model produced a correct `pgfplots` axis. Both were given the same system
prompt instructing them to use `pgfplots`.

Even the 1.5B model does not reliably follow "write only the fragment": it
reproduces surrounding sections before adding new content, which the backend
currently strips deterministically rather than trusting the instruction.

Planned models:

- **a LaTeX writing model**, fine-tuned on instruction-to-markup pairs. These
  pairs are already collected passively during normal use, and the routing table
  in the inference client already contains entries for such a model, so adopting
  one is a matter of supplying weights;
- **an analysis model**, fine-tuned on the structured summarisation and claim
  extraction formats the application parses, addressing the cases where a
  general model returns prose where JSON was requested.

### A diversified model suite via Hugging Face

Rather than two fixed models, offer a catalogue drawn from Hugging Face, with
selection driven by the hardware profile the application already computes at
startup. The model manager already has a catalogue, a downloader with progress
and cancellation, and cross-runtime discovery, so the mechanism exists; what is
missing is breadth and a way to browse it.

Distributing **adapters** rather than whole models is the intended direction, so
a capability upgrade costs tens of megabytes instead of gigabytes.

### Federated learning

A possible route to improving these models from real usage without collecting
anyone's documents: training on the user's own machine, with only model updates
leaving the device, and only with explicit consent.

Recorded as a possibility rather than a commitment. It must not weaken the
privacy guarantee that is the reason this product exists, and that constraint
takes precedence over the capability.

### A LaTeX editor built from scratch

The current editor is a plain text area over LaTeX source. The compiled PDF is
the preview and rebuilds automatically, which is a real improvement, but the
editing surface itself is primitive.

The intent is one window in which **LaTeX commands and direct editing coexist**,
so an author can write a heading the way they would in a word processor and
write a matrix the way they would in LaTeX, without switching modes or windows:

- syntax awareness, bracket matching, and compiler diagnostics shown against the
  line that caused them;
- direct editing of structure, so headings, lists, tables and emphasis behave as
  they do in an ordinary editor while remaining LaTeX underneath;
- raw command entry for everything that only LaTeX expresses well;
- position synchronisation between source and compiled output, so selecting a
  place in one moves to it in the other.

Existing editor components solve part of this, but none of them solves the
combination. This is the largest single piece of planned work.

---

## Also planned

- **Code signing and notarisation** for macOS and Windows. Required before a
  production release: both operating systems currently obstruct the first launch
  of an unsigned application, which every user encounters and which reads as the
  software being broken.
- **Incremental keyword index**, removing the per-query rebuild that limits
  corpus size.
- **A design system for the interface.** The philosophy will be agreed by the
  team first and the interface refactored to it, rather than the reverse.
- **Bundled model integrity checks**, so a corrupted payload is detected at
  startup rather than at first use.
- **GUI verification on macOS and Windows in CI**, extending the existing Linux
  window test.
