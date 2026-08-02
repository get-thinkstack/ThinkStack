# Polish

Things that are not broken, but are not finished either. `ISSUES.md` is for
defects; this is for the gap between "works" and "good".

Ordered by how much they change what the app feels like, not by effort.

---

## 1. A node click should explain the node

**Asked for 2026-08-02.**

Clicking a paper opens the panel with its title, authors, summary, claims and
chunk count. Everything the *map* knows about that paper is missing — which is
most of what makes it a map rather than a list:

- **Connections.** The paper is linked to up to 4 neighbours by cosine
  similarity, and that edge set is already computed
  (`graph_builder._edges`, `EDGE_THRESHOLD` 0.35, `MAX_EDGES_PER_NODE` 4).
  The panel should list them, with the similarity, and clicking one should fly
  the camera there. Right now the only way to learn a paper's neighbours is to
  hover it and watch what stays bright.
- **Gaps.** A gap marker names the papers that evidence it, but from a paper
  you cannot see which gaps it is cited in. The relation is already in
  `model.gaps[].doc_ids` — it just needs reading in the other direction.
- **Theme.** Which territory the paper sits in, and how many papers share it.
- **Why it is where it is.** The position is PCA over the embedding centroid.
  Even "closest to X, furthest from Y" would make the layout legible instead of
  decorative.

The data is all on the client already. This is panel work, not pipeline work.

## 2. Opening LitGraph for the first time should offer the papers

**Asked for 2026-08-02.**

On first open there is no selection, so the action bar is hidden and nothing
can be run. The only ways to select are typing a search or knowing that
shift-drag lassos a region — neither is discoverable, and the hint line at the
bottom is the only thing that says so.

Give it a paper list with checkboxes: every paper, select-all, and the count
feeding the same `matches` map the search and lasso already write to. Show it
when the library has never been selected from — an empty-state panel rather
than a permanent sidebar, so it does not compete with the canvas once you know
the gestures.

Worth doing together with #1: both are the panel learning to carry more.

---

## 3. Labels that get hidden have no way back

Today's collision pass (`placeLabels` in `useCanvas.js`) hides a label whose box
lands on one already placed. That is right for the static picture and wrong for
the moment you want *that* paper: there is no affordance to reveal it.

Reveal the hidden label on hover, and let the focused paper always keep its own.
Both are cheap — the pass already knows which labels lost.

## 4. Level of detail by node count

Semantic zoom currently only fades labels below `k = 0.5`. On a large library
the useful behaviour is to drop to theme territory and hide individual nodes
entirely when zoomed out, and only resolve papers as you come in. The prototype
switched on node count; the React version never did.

## 5. Prototype features never ported

The original HTML concept (`docs/litgraph-demo.html`, local-only) had these
working:

- **Reader pane** — open a paper at the passage that matched and step between
  matches inside it. The data is already there: `/api/search` with
  `group_by_doc` returns every matching chunk per paper in reading order, and
  the panel shows the first four. This is the "search inside papers" ask, and
  it is frontend work, not a new search engine.
- `Ctrl+K` command palette — jump to a paper by name.
- Keyboard node-walk, breadcrumb trail of where you have been.
- Density terrain, and a suggested reading path through the library.

## 6. Gap markers do not check the spot they land on

A gap is drawn at the centroid of the papers it cites, offset a flat 70px
upward, with no test that anything is already there. Node separation fixed the
papers; this one is still open and is marked in-code in `rebuildModel`.

## 7. Smaller things

- **A paper with no title metadata is labelled with its raw hex `doc_id`.**
  Falling back to the filename would be strictly better.
- **The error toast is overwritten by the next error** before the first has been
  read, and must be dismissed by hand.
- **"Fan out claims" is offered on papers that have no claims** — the button
  should say what it will do, or not be there.
- **The panel disappears below 900px** with no alternative affordance.
- **Per-node analysis state is invisible.** The header counts "3/5 analysed" but
  the canvas does not show *which* two are still waiting.
- **One 811 kB JS chunk.** Monaco, KaTeX and Recharts all load on first paint
  regardless of the section opened. `React.lazy` on the three routes in
  `App.jsx` is the obvious split.

---

## Open questions

- **How long does the bundled 0.5B take per paper on CPU?** The 2026-08-02
  packaged test analysed 2 of 3 ingested papers and ran themes twice
  automatically, roughly 5 minutes apart — but the third paper never got a
  cache entry, and it is not clear whether it was still queued when the app
  closed or whether its analysis failed. Worth a clean run with the log kept,
  because the answer decides whether auto-running a gap scan after *every*
  ingest is reasonable or has to wait for a threshold.
