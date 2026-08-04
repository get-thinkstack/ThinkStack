import { describe, it, expect } from 'vitest';
import { markChunks, locateQuote } from '../src/components/litgraph/highlight';

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

  it('marks theme keywords where they appear', () => {
    const m = markChunks(chunks, { theme: { keywords: ['retrieval'] } });
    expect(m.get('a').has('theme')).toBe(true);
    expect(m.has('b')).toBe(false);
  });

  it('lets one chunk carry every reason at once', () => {
    const m = markChunks(chunks, {
      hits: [{ chunk_id: 'a' }],
      claims: [{ supporting_text: 'contrastive pretraining improves retrieval' }],
      theme: { keywords: ['pretraining'] },
    });
    expect([...m.get('a')].sort()).toEqual(['claim', 'match', 'theme']);
  });

  it('marks nothing when there is nothing to mark', () => {
    expect(markChunks(chunks).size).toBe(0);
    expect(markChunks(chunks, { claims: [{}], theme: { keywords: [] } }).size).toBe(0);
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
