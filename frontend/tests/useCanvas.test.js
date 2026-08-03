import { describe, it, expect } from 'vitest';
import { makeAlpha, lassoFar, gestureFor } from '../src/components/litgraph/useCanvas';

const m = (...ids) => new Map(ids.map((id) => [id, { score: 1 }]));

describe('makeAlpha', () => {
  it('dims everything that did not match, once a search is running', () => {
    const alpha = makeAlpha(m('a'), null, new Set());
    expect(alpha('a')).toBe(1);
    expect(alpha('b')).toBe(0.15);
  });

  it('leaves the scene alone when nothing is selected', () => {
    const alpha = makeAlpha(new Map(), null, new Set());
    expect(alpha('a')).toBe(1);
  });

  it('ranks focus above its neighbours above everything else', () => {
    const alpha = makeAlpha(new Map(), 'a', new Set(['b']));
    expect(alpha('a')).toBe(1);
    expect(alpha('b')).toBe(0.6);
    expect(alpha('c')).toBe(0.32);
  });

  // A search and a focus can be active at once; the search has to win, or a
  // node that did not match reads as merely "not adjacent" rather than "not a
  // result".
  it('lets a running search override the focus rules', () => {
    const alpha = makeAlpha(m('a'), 'b', new Set(['c']));
    expect(alpha('c')).toBe(0.15);
  });
});

describe('lassoFar', () => {
  const at = (x, y) => ({ x, y });

  it('drops points inside the threshold and keeps the ones outside', () => {
    expect(lassoFar(at(0, 0), at(3, 0), 1)).toBe(false);
    expect(lassoFar(at(0, 0), at(5, 0), 1)).toBe(true);
  });

  it('measures in screen pixels, not world units', () => {
    // Zoomed 4x in, 4 world units is 16 screen pixels: keep it.
    expect(lassoFar(at(0, 0), at(4, 0), 4)).toBe(true);
    // Zoomed out to a quarter, the same 4 units is 1 screen pixel: drop it.
    expect(lassoFar(at(0, 0), at(4, 0), 0.25)).toBe(false);
  });

  it('measures diagonally, not per axis', () => {
    expect(lassoFar(at(0, 0), at(3, 3), 1)).toBe(true);
  });
});

describe('gestureFor', () => {
  const empty = { closest: () => null };
  const node = { closest: (sel) => (sel === '.lg-node' ? {} : null) };
  const press = (target = empty, button = 0) => ({ target, button });

  it('selects on a plain drag, with no modifier held', () => {
    expect(gestureFor(press(), false)).toBe('lasso');
  });

  it('pans on space-drag and on middle-drag', () => {
    expect(gestureFor(press(), true)).toBe('pan');
    expect(gestureFor(press(empty, 1), false)).toBe('pan');
  });

  // A press on a node must reach the node's own click listener untouched --
  // starting a lasso there flashes a path that is then thrown away.
  it('leaves a press on a node alone, held modifier or not', () => {
    expect(gestureFor(press(node), false)).toBe('node');
    expect(gestureFor(press(node), true)).toBe('node');
  });

  it('ignores the right button, which belongs to the context menu', () => {
    expect(gestureFor(press(empty, 2), false)).toBe('none');
  });
});
