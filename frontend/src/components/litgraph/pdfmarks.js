/**
 * What to highlight on a pdf page, and where in its text that is.
 *
 * The rectangles are NOT computed here. pdf.js hands back one text item per
 * typeset run -- often a whole line -- with a single width and no per-glyph
 * metrics, so any sub-item position derived from it is an estimate. Estimating
 * by character count put strokes through the middle of words. The reader
 * measures instead, with a DOM Range over pdf.js's own text layer, which is
 * exact by construction and costs nothing to be right about.
 *
 * So this module answers the two questions a browser cannot: which passage to
 * look for, and which characters of the page's text it occupies.
 *
 * ── Why word alignment rather than indexOf ──
 *
 * Both sides describe the same page, but not identically. The chunk came from
 * the backend's extractor; the page text comes from pdf.js. They disagree on
 * whitespace, on ligatures, and above all on hyphenation -- the pdf breaks
 * `features` across a line as `fea- tures` and the chunk does not. A substring
 * search fails on exactly the sentences worth marking, so the match is made
 * word by word and tolerates a few misses.
 */

import { norm, bestSentence } from './highlight';

// One passage gets one colour, the way a highlighter does. When a passage is
// several things at once the most specific reason wins: you searched for this,
// versus it merely contains a theme word.
const PRIORITY = ['match', 'gap', 'claim', 'theme'];

// Share of the target's words that must line up before a stretch of the page is
// called a match. Half is deliberately forgiving: hyphenation, ligatures and
// the extractor's own quirks all cost real words, and the alternative to a
// slightly loose match is no highlight at all.
const MIN_ALIGN = 0.5;

/**
 * Every passage to mark, with the page to look on.
 *
 * @param chunks the document's chunks
 * @param spans  Map<chunk_id, {kind, quote}[]> from `markSpans`
 * @returns [{ kind, chunkId, page, text }] -- `page` null means "look on every
 *          page", which is what a chunk that never recorded one deserves.
 */
export function targetsFor(chunks, spans) {
  const out = [];
  if (!spans?.size) return out;

  for (const chunk of chunks || []) {
    const marked = spans.get(chunk.chunk_id);
    if (!marked?.length) continue;

    // Which reason wins is fixed; the quote has to be the winner's own, or the
    // stroke would be the right colour over the wrong sentence.
    const kind = PRIORITY.find((k) => marked.some((s) => s.kind === k));
    if (!kind) continue;
    const { quote } = marked.find((s) => s.kind === kind);

    // No sentence to narrow to is not a reason to drop the mark: a claim the
    // model paraphrased past recognition still belongs to this chunk.
    out.push({
      kind,
      chunkId: chunk.chunk_id,
      page: chunk.metadata?.page_number ?? null,
      text: (quote && bestSentence(chunk.text, quote)) || chunk.text,
    });
  }
  return out;
}

/**
 * Where `target` sits in `pageText`, as character offsets, or null.
 *
 * @returns {{from: number, to: number} | null}
 */
export function findSpan(pageText, target) {
  const page = words(pageText);
  const want = words(target).map((w) => w.norm);
  if (!page.length || !want.length) return null;

  // Slide a window the length of the target across the page and score each
  // position by how many words line up where they should.
  let best = null;
  for (let i = 0; i + 1 <= page.length; i += 1) {
    let hit = 0;
    let first = -1;
    let last = -1;
    for (let j = 0; j < want.length && i + j < page.length; j += 1) {
      if (page[i + j].norm !== want[j]) continue;
      hit += 1;
      if (first < 0) first = i + j;
      last = i + j;
    }
    if (hit && (!best || hit > best.hit)) best = { hit, first, last };
  }

  if (!best || best.hit / want.length < MIN_ALIGN) return null;
  // Trim to the words that actually matched. The window can overhang the
  // sentence at either end when the alignment slips, and an overhang is a
  // stroke running into the neighbouring sentence.
  return { from: page[best.first].at, to: page[best.last].end };
}

/**
 * The page's words with their offsets, rejoining what a line break split.
 *
 * A trailing hyphen means the word continues on the next line, so the two
 * halves are one word spanning both -- which is what makes the offsets come
 * back covering `fea- tures` rather than stopping at the hyphen.
 */
function words(text) {
  const raw = [...String(text || '').matchAll(/\S+/g)]
    .map((m) => ({ at: m.index, end: m.index + m[0].length, str: m[0] }));

  const out = [];
  for (let i = 0; i < raw.length; i += 1) {
    let { str } = raw[i];
    const { at } = raw[i];
    let { end } = raw[i];
    // Join across as many breaks as the typesetter managed to make.
    while (str.endsWith('-') && raw[i + 1]) {
      i += 1;
      str = str.slice(0, -1) + raw[i].str;
      end = raw[i].end;
    }
    const cleaned = norm(str);
    if (cleaned) out.push({ norm: cleaned, at, end });
  }
  return out;
}
