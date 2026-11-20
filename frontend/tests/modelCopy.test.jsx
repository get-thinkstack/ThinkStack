/**
 * Nothing ships a language model (2026-08-31), so no screen may say one does.
 *
 * A first-run note promising "it works right away" sends a new user to
 * Summarize, which then has no model to run on.
 */
import { describe, it, expect } from 'vitest';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import FirstRunNote from '../src/components/FirstRunNote';
import ModelImport from '../src/components/ModelImport';

const CLAIMS_A_BUNDLED_MODEL = /includes a small model|included model|included one|bundled model/i;

async function markup(element) {
  const el = document.createElement('div');
  document.body.appendChild(el);
  const root = createRoot(el);
  await act(async () => { root.render(element); });
  const html = el.textContent;
  act(() => root.unmount());
  el.remove();
  return html;
}

describe('model copy after models stopped shipping', () => {
  it('the first-run note does not claim a model is included', async () => {
    localStorage.clear();
    const text = await markup(<FirstRunNote onOpenBench={() => {}} />);
    expect(text).not.toMatch(CLAIMS_A_BUNDLED_MODEL);
    expect(text).toMatch(/Bench/);
  });

  it('the import dialog does not promise a bundled fallback', async () => {
    const text = await markup(
      <ModelImport tasks={['general']} onImport={() => {}} onClose={() => {}} busy={false} error="" />,
    );
    expect(text).not.toMatch(CLAIMS_A_BUNDLED_MODEL);
  });
});
