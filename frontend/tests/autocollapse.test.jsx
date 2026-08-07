/**
 * "ANY action in those windows should collapse the sidebar."
 *
 * The first attempt at this hooked chosen handlers in each feature -- opening a
 * paper, opening a project, running a Bench mutation. It worked, and it was
 * still wrong: everything NOT on that list did nothing, so most of Bench and
 * Library felt broken while the code and its tests were entirely green. The
 * list was the bug.
 *
 * So the shell now watches its own content area, and these tests assert the
 * property rather than an inventory: a press anywhere in the page collapses,
 * and the chrome around it does not.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { shellStore, __resetShell } from '../src/utils/shell';

vi.mock('../src/utils/api', () => {
  const snapshot = {
    models: [], routing: {}, tasks: ['general'], budget_gb: 3,
    discovered: [], catalog: [], download: { status: 'idle' }, upgrade: null,
  };
  return {
    registryApi: { get: vi.fn(async () => snapshot), import: vi.fn(), update: vi.fn(), remove: vi.fn() },
    systemApi: {
      diagnose: vi.fn(async () => ({ machine: {}, engine: {}, limits: {}, advice: [] })),
      health: vi.fn(async () => ({ llm: { status: 'connected' } })),
      jobs: vi.fn(async () => ({})),
    },
    documentsApi: { list: vi.fn(async () => ({ documents: [] })), get: vi.fn(), delete: vi.fn() },
    papersApi: { list: vi.fn(async () => ({ projects: [] })) },
    graphApi: { get: vi.fn(async () => ({ nodes: [], edges: [], gaps: [] })) },
    modelsApi: { downloadStatus: vi.fn(), download: vi.fn(), cancelDownload: vi.fn() },
    encryptionApi: {}, analysisApi: {}, gapsApi: {}, searchApi: {}, hfApi: {},
    useLlmBusy: () => ({ busy: false, label: '' }),
    useJobs: () => ({ active: false, label: '', done: 0, total: 0, queued: 0, error: '' }),
    llmBusyStore: { subscribe: () => () => {}, getSnapshot: () => ({ count: 0, label: '' }) },
  };
});
vi.mock('../src/utils/updater', () => ({
  checkForUpdatesInteractive: vi.fn(), APP_VERSION: '0.0.0-test',
}));

let el;
async function mountApp() {
  const { default: App } = await import('../src/App');
  el = document.createElement('div');
  document.body.appendChild(el);
  const root = createRoot(el);
  await new Promise((r) => { root.render(<StrictMode><App /></StrictMode>); setTimeout(r, 120); });
  return root;
}

/** a real press, the way a mouse or a finger produces one. */
const press = (node) =>
  node.dispatchEvent(new Event('pointerdown', { bubbles: true, cancelable: true }));

beforeEach(() => {
  localStorage.clear();
  __resetShell();
  document.body.innerHTML = '';
});

describe('any press inside the page collapses the sidebar', () => {
  it('starts expanded', async () => {
    await mountApp();
    expect(shellStore.isCollapsed()).toBe(false);
  });

  it('a press on the content area collapses it', async () => {
    await mountApp();
    press(el.querySelector('.main-content'));
    expect(shellStore.isCollapsed()).toBe(true);
  });

  it('a press on something DEEP inside the page still collapses it', async () => {
    // the failure mode of the old approach: only blessed handlers counted
    await mountApp();
    const main = el.querySelector('.main-content');
    const deep = main.querySelector('button, input, a, div') || main;
    press(deep);
    expect(shellStore.isCollapsed()).toBe(true);
  });

  it('survives a child that stops propagation', async () => {
    // several rows stop propagation on their delete buttons; a bubbling
    // listener would never hear those, which is why this is a capture handler.
    await mountApp();
    const main = el.querySelector('.main-content');
    const child = document.createElement('button');
    child.addEventListener('pointerdown', (e) => e.stopPropagation());
    main.appendChild(child);
    press(child);
    expect(shellStore.isCollapsed()).toBe(true);
  });
});

describe('the chrome is not "the page"', () => {
  it('using the sidebar does NOT collapse it', async () => {
    // otherwise the nav would fold itself away the instant you touched it
    await mountApp();
    const sidebar = el.querySelector('.sidebar');
    expect(sidebar, 'no sidebar rendered').not.toBeNull();
    press(sidebar);
    expect(shellStore.isCollapsed()).toBe(false);
  });

  it('the nav links do not collapse it either', async () => {
    await mountApp();
    const link = el.querySelector('.sidebar-nav .nav-link');
    if (link) press(link);
    expect(shellStore.isCollapsed()).toBe(false);
  });
});

describe('what the collapse is worth', () => {
  it('an automatic collapse is still not remembered', async () => {
    await mountApp();
    press(el.querySelector('.main-content'));
    expect(shellStore.isCollapsed()).toBe(true);
    expect(localStorage.getItem('ts-sidebar-collapsed')).toBeNull();
  });

  it('the peek button brings it back', async () => {
    await mountApp();
    press(el.querySelector('.main-content'));
    expect(shellStore.isCollapsed()).toBe(true);
    el.querySelector('.sidebar-peek').click();
    expect(shellStore.isCollapsed()).toBe(false);
  });
});
