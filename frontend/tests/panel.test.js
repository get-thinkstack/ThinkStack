import { describe, it, expect } from 'vitest';
import { clampPanel, neighbours, nearestFurthest } from '../src/components/litgraph/panel';

describe('clampPanel', () => {
  it('will not go narrower than the reader stays readable at', () => {
    expect(clampPanel(100, 1600)).toBe(280);
  });

  // The map is the point of the page. Whatever you drag, it keeps half.
  it('never lets the panel take more than half the window', () => {
    expect(clampPanel(1400, 1600)).toBe(800);
  });

  it('passes a sane width through untouched', () => {
    expect(clampPanel(420, 1600)).toBe(420);
  });

  // On a narrow window the floor and the ceiling cross. The ceiling has to
  // win, or the panel is wider than the window it sits in.
  it('gives the ceiling the last word when the window is smaller than the floor', () => {
    expect(clampPanel(400, 500)).toBe(250);
  });
});

describe('neighbours', () => {
  const edges = [
    { source: 'a', target: 'b', weight: 0.42 },
    { source: 'c', target: 'a', weight: 0.88 },
    { source: 'b', target: 'c', weight: 0.5 },
  ];

  it('reads an edge from either end, and returns the other paper', () => {
    expect(neighbours('a', edges)).toEqual([
      { id: 'c', weight: 0.88 },
      { id: 'b', weight: 0.42 },
    ]);
  });

  it('puts the strongest link first, since that is the one worth reading next', () => {
    expect(neighbours('c', edges).map((n) => n.id)).toEqual(['a', 'b']);
  });

  it('says nothing rather than guessing for an unlinked paper', () => {
    expect(neighbours('z', edges)).toEqual([]);
    expect(neighbours('a', undefined)).toEqual([]);
  });
});

describe('nearestFurthest', () => {
  // Positions are the server's PCA projection, normalised 0..1.
  const nodes = [
    { doc_id: 'a', x: 0.1, y: 0.1 },
    { doc_id: 'near', x: 0.15, y: 0.1 },
    { doc_id: 'mid', x: 0.5, y: 0.5 },
    { doc_id: 'far', x: 0.9, y: 0.9 },
  ];

  it('names the closest and the most distant paper in the projection', () => {
    const r = nearestFurthest(nodes[0], nodes);
    expect(r.near.doc_id).toBe('near');
    expect(r.far.doc_id).toBe('far');
  });

  it('never compares a paper with itself', () => {
    const r = nearestFurthest(nodes[2], nodes);
    expect(r.near.doc_id).not.toBe('mid');
    expect(r.far.doc_id).not.toBe('mid');
  });

  // One paper has no layout to explain -- PCA over a single point says nothing.
  it('returns null when there is nothing to compare against', () => {
    expect(nearestFurthest(nodes[0], [nodes[0]])).toBe(null);
  });

  // With exactly one other paper, near and far are the same paper, and
  // "closest to X, furthest from X" is nonsense. There is no far.
  it('has no furthest paper when only one other exists', () => {
    const r = nearestFurthest(nodes[0], [nodes[0], nodes[1]]);
    expect(r.near.doc_id).toBe('near');
    expect(r.far).toBe(null);
  });
});
