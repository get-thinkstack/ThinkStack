# Changelog

All notable changes to ThinkStack, newest first. A version exists only once it
has been published; each entry below has installers on the
[releases page](https://github.com/get-thinkstack/ThinkStack/releases).

Versions are not semantic versioning: the number says how far a build has
drifted, and the updater only needs it to grow. The rules are in
`scripts/next_version.py`; how a release is cut is in
[CONTRIBUTING.md](CONTRIBUTING.md#releasing).

Pending entries go under `[Unreleased]` in the same PR; `scripts/ship.sh`
renames that section to the version it publishes.

---

## [Unreleased]

### Added

- **The map can be relaxed without ceasing to mean anything.** LitGraph draws
  where PCA put each paper, which is the product's central claim — position
  encodes meaning — but a static plate cannot be taken hold of. A single dial
  now runs from the projection exactly as computed, through overlap loosened
  with clusters intact, to a free layout where position is shape rather than
  meaning. Every paper keeps a spring back to **its own** projected home rather
  than to a shared centre, which is what makes it a dial rather than a switch:
  a small library pulled towards one point, with nothing anchoring any paper,
  settles into a knot in the middle of an empty plate.
- **Papers can be dragged and pinned.** A press that does not move is a
  selection rather than a zero-distance drag — committing on `pointerdown` had
  pinned every clicked paper where it already sat, and the pin's own re-render
  then replaced the element before the click landed, so papers stopped being
  selectable at all.
- **The panel says where a paper sits** before it lists anything, and a
  neighbourhood can be followed out to a chosen depth.
- **A paper can use a file that lives somewhere else.** Link a `.tex`, `.bib`,
  figure or PDF from anywhere on the machine; the project references it where it
  sits rather than taking a copy, for the reason imported models are not copied
  either. Because a referenced file can move, each link also stores the
  operating system's identity for it, which survives a rename and a move within
  a filesystem — so reorganising your documents does not silently break a paper.
  The path is checked before the identity, so an editor that saves by writing a
  temporary file and renaming it still reads as the same document. A file moved
  somewhere the project has never referred to is reported as missing, with a
  button to find it, rather than guessed at. A whole **folder** can be linked
  too — a shared `figures/` directory used by several papers — though its
  contents are never read or served: it is a remembered location, and copying
  it in is the only thing that touches what is inside.
- **A file chooser that works everywhere.** Clicking to link something opens a
  window you navigate — home, up, type to narrow, Enter to open or take — rather
  than asking for a path you have to remember. `Ctrl+O` chooses a file and
  `Ctrl+K Ctrl+O` a folder, following the editor most people already have in
  their hands. It reads directories through the backend, so it behaves the same
  in the desktop app as in a browser; files a paper cannot use are shown greyed
  rather than hidden, so a folder never looks emptier than it is.
- **A linked file is usable, not just remembered.** Write its bare name --
  `\includegraphics{chart.png}` -- and the compile finds it where it sits. One
  `references.bib` can be shared by three papers and stay a single file. A link
  that has gone missing is skipped and reported rather than failing the build.
- **Anything can be linked or added to a paper**, not only the file types LaTeX
  reads. A dataset or a README beside a document is a normal thing to keep, and
  a type the engine cannot open is useless to a document rather than dangerous
  to one. The chooser still marks which files a document could reference.
- **Scribe works with an empty library.** It carries its own TeX engine and
  compiles offline, so writing never depended on having read anything — but the
  first screen of a new install said only "drop a PDF here", which reads as a
  locked door to anyone who came to write. The empty Library now offers Scribe
  beside ingestion, and nothing in Scribe requires an ingested paper.
- **A new document can be something other than a research paper.** Six starters
  — research paper, article, letter, CV, report and Beamer slides — opened as a
  menu from the **+** in the tree, each described rather than merely named. A
  letter is no longer a paper you have to delete first. The set comes from the
  backend, so the menu cannot offer a shape that no longer exists, and an
  unrecognised one gives you the paper rather than an error.
- **The project tree is navigable at 23 papers.** Sort by name or last edit,
  filter once there are enough to be worth narrowing, and see when each was last
  touched.
- **A bibliography panel.** What the document cites, what `references.bib`
  defines, and which entries nothing cites — read from the source rather than
  the compiled PDF, so a citation typed a moment ago is already there.
- **Files can be dragged where they belong**, including into another paper.
  Folders are the drop targets; a file is not, because "beside it" would be a
  reorder this tree does not have.
- **The compiled PDF saves where you choose, named after the paper** — reduced
  to what every filesystem accepts, not to the project id. The button says
  **Save PDF**, because labelled only "PDF" it read as a link to the file and
  the save behaviour went unfound. In a browser it stays an ordinary download,
  because a page cannot choose a folder, but it arrives correctly named either
  way.
- **`Ctrl+K` reaches any screen or any paper** from the keyboard.

### Changed

- **A `feat/` branch moves the minor again.** Landing a feature advances Y and
  resets Z; a `fix/` advances Z. Between 2026-08-05 and now every landing moved
  Z and only a human could move Y, on the reasoning that calling something a
  feature release is editorial. It is — but naming a branch `feat/` *is* that
  judgement, made by the person who built it. What the previous rule produced
  was a Y that almost never moved, so a build that had gained a whole subsystem
  read the same as one that had fixed a typo.
- **Y carries into X at ten again, not twenty.** The radix was raised to twenty
  on 2026-08-09 so that X would not climb after ten features, which can be one
  quiet quarter. Reverted: a two-digit Y is precisely what the scheme exists to
  avoid — the number is a decimal odometer, and its value is that the distance
  between two versions is readable without parsing. If X climbs too often that
  is a statement about how readily a minor is declared, not about the radix.
  Y is a single digit, 0–9; X is unbounded; Z is unbounded and resets whenever
  a column above it moves.

Otherwise a new development cycle. See `docs/FUTURE_WORK.md` for what is
planned.

---

### Fixed

- **Documents compile offline.** The research paper, article, CV, report and
  slides, and any plain article, report or book, needed a network on their
  first compile; the bundled TeX engine now compiles them with none.
- **Qwen3 4B now works for analysis and gap finding.** Offered as the most
  capable model, it returned empty results for both; it now produces real
  gaps, suggestions and summaries.
- **No screen claims a model comes with the app any more.** None has since
  models became user-managed; the first-run note now says to choose one in
  Bench.
- **A paper with no title appears under its filename** on the map, not as an
  id.

### Security

- **Encrypting a paper now hides it at rest.** Its text and its PDF are
  encrypted on disk, and no part of the app shows either without the password.
  Removing encryption restores both exactly. Before, an encrypted paper's text
  stayed readable on disk and through the app.
- **Other websites can no longer act on ThinkStack.** A page open in your
  browser could previously send requests that added a PDF to your library or
  started a download; any write from another site is now refused.

## [2.3.5] — 2026-08-15

The first round in which testers on machines nobody here owns ran the real
installers. It produced four defects in an afternoon, after a fortnight in which
every automated suite had been green. None was a regression; all had been
present and unobserved. They are repaired on one branch and released as one
increment, because four branches would have meant four gigabyte builds and four
version numbers for what was, from a user's position, one afternoon's
correction.

### Fixed
- **Windows: no PDF would open.** The message named a file rather than a paper,
  so the tester reasonably deleted and re-ingested everything, which changed
  nothing because no paper was involved. Python assembles its table of media
  types partly from the Windows registry, which has no entry for `.mjs`; the
  server therefore described the PDF viewer's worker module as plain text, and
  a browser refuses to execute plain text as a program. The asset arrived intact
  and was declined on the doorstep. Invisible on Linux and macOS, where the
  built-in table answers correctly. `register_web_mime_types()` now runs at
  import, before the static mount — a fix that has to be called by hand is a fix
  nobody calls.
- **The gap finder repeated itself.** Valid output, arrived at by more than one
  route across a corpus large enough to support it, and nothing downstream was
  obliged to notice. Findings are now deduplicated on the normalised
  description, with evidence and related documents merged into the survivor and
  the worse severity kept. Severities are declared worst-first, so the more
  serious value is the lower index, and the first version of the merge
  confidently kept the milder one; a test written before the fix caught it.
- **Selecting a node took more precision than it should.** Raised independently
  by testers on two operating systems within an hour, which makes it design
  rather than hardware. The click target was the drawing — about six pixels once
  the map is scaled to show everything. The drawing is unchanged, since larger
  discs were removed months ago for turning the map into a bubble chart; an
  invisible target now carries the selection at a constant size on screen at any
  zoom. The label, thirteen times the area, is selectable too.
- **The reading surface was tiring in a dim room.** A physical report, not a
  preference: the page was at 94% luminance and filling the screen. An
  intermediate version lowered the page and the desk together and was rejected
  on sight as dusty — luminance had fallen while colour intensity rose, and dark
  with strong colour reads as dirt rather than as paper. The shipped version
  lowers only the page and puts the character of the stock into its warmth.

### Changed
- **The download page carries its own typefaces.** The previous one fetched
  three families from a third party, which contradicted the product it was
  advertising: an application whose premise is that nothing leaves the machine
  had a front door that could not draw itself without contacting someone else.
  Inlined, it makes no external request at all and is marginally smaller than
  the page it replaced. It also cannot be half-deployed, because there is no
  longer a directory that has to reach the right branch at the right moment.

---

## [2.3.0] — 2026-08-15

### Added

- **Cite a paper without leaving the sentence.** Type `cite` in Scribe and the
  library drops down under the caret; keep typing and it filters on title,
  author, year or key; Enter turns the word into `\cite{key}` and writes the
  entry into the project's own `references.bib`. Dismiss it and `cite` is still
  just a word, and a word compiles.

  Citation *numbers* are not tracked anywhere, which is the point of emitting
  keys: BibTeX renumbers every `\cite` on each recompile and generates the
  reference list in the style's own order. Keys read the way a LaTeX user
  expects — `vaswani2017attention` — because the whole value of a key is that a
  human types it.

  One `references.bib` per project, and the file is the authority: a key
  already written there is never recomputed, so a `\cite` already typed cannot
  break when the library grows. Entries carry a `thinkstackid` field that
  BibTeX styles ignore, which is what lets you edit the file by hand — rename
  a key, fix an author — and keep the mapping.

- **A wrong reference can be corrected.** The Library's title edit now covers
  authors and the year as well. Titles are extracted right about 93% of the
  time and author lists 86%, so roughly one paper in seven is stored wrong, and
  that data labels every node on the map, names every search hit, and is what a
  BibTeX entry is built from. Fixing it once fixes every paper cited from then
  on.

### Fixed

- **Author lists were destroyed on the way into storage.** The vector store
  holds strings, so the list was flattened with `", ".join(authors)` — and in
  BibTeX the comma is *syntax*: `Vaswani, Ashish and Shazeer, Noam` is two
  people. Read back, eight authors became sixteen half-names, and a
  bibliography does not raise, it just prints them. Authors are JSON-encoded
  now; rows written the old way are still read as written.

- **The arXiv identifier and DOI were extracted and thrown away.** Both were
  found while dating the paper and discarded. A reference carrying neither is a
  dead one, so they are kept — on papers ingested from now on.

- **`pdflatex` never ran BibTeX, so citations resolved to `[?]`.** Tectonic
  drives BibTeX as part of its own build, so the bundled engine was fine and a
  build from source was not — which is every developer's machine. The pass now
  runs when the engine will not do it, driven off the `.aux` rather than the
  source, because a `\cite` inside a commented-out paragraph is in one and not
  the other.

- **A document that cited papers but had no bibliography printed `[?]`.** The
  reference list is typeset by `\bibliography`, and that command is also what
  puts the `\bibdata` line in the `.aux` that invokes BibTeX at all — so a
  document without it silently produced neither. It is added before
  `\end{document}` when the document actually cites something *and* the
  project has a `references.bib`; pointing at a file that is not there would
  turn a working compile into a failed one.


- **Every paper in the library had the wrong title, authors and year.** The
  extractor read the document as flat text and kept any of the first ten lines
  over ten characters as the title, then took any two capitalised words as an
  author. On *Attention Is All You Need* the stored title was Google's copyright
  notice, the author list contained "Google Brain" and the paper's own title, and
  the year was 2014 — the first four-digit number on the page, three years before
  the paper. That metadata labels every node on the LitGraph map.

  A PDF is not text: it is glyphs carrying a size and a position, and the title
  is the largest horizontal text at the top of page 1 with the authors on the
  rows beneath it. `extract_text()` throws all of that away. Title and authors
  are now read from the layout, the year comes from the arXiv identifier or a
  stated copyright line, and a year the paper does not state is left **empty**
  rather than guessed.

  Measured against 56 papers sampled at random across 15 arXiv categories, with
  arXiv's own metadata as ground truth: **92.9% of titles, 85.7% of author lists
  exactly right (no extras), 92.9% of years**. Author lists no longer contain
  employers, addresses, email fragments or the paper's own title.

- **The fallback that could never run.** A small-language-model path existed for
  papers the regex could not handle, guarded on the title being *empty*. The
  regex never returned empty — it returned wrong — so the guard never fired on a
  single paper it existed to rescue. A plausibility check replaces it: a usable
  result needs a title that is not boilerplate *and* at least one author. When
  the model does run it is now given the page's font sizes rather than the same
  flat text that misled the regex, and it may fill a missing field but never
  overwrite a good one.

- **Ligatures and accents reached the search index.** "Efficient" is stored in a
  PDF as the single glyph `U+FB01`, and TeX writes an accent as its own glyph
  *before* its letter, so "Dollár" arrived as `Doll ´ar`. Both are normalised at
  parse time; before this, neither surname nor title could be searched for.

- **Library's overview reported things it did not know.** "Bench in use" read
  the model list and took the first entry whose status was `ready` — a status
  the backend does not emit; it says `present` — so it always fell through to
  whichever model happened to be first. There is no active model: routing is
  per task, and the 1.5B that actually serves Analysis was not in that array at
  all. It now reads the routing table the backend already computes, one row per
  task. "Analyses Run" and "Gaps Found" had been hardcoded to `-` since they
  were written and now carry real counts. A lone `-` also meant three different
  things — loading, empty, and *the request failed* — which are now told apart.

- **Nothing showed that ingestion was still working.** Analysis is queued after
  the upload responds, so a user was told "ingested", opened LitGraph, found it
  empty, and had no way to know a model was still running. Library now shows the
  queue and refreshes when it drains.

- **A wrong title could not be corrected.** Rows showed the filename, so the
  extracted title — which labels the paper everywhere else, including every
  LitGraph node — was never even visible. It is now shown and editable, and
  "Needs Attention" names the papers missing an author list or a year.

### Changed

- **Scribe's prompt is one control, not three.** An icon, a two-row field and a
  labelled Generate button sat on a wrapping row, saying between them what the
  placeholder already said — and the height came straight out of the editor.
  There is one field with a round arrow in its corner. The keyboard hint and
  the grounding toggle share a line instead of stacking. The editor itself no
  longer has a fixed 460px height, which on a tall window stopped short and on
  a short one pushed the prompt past the pane's hidden edge; it takes the
  height it is given.

- **Page titles are gone from all four screens.** The nav says where you are,
  the brand mark follows it, and Library now introduces the others by name. A
  heading reading "Scribe" above Scribe only cost the editor a strip of height.
- **Scribe and LitGraph fill the window properly.** Both sized themselves with
  `calc(100vh - 11rem)` — a guess at the chrome above them, which was silently
  wrong the moment the title was removed. They now take the height they are
  given. Library takes the full width too: the 1400px measure exists so prose is
  not set 1900px wide, which is not a problem a dashboard has.

- **Library says less, and says it where it matters.** Six stat cards opened
  the page — the least actionable thing first, pushing the papers themselves
  below the fold — and a "chunks per paper" chart nobody acts on sat under
  them. The counts now caption the Knowledge Base section they describe. Two
  were cut rather than moved: bytes on disk answered a question nobody asked,
  and the chunk count is a detail of how text is indexed. "Analysed" reads
  **15 of 20**, because the gap between ingested and read is the fact worth
  having. The paper list pages five at a time, with an arrow at each end.

- **The interface has a type scale.** There were twelve ad-hoc small sizes in
  the stylesheets — `0.68`, `0.7`, `0.72`, `0.75`, `0.76`, `0.78`, `0.8`,
  `0.82`, `0.84`, `0.85`, `0.9`, `0.95rem` — differences nobody can see and
  nobody chose. 161 declarations now resolve to six named steps, and the root
  size is fluid (`clamp(16px, 0.15vw + 14.6px, 18px)`), so every `rem` grows
  with the window instead of staying at a fixed 16px on a 27" display.

- **The collapsed sidebar is a rail, not nothing.** It used to collapse to zero
  width and leave entirely, which meant the two things you still need — the
  logo to bring it back, and the "i" explaining the page — had to float *over*
  the content, covering whatever was underneath. A 64px rail carries both, and
  since the page's margin is the same variable, the content moves aside for it.
  The separate floating logo is gone: one affordance, in one place, in both
  states.

- **The interface is replaced.** ThinkStack now runs the *Paper and Ink*
  interface — a sheet of paper on a desk, worked in ink, in place of the dark
  glass one. It was built as a parallel tree while the old one shipped; both
  called the same 44 routes, and every one of them was called against a running
  backend before the swap. The old tree is deleted: one interface, one build.

  Everything above carried across: the routing-table read, the correctable
  titles, the paged shelf, the type scale (138 sizes here, six steps) and the
  rail. They were made twice, once in each tree, which is what replacing a
  running interface costs.

- **Ingestion can be stopped.** Dropping thirty papers by mistake used to mean
  waiting for thirty. The paper being read finishes and the queue stops there,
  so nothing is left half-ingested.

- **Bench no longer grades your machine.** The hardware "tier" is gone from
  Bench and Diagnostics. It is a mark out of ten for someone's laptop and tells
  them nothing they can act on; which models fit is what the cards already say.

### Known limitations

- 43 of those 56 papers are exactly right on title, authors *and* year together.
  Mathematics inside a title, publisher cover pages that precede the paper, and
  submissions too new to carry an arXiv stamp still defeat it.
- Library's ingestion progress is per *batch* ("analysing paper 2 of 5"), not
  per document. Saying which row is being analysed needs the document id on the
  job record.
- Papers ingested before this release carry no arXiv id or DOI, so they are
  cited as `@misc` rather than `@article` with the preprint link. Their author
  lists are read from the old comma-joined form, which is wrong wherever a name
  was stored surname-first — not repairable from the string, but repairable by
  hand in the Library.
- Correcting a reference in the Library does not rewrite a `references.bib`
  that already cites the paper. The file is the author's and may have been
  edited by hand, so it keeps what it has; fix the reference before citing it,
  or edit that project's `.bib`.
- The new interface and the citation feature are verified on Linux only.
  Windows and macOS are outstanding.

---

---

## [2.1.10] — 2026-08-09

### Fixed
- **Bench told AMD, Intel and open-driver machines nothing about their GPU.**
  Two detectors answer "is there a GPU here" and they disagree: `vram_gb` comes
  from `nvidia-smi`, which exists only where NVIDIA's proprietary driver is
  installed, while `accelerable_device` comes from Vulkan, which reaches AMD,
  Intel and Mesa/NVK as well. The advice was gated on `vram_gb >= 2`, so those
  machines reported 0.0 GB and the sentence explaining that their GPU was idle
  never printed — while the card beside it offered them the graphics download
  anyway. The offer appeared with nothing saying why anyone would want it, on
  exactly the machines the Vulkan work was done to reach. Now the advice asks
  the detector that can see them, keeping `vram_gb` as the fallback for a card
  `nvidia-smi` found but Vulkan could not reach.

### Added
- **`scripts/ship.sh`** — beta → main → published in one command. Promoting used
  to be a merge *and* a separate workflow dispatch, and the gap between them was
  not theoretical: the merge was done, the dispatch was not, and main sat
  un-released while everyone assumed it had shipped. Refuses a dirty tree, a
  failed fetch, a beta that is not ahead of main, a beta whose own build did not
  succeed, a version not ahead of what is published, and a tag that already
  exists. Afterwards it asserts the outcome: not a draft, not a prerelease,
  `latest.json` attached, four installers present, `/releases/latest` resolving
  to the new tag.
- **`scripts/rollback.sh`** — shaped by the fact that you cannot un-ship. The
  updater only moves forward, so an app that already updated will never move
  back and deleting a release does not reach it. Marking the bad release a
  prerelease makes `/releases/latest` fall back to the previous one within
  seconds, which fixes every download and update check that has not happened
  yet; `--reship` publishes the previous tree under a *higher* number, which is
  the only way to reach anyone who already updated. `--undo` reverses the first
  half.

### Changed
- **Y now carries into X at twenty rather than ten.** Ten made a major version
  arrive after ten features, which can be one quiet quarter, so X climbed for
  reasons no user could feel.
- `release.yml` refuses a version lower than the published one. The override
  input was accepted with no ordering check at all, so `-f version=1.0.0` would
  have tagged it, published it as "latest", and presented every user with a
  downgrade their updater would silently ignore. The guard existed in
  `release.sh`, which is not on the dispatch path anyone uses; it now lives in
  `ship.sh` **and** in the workflow, because a dispatch can be run from the
  GitHub UI or a phone.

---

## [2.1.9] — 2026-08-08

### Fixed
- **Scribe and LitGraph looked like their dividers were broken.** They were not:
  `.main-content` carried `max-width: 1400px` for every screen, so on a 1920px
  window the panes resized correctly inside a 1400px box and left 500px of dead
  space beside them. Dragging worked and simply ran out of room early, which
  reads as a bug rather than a limit. A page now declares whether it is a
  document or a workspace in `features.js`; workspaces take the whole window and
  drop their padding from 4rem to 2rem, while Library and Bench keep a measure,
  because prose set 1900px wide is unreadable.

---

## [2.1.8] — 2026-08-08

### Fixed
- **A beta release built correctly, uploaded every asset, reported every job
  green — and stayed a draft.** A draft is invisible and its assets 404, and the
  updater maps 404 to "up to date", so testers were told they were current while
  the release sat there unreachable, and the download page 404d for the same
  reason. `draft: false` is a request, not a guarantee, so the publish is now
  asserted after the fact and republished with retries if it is wrong.

---

## [2.1.7] — 2026-08-08

### Fixed
- **The graphics engine build had never once run.** `workflow_dispatch` can only
  be registered from the default branch, so its first execution was in
  production, and it failed twice for unrelated reasons. On Linux there is no
  `glslc` package on jammy at all — the shader compiler llama.cpp's Vulkan
  backend needs — so it now comes from LunarG's own repository. On Windows,
  `--no-binary :all:` meant *every* package in the tree, so pip tried to compile
  numpy from source and died; only `llama-cpp-python` needs building, since
  compiling it with `-DGGML_VULKAN=on` is the entire point.
- **The build then failed its own verification.** The step asserted
  `llama_supports_gpu_offload()` and got `False` on a 49 MB Vulkan library that
  was perfectly good. llama.cpp loads backends *dynamically*, so that function
  reports whether a GPU backend successfully **registered**, not whether one was
  compiled in — and a CI runner has the SDK but no driver. It now asserts what a
  build can prove: the library exists, is large enough to hold compiled shaders,
  and links against the Vulkan loader.

### Changed
- Dependabot groups minor and patch upgrades into one pull request per
  ecosystem. The first time the config reached the default branch it opened
  sixteen PRs in sixty seconds, and sixteen is a queue nobody works through —
  an unreviewed upgrade is the same silent drift that broke the nltk build,
  wearing a PR number. Majors stay ungrouped, because those need someone reading
  a changelog.

---

## [2.1.6] — 2026-08-08

First release of the 2.x line. Carries everything listed under **1.x
accumulated** below, plus:

### Added
- **Graphics acceleration is now actually available.** The Vulkan engine is
  built and published to the rolling `accel-latest` release, so the offer Bench
  makes can be fulfilled. Before this the app correctly detected the hardware,
  correctly quoted a size, and then failed with "the graphics engine is not
  published for this platform yet" — because it never had been.

---

## [1.10.5] — 2026-08-08

### Fixed
- **The sidebar ate the click that collapsed it.** Any press inside the page
  collapses the sidebar, and it collapsed *during* the press: the sidebar is
  220px wide and the page is offset by it, so the whole page slid 220px left
  over 180ms while the button was still held down. A click is not something the
  page sends — it is a conclusion the browser draws when mousedown and mouseup
  land on the same element, and moving the element between them means the
  conclusion is never drawn. The sidebar shut and the action never ran. The
  press now *arms* the collapse and the gesture ending applies it.
- **"Update app" found the new version, installed nothing, and reported "Up to
  date".** Tauri's webview does not implement `window.confirm`: it returns
  `undefined`, not a boolean, and the updater read that as "the user declined".
  The confirm is now a real dialog, and three outcomes replace two — "could not
  ask" is an error, "declined" is `declined`, and neither is "current".

---

## [Unreleased]

Work merged but not yet tagged.

### Changed — breaking

- **The app is now three sections instead of five.** Library, Search, Analysis,
  Gap Finder and Paper Writer became **Library** → **LitGraph** → **Scribe**
  (collect, understand, write). Search, Analysis and Gap Finder were three views
  onto one question, so they are now one canvas. `/search`, `/analysis` and
  `/gaps` redirect to `/litgraph`; any bookmark to them still lands somewhere
  sensible. No data, API route or storage path changed — only the sections.
- **Search is purely semantic.** BM25 keyword search and the reciprocal-rank
  fusion that combined it with vector search are gone, along with the
  `rank-bm25` dependency. Queries are now ranked by cosine similarity across
  *every* chunk of every paper rather than a `top_k` candidate pool. Paraphrase
  queries improve markedly; rare literal tokens (`FedAvg`, author surnames) are
  preserved by a small exact-token bonus applied after the semantic score.
  Results may be ordered differently than before. See `docs/ADR.md`.

### Added
- **Bench** — a fourth section: what this machine can run, and the models it
  runs it with. `Diagnose my machine` and `Add better models` were two sidebar
  buttons opening modals; they are two halves of one question, and a modal is
  the wrong shape for something consulted while deciding. Deliberately thin —
  model acquisition, per-task suggestions and the registry land here later
  rather than being mocked up now.
- **`POST /api/system/diagnose`** re-examines the machine on request. The
  profile is cached at startup, which is right, but a user who frees memory or
  upgraded from a build predating this had no way to make the app look again.
- **`infrastructure/capability.py`** — one place that answers "what can this
  machine do". Rust detects, Python decides; every derived number (tier,
  context, GPU layers, token budgets) comes from here instead of ten places.


- **LitGraph** — a spatial map of your library. Papers are positioned by meaning
  (PCA over embedding centroids), linked by similarity, grouped into theme
  territory, and annotated with gap markers wired back to their evidence. The
  map doubles as the selector: shift-drag a lasso or run a search, and
  Summarize / Claims / Themes / Find-gaps operate on that selection. Past
  analyses and gap scans live in one Runs drawer.
- `GET /api/graph` — the derived graph payload. Computed from data that already
  persists, so there is no new state and no extra model call.
- `POST /api/search` accepts `group_by_doc`, returning papers with every one of
  their matching chunks in reading order.
- **Analysis runs at ingest, not on the request path.** Uploading no longer waits
  on a ~50 s model call: summaries, claims and themes are queued to a background
  worker, and `GET /api/system/jobs` drives a determinate progress bar
  ("analysing paper 2 of 5"). The canvas refreshes itself when the queue drains.

### Changed
- **The shell embeds only the loading screen.** `frontendDist` pointed at
  `frontend/dist`, compiling the whole SPA into the binary a second time -- the
  window never renders it, since it navigates to the backend, which serves the
  copy PyInstaller bundled.
- **Documentation-only changes no longer trigger a three-OS build**, and the doc
  sync maintains versions in `docs/` only. It previously rewrote test and line
  counts across every markdown file, and installed torch on every push to do it.
- **One release workflow instead of five.** `release-stable`, `release-beta`,
  `release-on-main`, `release-on-beta` and `nightly` differed only in what
  started them and how the version was worked out; their build and publish
  halves were identical, and two even shared a concurrency group. They are now
  `release.yml`: merge into `beta` cuts a beta, merge into `main` releases what
  beta validated, the cron cuts a nightly. Ten workflows became seven.
- **A merge is the release; a tag is the record.** Tags no longer trigger
  builds. While they did, `git push origin v1.2.3` published a stable release to
  every user without the merge being reviewed. The `v*` ruleset still forbids
  moving or deleting a published tag.
- **The version can no longer go backwards.** It is derived from the newest tag
  on *any* channel, not the newest stable one: beta was testing 1.6.7 while
  stable was 1.0.0, so a patch bump computed from stable gave 1.0.1 -- below
  what testers already ran. Each `feat/` and `fix/` branch merged since is
  replayed in landing order, one bump each. `chore/` and `docs/` branches and
  direct commits do not move it. Merges must be `--no-ff`, or the branch name
  never enters the history and the landing is invisible.

### Fixed
- **An updated app kept rendering the previous build's UI.** A freshly installed
  1.6.10 still showed v1.6.7 and the old Analysis screen. The desktop shell is a
  WebKit view whose HTTP cache outlives the application, and nothing sent a
  cache header, so `index.html` -- whose name never changes -- was reused from
  cache and kept pointing at the previous build's assets. It is now `no-store`;
  the content-hashed assets are cached permanently instead.
- **A dependency release broke every platform at once.** `nltk` was declared
  `>=3.9.1`; 3.10.1 shipped between two builds and refuses to import
  `xml.etree` when the working directory is importable, so the frozen backend
  died during startup on Linux, macOS and Windows from a commit that changed no
  Python code. It could not be reproduced locally either, because the developer
  venv had 3.9.4.
- **`uvicorn[standard]` lost its extra** while pinning, silently dropping
  uvloop, httptools, websockets and watchfiles. Nothing failed; it was caught by
  diffing every changed line before merging.
- **The macOS launch test ran before the macOS app was built** and reported a
  tick, because `continue-on-error` renders a failure as success. A separate
  non-masking step now fails the job when a build produces no bundle.

- **Summarizing a paper could return a parser error as the summary.** The token
  limit (640) was too small to hold the summary, key points, methodology *and*
  limitations the prompt asks for, so generation stopped mid-sentence and the
  JSON never closed. The reader saw `summarization failed: Unterminated string
  starting at: line 9 column 5`. The limit is now 1024 (1280 comparative),
  incomplete responses are repaired rather than discarded — a truncated summary
  is kept, a half-written bullet is dropped — and if it still cannot be read the
  message explains what to do instead of quoting the exception.
- **The Analysis page had two buttons for one action.** "Summarize" only
  *selected* a mode; a second, identically styled "Run summarize" underneath did
  the work. The three analysis buttons now run the analysis they name.
- **`preflight.sh` checked nothing on a branch that had never been pushed.**
  With no upstream it fell back to diffing the working tree, so once the work
  was committed it saw zero changed files, skipped every toolchain, and printed
  "CI should be green" without running ruff, pytest or shellcheck. That is every
  `feat/` and `fix/` branch on its first run. It now compares against `origin/dev`.
- **`beta` and `nightly` name both a branch and a rolling release tag**, and git
  resolves tags first. `git checkout beta` detaches onto a release, `git pull`
  reports a divergence that does not exist, and `git push origin HEAD:beta` fails
  with "dst refspec beta matches more than one" — which is what broke the doc
  sync. Renaming the tags was tried and reverted: it split the download path, and
  testers got the previous build. Every push and checkout in the repo now names
  refs in full (`refs/heads/beta`), which is unambiguous regardless of the tag.
- **`promote.sh release` would have promoted the wrong version.** `$REPO` was
  read but never assigned, so under `set -u` the lookup of what beta had been
  testing failed silently and the script fell back to inferring from commit
  subjects: it derived **1.1.0** while beta was validating **1.6.7**. It now
  reads the repo from `release.config.json` and fails loudly if it cannot.
- **`promote.sh release` reported failure for a release that published fine.**
  It merged into `main` *and* tagged, but a push to `main` already triggers
  `release-on-main.yml`, which derives the version and creates the tag itself.
  `release.sh` then hit either "no CI results found" (CI on the new commit had
  not finished) or "tag already exists", and `promote.sh` printed "the tag was
  refused, so nothing was released" while CI was building and publishing it.
  Tagging `main` is now CI's job alone.
- **The packaged app never started.** v1.0.0's installer showed a loading spinner
  indefinitely. The backend lookup missed the AppImage/deb layout (binary in
  `usr/bin`, resources in `usr/lib/ThinkStack`), so the app silently fell back to
  running a system `python3` -- which the AppImage's own `AppRun` had already
  broken by exporting `PYTHONHOME=$APPDIR/usr`, killing it with "Failed to import
  encodings module" before any of our code ran.
- **The window crashed a second after loading** on Fedora/Mesa: WebKitGTK's
  DMABUF renderer corrupts the heap. Disabled on Linux.
- **The embedding model was never bundled**, so ingesting the first document in a
  packaged build reached for HuggingFace -- impossible offline, and the docstring
  promised the opposite. It is now shipped inside the installer.
- **The model directory was derived from the working directory**, which is wrong
  for every installed app on every OS. The backend now resolves it itself.
- The loading screen polled `localhost`, which resolves to `::1` first while the
  backend binds IPv4 only.
- Declining the model prompt was permanent and irreversible: the flag lived in
  the webview's localStorage, outside the app, so even reinstalling did not clear
  it, and it silenced every future model rather than the one declined.

### Added
- `LICENSE` (MIT) and `THIRD-PARTY-NOTICES.md`, covering the model weights and
  TeX engine redistributed inside the installer.
- `docs/FUTURE_WORK.md`, separating near-term consolidation (LitGraph, Library)
  from longer work (custom models, federated learning, a LaTeX editor built from
  scratch).
- **The loading screen reports every startup step** with timings, names the
  backend it is launching, and fails with a real error plus a log path instead of
  spinning forever. Startup is bounded at 180s.
- Backend output is captured to `backend.log` (Tauri's app log dir) alongside the
  startup trace, so a failed launch can be diagnosed after the window is gone.
- Sidebar: **Add better models**, **Update app**, and the running version.
- A **beta landing page** at `/beta/`, generated from the same `landing.html` and
  pointing at the newest prerelease.
- `scripts/build.sh` copies installers into `local/` (replacing older ones),
  smoke-tests the frozen backend over HTTP, stages only the models
  `release.config.json` declares, and packages the AppImage the way CI does.
- Beta-testing guide in `CONTRIBUTING.md`: what to check on each OS, per-OS log
  paths, and expected unsigned-build friction.

### Changed
- **The paper writer edits the document instead of appending to it.** The model
  was shown the first 6000 characters of the source, which on any real paper is
  the preamble and introduction, never the part being worked on. It is now shown
  the preamble plus a window around your cursor with an explicit insertion
  point, and generated content is inserted **at the cursor** rather than at the
  end of the document. Output that repeats the surrounding sections, or that
  redeclares the preamble, is stripped before insertion.
- **A TeX engine ships inside the installer.** The paper writer no longer needs
  LaTeX installed on the machine — PDF compilation works out of the box, offline.
  Costs ~25 MB compressed per installer.
- **The compiled PDF is the only preview**, and it rebuilds itself shortly after
  you stop typing. An "Auto" toggle turns that off; the Compile button remains.
  The client-side KaTeX preview is gone: it was a second renderer that disagreed
  with the real PDF.
- **Select plain English and press Ctrl+Enter** to have the local model rewrite
  it as LaTeX in place.
- **The paper writer now uses the larger model when available.** It was routed to
  two fine-tuned models that are never built, so it silently fell through to the
  0.5B — which answered "plot y = x squared" with a reference to an image file
  that does not exist.
- **Updates are user-initiated only.** The check that ran on every launch is
  gone: an offline-first app should not contact the network unprompted. The
  sidebar button reports every outcome, including "Up to date".

---

## [1.0.0] - 2026-07-29

### Added
- First-run model setup: the app detects what your machine can run and offers a
  larger analysis model once, with a progress bar and a cancel button. Declining
  is remembered.
- Model discovery across runtimes — models already installed via **Ollama** or
  **LM Studio** are found and used instead of downloading a second copy.
- `CONTRIBUTING.md`: setup, branch model, what the hooks block, test conventions,
  and the merging + release guides — including who may cut a release and what
  each branch will refuse.
- On-demand modular builds (`dev-build.yml`) — build one OS without cutting a tag.
- Release guardrails: a tag is refused when the version is older than what is
  published or when CI is not green; the publish fails if any asset reaches
  GitHub's 2 GiB limit.
- Local gate (`scripts/preflight.sh`) and shared git hooks that mirror CI.
- `scripts/promote.sh` for the dev → beta → main promotion paths.

### Changed
- **Installers now bundle only the 0.5B baseline model.** Expected to cut every
  installer by roughly 1 GB. The app still works offline immediately; the larger
  analysis model is fetched on consent, or reused from an existing install.
- Documentation restructured: `RELEASE_GUIDE.md` folded into `docs/ADR.md`
  (decisions) and `scripts/README.md` (runbook). `docs/` now holds ABOUT,
  FEATURES, ADR and TEAM.

### Fixed
- Models the user already had could be offered for download again, because
  matching compared filenames and every runtime names the same weights
  differently (`qwen2.5:1.5b` vs `qwen2.5-1.5b-instruct-q4_k_m.gguf`). Matching
  is now on a canonical family/size key. *(Found by Aditya.)*
- The model loader only looked in ThinkStack's own directory, so analysis
  degraded to the base model even when the right weights sat in LM Studio's
  folder.

---

## [0.1.1] — 2026-07-29

First release to build successfully on **all three platforms**.

### Fixed
- **Windows builds failed** at the model-download step: `jq` emits CRLF on the
  Windows runner, leaving a trailing carriage return on the URL that curl
  rejected with "URL rejected: Malformed input to a URL function".
- **macOS builds failed** at code signing: the absent `APPLE_CERTIFICATE` secret
  was passed as an empty string, so Tauri tried to import an empty certificate
  instead of skipping signing.
- `release.sh` staged a path that no longer existed. `git add` is atomic across
  pathspecs, so it staged *nothing* and the version-bump commit aborted.

### Added
- CI smoke test: the frozen backend is booted and must answer
  `/api/system/health` before a build may continue — the only check that
  exercises the bundle rather than the source tree.
- Model and pip caching in CI (the build was re-downloading ~1.5 GB of weights on
  all three runners, every release).

---

## [0.1.0] — 2026-07-27

First public release. Installers for Linux, macOS and Windows, with a signed
auto-updater.

### Added
- PDF ingestion, hybrid search (semantic + BM25 with reciprocal rank fusion),
  summarization, thematic clustering and the gap finder.
- AI-assisted LaTeX paper writer with a live KaTeX preview and an auto-healing
  `pdflatex` compiler that still produces a PDF when a figure is broken.
- Local inference via `llama.cpp`, with task-based routing between a 0.5B and a
  1.5B model and a single resident model to cap memory.
- Paper encryption (Argon2id + AES-256-GCM).
- Native hardware diagnosis in the Tauri shell, replacing a multi-second
  `import torch` on the startup path.
- Automated release pipeline with stable / beta / nightly channels and in-app
  updates.

### Fixed
- A `t"""` typo that only Python 3.12 rejects (valid on the developer's 3.14), so
  every frozen build shipped a backend that could not import.
- Backend startup no longer imports torch/transformers eagerly (~4s → ~0.6s).
- The paper writer's last-resort figure salvage crashed on `re.sub` escapes,
  exactly when it was needed most.
