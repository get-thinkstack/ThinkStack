import { describe, it, expect } from 'vitest';
import {
  markChunks, markSpans, locateQuote, bestSentence,
} from '../src/components/litgraph/highlight';

const chunks = [
  { chunk_id: 'a', text: 'We show that contrastive pretraining improves retrieval quality.' },
  { chunk_id: 'b', text: 'Unrelated boilerplate about the funding acknowledgements.' },
];
const claimed = (supporting_text) => markChunks(chunks, { claims: [{ supporting_text }] });

describe('markChunks', () => {
  it('marks a search hit exactly, by chunk id', () => {
    const m = markChunks(chunks, { hits: [{ chunk_id: 'b' }] });
    expect([...m.get('b')]).toEqual(['match']);
    expect(m.has('a')).toBe(false);
  });

  // supporting_text is written by the model, not quoted from the paper, so
  // punctuation and case will not line up even when the sentence is right.
  it('finds a claim whose supporting text survives punctuation and case', () => {
    expect(claimed('Contrastive pretraining improves retrieval!').get('a').has('claim')).toBe(true);
  });

  // The real failure mode. Checked against the library on this machine, no
  // claim's supporting_text appeared verbatim in the paper it came from --
  // the model paraphrases. Matching whole phrases found nothing at all.
  it('finds a claim that paraphrases the paper instead of quoting it', () => {
    const m = claimed('Contrastive methods improve the quality of retrieval during pretraining');
    expect(m.get('a').has('claim')).toBe(true);
  });

  it('marks one chunk per claim, not every chunk sharing a word', () => {
    const m = claimed('Contrastive pretraining improves retrieval quality');
    expect(m.size).toBe(1);
  });

  it('does not guess when the supporting text is nowhere in the paper', () => {
    expect(claimed('an entirely different sentence about something else').has('a')).toBe(false);
  });

  // "We show" is in half of every paper ever written.
  it('ignores a supporting text too short to be distinctive', () => {
    expect(claimed('We show').size).toBe(0);
  });

  // A gap's evidence is written under the same instruction as a claim's
  // supporting text -- short phrases, not quotations -- so it is located the
  // same way rather than by a second matcher tuned differently.
  it('marks the passage a gap cites as evidence', () => {
    const m = markChunks(chunks, {
      gaps: [{ evidence: ['contrastive pretraining improves retrieval'] }],
    });
    expect(m.get('a').has('gap')).toBe(true);
    expect(m.has('b')).toBe(false);
  });

  // Unlike a claim, which has one source passage by definition, a gap's two
  // phrases can rest on different parts of the paper.
  it('marks every passage a gap rests on, not just the first', () => {
    const m = markChunks(chunks, {
      gaps: [{
        evidence: [
          'contrastive pretraining improves retrieval',
          'boilerplate about the funding acknowledgements',
        ],
      }],
    });
    expect(m.get('a').has('gap')).toBe(true);
    expect(m.get('b').has('gap')).toBe(true);
  });

  it('does not guess a gap whose evidence is nowhere in the paper', () => {
    const m = markChunks(chunks, { gaps: [{ evidence: ['something else entirely, elsewhere'] }] });
    expect(m.size).toBe(0);
  });

  it('survives a gap with no evidence at all', () => {
    expect(markChunks(chunks, { gaps: [{}, { evidence: [] }] }).size).toBe(0);
  });

  it('marks theme keywords where they appear', () => {
    const m = markChunks(chunks, { theme: { keywords: ['retrieval'] } });
    expect(m.get('a').has('theme')).toBe(true);
    expect(m.has('b')).toBe(false);
  });

  it('lets one chunk carry every reason at once', () => {
    const m = markChunks(chunks, {
      hits: [{ chunk_id: 'a' }],
      claims: [{ supporting_text: 'contrastive pretraining improves retrieval' }],
      gaps: [{ evidence: ['contrastive pretraining improves retrieval'] }],
      theme: { keywords: ['pretraining'] },
    });
    expect([...m.get('a')].sort()).toEqual(['claim', 'gap', 'match', 'theme']);
  });

  it('marks nothing when there is nothing to mark', () => {
    expect(markChunks(chunks).size).toBe(0);
    expect(markChunks(chunks, { claims: [{}], theme: { keywords: [] } }).size).toBe(0);
  });
});

/**
 * markChunks answers "why is this passage worth looking at". markSpans answers
 * that and "which phrase said so", which is what lets the pdf reader narrow a
 * mark to one sentence instead of painting the block.
 */
