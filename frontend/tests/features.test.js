/**
 * The feature registry: the one place a feature is described.
 *
 * These are integrity checks, not behaviour tests. The registry's whole value is
 * that nav, routes and the brand mark are generated from it, which means a
 * malformed entry does not fail loudly -- it produces a nav link to nowhere, or
 * a route with no page, or a logo that silently falls back. Each of those looks
 * like a styling bug and gets debugged as one.
 */

import { describe, it, expect } from 'vitest';
import { createElement } from 'react';
import { createRoot } from 'react-dom/client';
import { FEATURES, featureForPath, markFor } from '../src/features';
import { StackMark } from '../src/components/marks';

/** mount a component and hand back the DOM it produced. */
async function renderToDom(type, props) {
  const el = document.createElement('div');
  const root = createRoot(el);
  await new Promise((resolve) => {
    root.render(createElement(type, props));
    setTimeout(resolve, 20);
  });
  const html = el.innerHTML;
  const svg = el.querySelector('svg');
  const stroke = svg?.getAttribute('stroke');
  root.unmount();
  return { html, hasSvg: Boolean(svg), stroke };
}

describe('every feature is completely declared', () => {
  it.each(FEATURES)('$id has everything the shell renders from', (f) => {
    expect(f.id, 'id').toBeTruthy();
    expect(f.path, 'path').toMatch(/^\//);
    expect(f.label, 'label').toBeTruthy();
    expect(f.icon, 'nav icon').toBeTruthy();
    expect(f.Component, 'page component').toBeTruthy();
  });

  it('ids are unique', () => {
    const ids = FEATURES.map((f) => f.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('paths are unique', () => {
    const paths = FEATURES.map((f) => f.path);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it('only the root route is exact-match', () => {
    // "/" prefixes every other path, so without `end` it would match them all
    // and the nav would show Library as active everywhere.
    for (const f of FEATURES) {
      if (f.path === '/') expect(f.end).toBe(true);
      else expect(f.end).toBeFalsy();
    }
  });
});

describe('resolving a url to a feature', () => {
  it.each(FEATURES)('$path resolves to $id', (f) => {
    expect(featureForPath(f.path)?.id).toBe(f.id);
  });

  it('a nested path resolves to its parent feature', () => {
    // Scribe grows /write/<project>/<file> when it gets a file tree. The mark
    // must not fall back to the default the moment a file is opened.
    expect(featureForPath('/write/abc123')?.id).toBe('write');
    expect(featureForPath('/write/abc123/fig1.png')?.id).toBe('write');
  });

  it('root does not swallow every other path', () => {
    expect(featureForPath('/bench')?.id).toBe('bench');
    expect(featureForPath('/litgraph')?.id).toBe('litgraph');
  });

  it('an unknown path resolves to nothing rather than guessing', () => {
    expect(featureForPath('/nope')).toBeNull();
  });
});

describe('the brand mark follows the feature', () => {
  it.each(FEATURES)('$id renders an actual glyph', async (f) => {
    // Asserted by rendering rather than by inspecting the value: lucide's icons
    // are forwardRef objects, not plain functions, so a typeof check would call
    // a perfectly good component broken. What matters is that an svg comes out.
    const { hasSvg } = await renderToDom(markFor(f), { size: 18 });
    expect(hasSvg, `${f.id} rendered no svg`).toBe(true);
  });

  it('marks inherit their colour so the shell sets the ink once', async () => {
    // .brand-logo-icon and .sidebar-peek set `color`; a mark that hardcoded its
    // stroke would ignore that and could render invisibly on the lime chip.
    const { stroke } = await renderToDom(StackMark, { size: 18 });
    expect(stroke).toBe('currentColor');
  });

  it('falls back to a feature icon when no mark is declared', () => {
    const litgraph = FEATURES.find((f) => f.id === 'litgraph');
    expect(markFor(litgraph)).toBe(litgraph.icon);
  });

  it('an explicit mark wins over the icon', () => {
    const library = FEATURES.find((f) => f.id === 'library');
    expect(markFor(library)).toBe(StackMark);
    expect(markFor(library)).not.toBe(library.icon);
  });

  it('an unknown route keeps the house mark rather than rendering nothing', () => {
    expect(markFor(null)).toBe(StackMark);
    expect(markFor(featureForPath('/nope'))).toBe(StackMark);
  });

  it('distinct features are visually distinguishable', () => {
    // the point of the whole exercise: the logo must actually change
    const marks = FEATURES.map(markFor);
    expect(new Set(marks).size).toBe(marks.length);
  });
});

describe('a page declares whether it is a document or a workspace', () => {
  // One max-width: 1400px applied to every screen. Right for reading, wrong for
  // working: on a 1920px window Scribe's three panes were squeezed into 1400
  // with dead space beside them, so the dividers looked broken when they were
  // only out of room. Two beta checks -- "the panes can be dragged" -- would
  // have failed for every tester on a wide monitor.

  it('the workspaces are the ones built out of panes', () => {
    const fills = FEATURES.filter((f) => f.fills).map((f) => f.id);
    expect(fills.sort()).toEqual(['litgraph', 'write']);
  });

  it('the reading pages keep a measure', () => {
    // prose set 1900px wide is unreadable; this is not an oversight
    for (const id of ['library', 'bench']) {
      expect(FEATURES.find((f) => f.id === id).fills).toBeFalsy();
    }
  });

  it('every feature resolves from its own path', () => {
    // MainRegion looks the feature up by pathname, so a path that does not
    // resolve silently loses the workspace width rather than erroring
    for (const f of FEATURES) {
      expect(featureForPath(f.path), `no feature for ${f.path}`).toBeTruthy();
      expect(featureForPath(f.path).id).toBe(f.id);
    }
  });
});
