import { describe, it, expect } from 'vitest';
import { clampPanel } from '../src/components/litgraph/panel';

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