describe('markSpans', () => {
  it('carries the supporting text that located a claim', () => {
    const quote = 'contrastive pretraining improves retrieval';
    const spans = markSpans(chunks, { claims: [{ supporting_text: quote }] });
    expect(spans.get('a')).toEqual([{ kind: 'claim', quote }]);
  });

  it('carries each evidence phrase on its own gap span', () => {
    const spans = markSpans(chunks, {
      gaps: [{
        evidence: [
          'contrastive pretraining improves retrieval',
          'boilerplate about the funding acknowledgements',
        ],
      }],
    });
    expect(spans.get('a')[0].quote).toBe('contrastive pretraining improves retrieval');
    expect(spans.get('b')[0].quote).toBe('boilerplate about the funding acknowledgements');
  });

  it('carries the keyword that matched, not the whole theme', () => {
    const spans = markSpans(chunks, { theme: { keywords: ['nowhere', 'retrieval'] } });
    expect(spans.get('a')).toEqual([{ kind: 'theme', quote: 'retrieval' }]);
  });

  // A hit IS a chunk, so it has no narrower phrase of its own -- but the words
  // you typed are exactly what "matched your search" should point at.
  it('carries the search query on a match', () => {
    const spans = markSpans(chunks, { hits: [{ chunk_id: 'a' }], query: 'retrieval quality' });
    expect(spans.get('a')).toEqual([{ kind: 'match', quote: 'retrieval quality' }]);
  });

  it('leaves a match unnarrowed when there was no query', () => {
    const spans = markSpans(chunks, { hits: [{ chunk_id: 'a' }] });
    expect(spans.get('a')).toEqual([{ kind: 'match', quote: null }]);
  });
});

/**
 * A chunk is a whole block of a page. Marking one washes two columns of the pdf
 * yellow, which says nothing -- so the chunk locates the page and this locates
 * the sentence on it. Null means "no narrower answer", and the caller keeps the
 * whole chunk: a broadly highlighted claim beats an unhighlighted one.
 */
describe('bestSentence', () => {
  const chunk = 'Dense retrieval has become standard. '
    + 'Contrastive pretraining improves retrieval quality on every benchmark we tried. '
    + 'We leave multilingual evaluation to future work.';

  it('picks the sentence a paraphrased claim came from', () => {
    const s = bestSentence(chunk, 'Contrastive methods improve the quality of retrieval');
    expect(s).toBe('Contrastive pretraining improves retrieval quality on every benchmark we tried.');
  });

  // A theme keyword is one or two words -- far too few for the word overlap
  // that locates a claim to say anything at all. It appears verbatim, though.
  it('finds the sentence containing a keyword too short to score', () => {
    expect(bestSentence(chunk, 'multilingual'))
      .toBe('We leave multilingual evaluation to future work.');
  });

  it('narrows to one sentence, not the block around it', () => {
    const s = bestSentence(chunk, 'dense retrieval is standard');
    expect(s).toBe('Dense retrieval has become standard.');
  });

  // The caller falls back to the whole chunk on null, so this is the difference
  // between "highlight the block" and "highlight nothing".
  it('gives up rather than guessing when the quote is nowhere in the chunk', () => {
    expect(bestSentence(chunk, 'an entirely unrelated matter of taxonomy')).toBe(null);
  });

  // Academic prose is full of these, and a split at "e.g." cuts the sentence in
  // half -- so half of it never gets highlighted. Seen on the real library.
  it('does not mistake an abbreviation for the end of a sentence', () => {
    const c = 'Earlier work is limited. '
      + 'They rely on engineered features (e.g. molecular fingerprints) that Kearns et al. '
      + 'showed to be brittle. We do not.';
    expect(bestSentence(c, 'engineered features are brittle'))
      .toBe('They rely on engineered features (e.g. molecular fingerprints) '
        + 'that Kearns et al. showed to be brittle.');
  });

  it('has nothing to narrow when the chunk is a single sentence', () => {
    expect(bestSentence('Contrastive pretraining improves retrieval.', 'contrastive pretraining'))
      .toBe(null);
  });

  it('survives an empty quote and an empty chunk', () => {
    expect(bestSentence(chunk, '')).toBe(null);
    expect(bestSentence(chunk, undefined)).toBe(null);
    expect(bestSentence('', 'contrastive pretraining')).toBe(null);
  });
});

describe('locateQuote', () => {
  it('finds the chunk a claim rests on', () => {
    expect(locateQuote(chunks, 'Contrastive pretraining improves retrieval.')).toBe('a');
  });

  // A claim that cannot be highlighted must not offer to jump to itself.
  it('agrees with markChunks about what cannot be found', () => {
    const missing = 'an entirely different sentence about something else';
    expect(locateQuote(chunks, missing)).toBe(null);
    expect(markChunks(chunks, { claims: [{ supporting_text: missing }] }).size).toBe(0);
  });

  it('refuses a quote too short to be distinctive', () => {
    expect(locateQuote(chunks, 'We show')).toBe(null);
  });
});
