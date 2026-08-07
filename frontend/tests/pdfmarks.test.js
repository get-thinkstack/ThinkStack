/**
 * The pdf reader's testable half.
 *
 * Rectangles are measured in the browser now, with a DOM Range over pdf.js's
 * own text layer -- the only way to get them right mid-word, since pdf.js hands
 * back one item per typeset run with a single width and no per-glyph metrics.
 * Estimating sub-item positions by character count put highlights through the
 * middle of words ("tween their m"), which reads as a bug rather than a style.
 *
 * What stays here, and stays tested, is deciding WHAT to look for and WHERE in
 * the page's text it is. Measuring is the browser's job and needs no test.
 */

import { describe, it, expect } from 'vitest';
import { findSpan, targetsFor } from '../src/components/litgraph/pdfmarks';

const PAGE = 'Earlier work is limited. '
  + 'They rely on engineered features that Kearns showed to be brittle. '
  + 'We do not.';

describe('findSpan', () => {
  const slice = (span) => (span ? PAGE.slice(span.from, span.to) : null);

  it('locates a sentence that appears verbatim', () => {
    const span = findSpan(PAGE, 'They rely on engineered features that Kearns showed to be brittle.');
    expect(slice(span)).toBe('They rely on engineered features that Kearns showed to be brittle.');
  });

  it('locates it through case and punctuation differences', () => {
    const span = findSpan(PAGE, 'they rely on ENGINEERED features, that Kearns showed to be brittle');
    expect(slice(span)).toContain('engineered features that Kearns showed to be brittle');
  });

  // The pdf breaks a word across a line and the extracted chunk does not, so
  // the two texts disagree on exactly the words that matter.
  it('locates a run the pdf hyphenated across a line break', () => {
    const hyphenated = 'They rely on engineered fea- tures that Kearns showed to be brittle.';
    const span = findSpan(hyphenated, 'engineered features that Kearns showed');
    expect(hyphenated.slice(span.from, span.to)).toBe('engineered fea- tures that Kearns showed');
  });

  it('starts and ends on the words that matched, not on the window', () => {
    const span = findSpan(PAGE, 'engineered features that Kearns');
    expect(slice(span)).toBe('engineered features that Kearns');
  });

  it('refuses to guess when the target is not on this page', () => {
    expect(findSpan(PAGE, 'a completely different matter of taxonomy and naming')).toBe(null);
  });

  it('refuses an empty target or an empty page', () => {
    expect(findSpan(PAGE, '')).toBe(null);
    expect(findSpan('', 'engineered features')).toBe(null);
  });
});

/**
 * Narrowing is the whole point of the span carrying a quote.
 *
 * Marking the chunk washed two columns of the page yellow, which told the
 * reader nothing. The chunk locates the page; the quote locates the sentence.
 */
describe('targetsFor', () => {
  const chunks = [{
    chunk_id: 'a',
    metadata: { page_number: 3 },
    text: 'Dense retrieval has become standard. Contrastive pretraining improves quality.',
  }];
  const span = (kind, quote) => new Map([['a', [{ kind, quote }]]]);

  it('looks for the sentence the quote came from, on the chunk\'s page', () => {
    const [t] = targetsFor(chunks, span('claim', 'contrastive methods improve quality'));
    expect(t).toMatchObject({
      kind: 'claim',
      chunkId: 'a',
      page: 3,
      text: 'Contrastive pretraining improves quality.',
    });
  });

  it('looks for the whole chunk when the span carries no quote', () => {
    const [t] = targetsFor(chunks, span('match', null));
    expect(t.text).toBe(chunks[0].text);
  });

  // Better a broad highlight than none: the claim is still in this chunk, we
  // just cannot say which sentence.
  it('falls back to the whole chunk when the quote locates no sentence', () => {
    const [t] = targetsFor(chunks, span('claim', 'an unrelated matter of taxonomy'));
    expect(t.text).toBe(chunks[0].text);
  });

  it('gives one passage one colour when it is several things at once', () => {
    const both = new Map([['a', [
      { kind: 'theme', quote: 'contrastive' },
      { kind: 'match', quote: 'contrastive' },
    ]]]);
    expect(targetsFor(chunks, both).map((t) => t.kind)).toEqual(['match']);
  });

  // A chunk with no recorded page has to be looked for on every page: a missing
  // page number is the chunker's gap, not a reason to drop the mark.
  it('leaves the page open when the chunk never recorded one', () => {
    const loose = [{ chunk_id: 'a', text: 'Dense retrieval has become standard.' }];
    expect(targetsFor(loose, span('match', null))[0].page).toBe(null);
  });

  it('looks for nothing when nothing is marked', () => {
    expect(targetsFor(chunks, new Map())).toEqual([]);
    expect(targetsFor(null, span('claim', 'contrastive'))).toEqual([]);
  });
});
