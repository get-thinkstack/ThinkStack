/**
 * Why a passage in the reader is worth looking at.
 *
 * Three reasons, and they are not equally exact:
 *
 *   match  exact. hits[].chunk_id comes from search_papers(), which already
 *          returns every matching chunk per paper in reading order.
 *   claim  approximate, by word overlap. See below.
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

const norm = (s) => (s || '')
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
const terms = (s) => new Set(norm(s).split(' ').filter((w) => w.length >= 4 && !EMPTY.has(w)));

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

/** @returns Map<chunk_id, Set<'match'|'claim'|'theme'>> */
export function markChunks(chunks, { hits = [], claims = [], theme = null } = {}) {
  const marks = new Map();
  const add = (id, kind) => {
    if (!marks.has(id)) marks.set(id, new Set());
    marks.get(id).add(kind);
  };

  for (const h of hits) add(h.chunk_id, 'match');

  for (const claim of claims) {
    const at = locateQuote(chunks, claim.supporting_text);
    if (at) add(at, 'claim');
  }

  const keywords = (theme?.keywords || []).map(norm).filter(Boolean);
  if (keywords.length) {
    for (const c of chunks || []) {
      const text = norm(c.text);
      if (keywords.some((w) => text.includes(w))) add(c.chunk_id, 'theme');
    }
  }
  return marks;
}
