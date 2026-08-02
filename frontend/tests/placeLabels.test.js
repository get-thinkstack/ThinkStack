import { describe, it, expect } from 'vitest';
import { boxesHit, placeLabels } from '../src/components/litgraph/useCanvas';

const box = (x, y, w, h) => ({ x, y, w, h });

describe('boxesHit', () => {
  it('catches an overlap', () => {
    expect(boxesHit(box(0, 0, 10, 10), box(5, 5, 10, 10))).toBe(true);
  });

  it('lets boxes that only share an edge through', () => {
    // Titles sit shoulder to shoulder often enough that treating a shared
    // edge as a collision would hide labels with nothing wrong with them.
    expect(boxesHit(box(0, 0, 10, 10), box(10, 0, 10, 10))).toBe(false);
  });

  it('separates on either axis alone', () => {
    expect(boxesHit(box(0, 0, 10, 10), box(0, 11, 10, 10))).toBe(false);
    expect(boxesHit(box(0, 0, 10, 10), box(11, 0, 10, 10))).toBe(false);
  });
});

describe('placeLabels', () => {
  it('keeps labels that do not fight', () => {
    expect(placeLabels([
      { text: 'one', x: 0, y: 0 },
      { text: 'two', x: 500, y: 400 },
    ])).toEqual([true, true]);
  });

  it('drops the second of two labels on the same spot', () => {
    expect(placeLabels([
      { text: 'Attention Is All You Need', x: 100, y: 100 },
      { text: 'Attention Is All You Want', x: 100, y: 100 },
    ])).toEqual([true, false]);
  });

  it('gives the space to whoever is passed first', () => {
    // Draw order is priority order: theme labels are pushed before paper
    // titles, so a theme keeps its label when the two collide.
    const [theme, paper] = placeLabels([
      { text: 'Drug-Drug Interaction', x: 200, y: 200 },
      { text: 'A paper title here', x: 205, y: 202 },
    ]);
    expect(theme).toBe(true);
    expect(paper).toBe(false);
  });

  it('measures from the anchor, so centred labels reserve both sides', () => {
    // 'wide title text' is ~93px wide centred on x=100, so it spans ~53..146.
    // A label starting at x=60 is inside that; one at x=200 is not.
    expect(placeLabels([
      { text: 'wide title text', x: 100, y: 0 },
      { text: 'x', x: 60, y: 0 },
    ])).toEqual([true, false]);
    expect(placeLabels([
      { text: 'wide title text', x: 100, y: 0 },
      { text: 'x', x: 200, y: 0 },
    ])).toEqual([true, true]);
  });

  it('lets a label sit under another if the rows clear', () => {
    expect(placeLabels([
      { text: 'top row', x: 0, y: 0 },
      { text: 'next row', x: 0, y: 40 },
    ])).toEqual([true, true]);
  });
});
