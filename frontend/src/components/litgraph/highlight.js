/**
 * Why a passage in the reader is worth looking at.
 *
 * Four reasons, and they are not equally exact:
 *
 *   match  exact. hits[].chunk_id comes from search_papers(), which already
 *          returns every matching chunk per paper in reading order.
 *   claim  approximate, by word overlap. See below.
 *   gap    approximate, the same way. A gap carries up to two short supporting
 *          phrases in `evidence`, written by the same model under the same
 *          instruction as a claim's supporting_text, so it is located by the
 *          same matcher rather than a second one tuned differently.
 *   theme  approximate. Themes attach to documents, never to chunks, so
 *          keyword presence is the only signal that exists on the client.
 *
 * Both approximations under-report rather than mislabel: a passage is left
 * unmarked when the evidence is not there, and never marked on a guess.
 *
 * ponytail: exact spans need per-chunk character offsets the chunker does not
 * store, and a real theme signal needs cosine of the chunk embedding against
 * the theme centroid -- a new endpoint. Go there if this reads as wrong
 * rather than merely sparse.
 */

export const norm = (s) => (s || '')
  .toLowerCase()
  .replace(/[^a-z0-9 ]+/g, ' ')
  .replace(/\s+/g, ' ')
  .trim();

// Not a stopword list, a "carries no evidence" list. Short words are dropped
// by length anyway; these are the long ones that mean nothing on their own.
const EMPTY = new Set(['that', 'this', 'with', 'from', 'into', 'their', 'these',
  'those', 'which', 'while', 'than', 'they', 'have', 'been', 'such', 'also',
  'each', 'when', 'where', 'using', 'used', 'based', 'shows', 'show']);

/** The words in a string that could identify a passage. */
export const terms = (s) => new Set(norm(s).split(' ').filter((w) => w.length >= 4 && !EMPTY.has(w)));

// Fewer distinctive words than this and there is nothing to be confident about.
const MIN_TERMS = 3;
// Share of a claim's words that must appear in a chunk before it is marked.
const MIN_OVERLAP = 0.5;

/**
 * The chunk a claim's supporting text sits in, or null if it cannot be found.
 *
 * Word overlap, not substring. A claim's supporting_text is written by the
 * model -- "a brief supporting phrase, max ~12 words" -- and is a paraphrase,
 * not a quotation. Checked against the real library here, whole-phrase
 * matching located zero of five claims while word overlap located the two it
 * should have; the wording never survives, the vocabulary does.
 *
 * One chunk per claim, the best-scoring one, because "which passage is this
 * claim from" has one answer. Below MIN_OVERLAP it has none, and a wrong
 * landing is worse than no landing.
 *
 * markChunks uses this too, so a claim that highlights a passage is exactly a
 * claim that can jump to it -- neither can appear without the other.
 */
export function locateQuote(chunks, quote) {
  const q = terms(quote);
  if (q.size < MIN_TERMS) return null;
  let best = null;
  let top = 0;
  for (const c of chunks || []) {
    const words = terms(c.text);
    let hit = 0;
    for (const w of q) if (words.has(w)) hit += 1;
    const score = hit / q.size;
    if (score > top) { top = score; best = c.chunk_id; }
  }
  return top >= MIN_OVERLAP ? best : null;
}

// The abbreviations that actually appear in academic prose, and that a naive
// terminator split would cut a sentence in half at. Not a general list -- a
// general list is unmaintainable and this one is closed: these are what showed
// up in the library on this machine.
const ABBREV = /(?:e\.g|i\.e|et\sal|cf|vs|Fig|Eq|Tab|Ref|approx|no|pp|St|Dr|Prof)\.$/i;

// A terminator followed by whitespace, unless what precedes it is one of those.
// Split with a capture so the pieces can be rejoined when the split was wrong:
// javascript has no variable-length lookbehind, so the abbreviation cannot be
// excluded in the pattern itself.
const SENTENCE = /([.!?])\s+/;

/** Split into sentences, keeping abbreviations attached to their sentence. */
function sentences(text) {
  const parts = String(text || '').split(SENTENCE);
  const out = [];
  // split() with one capture group yields [text, punct, text, punct, ...].
  for (let i = 0; i < parts.length; i += 2) {
    const piece = parts[i] + (parts[i + 1] || '');
    const prev = out[out.length - 1];
    if (prev !== undefined && ABBREV.test(prev)) out[out.length - 1] = `${prev} ${piece}`;
    else out.push(piece);
  }
  return out.filter((s) => s.trim());
}

