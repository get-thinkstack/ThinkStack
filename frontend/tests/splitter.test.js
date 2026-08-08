/**
 * "lol why can't i expand the read window the other way"
 *
 * Both resizable pages had the same class of bug, and it was never the drag
 * handling -- it was the arithmetic deciding where the drag is allowed to stop.
 * LitGraph capped its panel at half the window; Scribe capped its preview at
 * 70% while reserving a flat 320px for a layout that has THREE columns, so the
 * editor could be squeezed to a strip too narrow to write LaTeX in.
 *
 * The lesson both share: a limit should be stated in the pixels the other panes
 * actually need, never as a fraction of the window. A fraction is a guess that
 * gets worse as the screen gets smaller -- which is precisely when the limit
 * starts to matter.
 */

import { describe, it, expect } from 'vitest';
import { clampWidth } from '../src/utils/useSplitter';

// Scribe's real numbers, so these tests fail if the component's change
const EDITOR_MIN = 340;
const TREE = { min: 140, max: 420 };
const PREVIEW = { min: 260, max: 720 };

describe('clampWidth', () => {
  it('honours the floor and the ceiling', () => {
    const o = { ...TREE, reserve: 600, viewportW: 1600 };
    expect(clampWidth(50, o)).toBe(140);    // below the floor
    expect(clampWidth(300, o)).toBe(300);   // in range, untouched
    expect(clampWidth(9000, o)).toBe(420);  // above the ceiling
  });

  it('rounds, because a CSS pixel is not fractional', () => {
    expect(clampWidth(300.6, { ...TREE, reserve: 600, viewportW: 1600 })).toBe(301);
  });

  it('resizes in BOTH directions between the limits', () => {
    const o = { ...PREVIEW, max: 2000, reserve: 540, viewportW: 1600 };
    const wide = clampWidth(900, o);
    const narrow = clampWidth(400, o);
    expect(wide).toBe(900);
    expect(narrow).toBe(400);
    expect(wide).toBeGreaterThan(narrow);   // the grip actually moves both ways
  });

  it('leaves room for the other panes rather than a fraction of the window', () => {
    // 1280px laptop: the old rule was min(0.7 * 1280, 1280 - 320) = 896,
    // which left the editor 1280 - 896 - 200 = 184px. Unusable.
    const editorGets = (w) =>
      w - clampWidth(9000, { ...PREVIEW, max: 2000, reserve: 200 + EDITOR_MIN, viewportW: w }) - 200;
    expect(editorGets(1280)).toBeGreaterThanOrEqual(EDITOR_MIN);
    expect(editorGets(1600)).toBeGreaterThanOrEqual(EDITOR_MIN);
    expect(editorGets(2560)).toBeGreaterThanOrEqual(EDITOR_MIN);
  });

  it('asks the reserve at clamp time, so a resized sibling still counts', () => {
    // This is why reserve may be a function. The tree is itself draggable: with
    // it at 420 rather than its default 200, a fixed reserve would let the
    // preview take 220px that the editor needed.
    let treeW = 200;
    const o = { ...PREVIEW, max: 2000, reserve: () => treeW + EDITOR_MIN, viewportW: 1600 };
    const withNarrowTree = clampWidth(9000, o);
    treeW = 420;
    const withWideTree = clampWidth(9000, o);
    expect(withNarrowTree - withWideTree).toBe(220);
    expect(1600 - withWideTree - treeW).toBeGreaterThanOrEqual(EDITOR_MIN);
  });

  it('keeps the dragged pane usable when the window cannot satisfy both', () => {
    // 800px window, 540 reserved: the ceiling would fall to 260, which is the
    // floor. The floor wins -- a pane you cannot grab is worse than overflow.
    expect(clampWidth(9000, { ...PREVIEW, reserve: 540, viewportW: 800 })).toBe(260);
    expect(clampWidth(9000, { ...PREVIEW, reserve: 540, viewportW: 500 })).toBe(260);
  });

  it('accepts a ceiling computed from the window', () => {
    const o = { min: 260, max: (w) => w * 0.5, reserve: 0, viewportW: 1600 };
    expect(clampWidth(9000, o)).toBe(800);
  });
});