// Lower than MIN_OVERLAP on purpose. locateQuote has already said this is the
// right chunk, so picking the sentence inside it is the easier question. Held
// at MIN_OVERLAP, a quote whose words straddle two sentences narrows to nothing
// and the whole block gets painted again.
const SENTENCE_OVERLAP = 0.25;

/**
 * The one sentence in a chunk that a quote came from, or null.
 *
 * The chunk says which page; this says where on it. Null means there is no
 * narrower answer, and the caller keeps the whole chunk -- a broadly
 * highlighted claim beats an unhighlighted one.
 *
 * Two matchers, in order. A theme keyword or a phrase quoted verbatim sits
 * inside its sentence, so containment finds it exactly and works on quotes far
 * too short for word overlap to say anything about. A model's paraphrase sits
 * nowhere, so it falls through to the overlap locateQuote already uses.
 */
export function bestSentence(text, quote) {
  const nq = norm(quote);
  if (!nq) return null;

  const parts = sentences(text);
  if (parts.length < 2) return null;   // already as narrow as this chunk gets

  const literal = parts.find((s) => norm(s).includes(nq));
  if (literal) return literal.trim();

  const q = terms(quote);
  if (q.size < MIN_TERMS) return null;
  let best = null;
  let top = 0;
  for (const s of parts) {
    const words = terms(s);
    let hit = 0;
    for (const w of q) if (words.has(w)) hit += 1;
    const score = hit / q.size;
    if (score > top) { top = score; best = s; }
  }
  return top >= SENTENCE_OVERLAP ? best.trim() : null;
}

/**
 * Every reason to mark a passage, with the phrase that caused it.
 *
 * The phrase matters to the pdf reader and not to the text one. A chunk is a
 * whole block of a page, so marking the chunk paints two columns yellow and
 * says nothing -- the chunk locates the *page*, and the phrase locates the
 * sentence on it. The text reader has no such problem: it lays chunks out as
 * paragraphs, so marking one marks a paragraph.
 *
 * `quote` is null where there is nothing narrower than the passage itself --
 * a search hit with no query behind it.
 *
 * @returns Map<chunk_id, {kind, quote}[]>
 */
export function markSpans(
  chunks,
  { hits = [], claims = [], gaps = [], theme = null, query = '' } = {},
) {
  const spans = new Map();
  const add = (id, kind, quote = null) => {
    if (!spans.has(id)) spans.set(id, []);
    spans.get(id).push({ kind, quote });
  };

  // A hit is a whole chunk, so the passage has no narrower phrase of its own.
  // The words you typed are the narrower phrase.
  for (const h of hits) add(h.chunk_id, 'match', query || null);

  for (const claim of claims) {
    const at = locateQuote(chunks, claim.supporting_text);
    if (at) add(at, 'claim', claim.supporting_text);
  }

  // A gap carries up to two phrases and they need not sit in the same passage,
  // so every one that locates is marked -- unlike a claim, which has one
  // source passage by definition.
  for (const gap of gaps) {
    for (const quote of gap?.evidence || []) {
      const at = locateQuote(chunks, quote);
      if (at) add(at, 'gap', quote);
    }
  }

  const keywords = (theme?.keywords || []).map(norm).filter(Boolean);
  if (keywords.length) {
    for (const c of chunks || []) {
      const text = norm(c.text);
      const found = keywords.find((w) => text.includes(w));
      if (found) add(c.chunk_id, 'theme', found);
    }
  }
  return spans;
}

/**
 * Spans reduced to the reasons alone, dropping the phrases.
 *
 * @returns Map<chunk_id, Set<'match'|'claim'|'gap'|'theme'>>
 */
export function kindsOf(spans) {
  const marks = new Map();
  for (const [id, list] of spans) marks.set(id, new Set(list.map((s) => s.kind)));
  return marks;
}

/** @returns Map<chunk_id, Set<'match'|'claim'|'gap'|'theme'>> */
export function markChunks(chunks, sources) {
  return kindsOf(markSpans(chunks, sources));
}
