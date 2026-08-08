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

/**
 * A real press: down AND up, the way a mouse or a finger produces one.
 *
 * It used to dispatch only pointerdown, which is why these tests stayed green
 * through a bug that made the feature actively harmful -- collapsing on the
 * press slid the page out from under the button being held, so the sidebar
 * closed and the click never landed. A half-gesture cannot show that. The
 * collapse is now applied after the gesture ends, so the flush matters too.
 */
const press = async (node) => {
  node.dispatchEvent(new Event('pointerdown', { bubbles: true, cancelable: true }));
  window.dispatchEvent(new Event('pointerup', { bubbles: true }));
  await flush();
};

/** let the deferred collapse run: it is a macrotask, so a microtask is too early. */
const flush = () => new Promise((r) => setTimeout(r, 0));

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
    await press(el.querySelector('.main-content'));
    expect(shellStore.isCollapsed()).toBe(true);
  });

  it('a press on something DEEP inside the page still collapses it', async () => {
    // the failure mode of the old approach: only blessed handlers counted
    await mountApp();
    const main = el.querySelector('.main-content');
    const deep = main.querySelector('button, input, a, div') || main;
    await press(deep);
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
    await press(child);
    expect(shellStore.isCollapsed()).toBe(true);
  });
});

describe('the chrome is not "the page"', () => {
  it('using the sidebar does NOT collapse it', async () => {
    // otherwise the nav would fold itself away the instant you touched it
    await mountApp();
    const sidebar = el.querySelector('.sidebar');
    expect(sidebar, 'no sidebar rendered').not.toBeNull();
    await press(sidebar);
    expect(shellStore.isCollapsed()).toBe(false);
  });

  it('the nav links do not collapse it either', async () => {
    await mountApp();
    const link = el.querySelector('.sidebar-nav .nav-link');
    if (link) await press(link);
    expect(shellStore.isCollapsed()).toBe(false);
  });
});

describe('what the collapse is worth', () => {
  it('an automatic collapse is still not remembered', async () => {
    await mountApp();
    await press(el.querySelector('.main-content'));
    expect(shellStore.isCollapsed()).toBe(true);
    expect(localStorage.getItem('ts-sidebar-collapsed')).toBeNull();
  });

  it('the peek button brings it back', async () => {
    await mountApp();
    await press(el.querySelector('.main-content'));
    expect(shellStore.isCollapsed()).toBe(true);
    el.querySelector('.sidebar-peek').click();
    expect(shellStore.isCollapsed()).toBe(false);
  });

  // The undo has to survive the action it was undoing. You reopen the nav in
  // order to use the page, so collapsing again on the next press made bringing
  // it back worth exactly one click -- and it read as the button not working.
  it('bringing it back is not undone by the next press', async () => {
    await mountApp();
    await press(el.querySelector('.main-content'));
    el.querySelector('.sidebar-peek').click();

    await press(el.querySelector('.main-content'));
    expect(shellStore.isCollapsed()).toBe(false);
  });

  // ...but only for as long as you are on the screen you reopened it for.
  it('the automatic collapse resumes after navigating', async () => {
    await mountApp();
    await press(el.querySelector('.main-content'));
    el.querySelector('.sidebar-peek').click();

    shellStore.releaseFocus();   // what ReleaseFocusOnNavigate does on a route change
    await press(el.querySelector('.main-content'));
    expect(shellStore.isCollapsed()).toBe(true);
  });
});

describe('the collapse must not eat the press that caused it', () => {
  // The bug: collapsing on pointerdown slides the page 220px left over 180ms
  // while the button is still held, so mouseup lands somewhere else and the
  // browser never concludes a click. The sidebar shut and the action did
  // nothing -- "both simultaneously" was exactly what did not happen.
  //
  // jsdom has no layout, so the shift itself cannot be reproduced here. What
  // CAN be asserted is the property that makes the shift harmless: the sidebar
  // does not move until the gesture is over.

  it('does not collapse while the button is still down', async () => {
    await mountApp();
    const main = el.querySelector('.main-content');
    main.dispatchEvent(new Event('pointerdown', { bubbles: true, cancelable: true }));
    expect(shellStore.isCollapsed(), 'collapsed mid-press').toBe(false);
  });

  it('collapses once the gesture ends', async () => {
    await mountApp();
    await press(el.querySelector('.main-content'));
    expect(shellStore.isCollapsed()).toBe(true);
  });

  it('runs the action FIRST and collapses after', async () => {
    await mountApp();
    const main = el.querySelector('.main-content');
    const order = [];

    const btn = document.createElement('button');
    btn.addEventListener('click', () => order.push('action'));
    main.appendChild(btn);
    shellStore.subscribe(() => {
      if (shellStore.isCollapsed() && order.at(-1) !== 'collapse') order.push('collapse');
    });

    btn.dispatchEvent(new Event('pointerdown', { bubbles: true, cancelable: true }));
    window.dispatchEvent(new Event('pointerup', { bubbles: true }));
    btn.dispatchEvent(new Event('click', { bubbles: true }));
    await flush();

    expect(order).toEqual(['action', 'collapse']);
  });

  it('a cancelled pointer still collapses, since no click is coming', async () => {
    await mountApp();
    el.querySelector('.main-content')
      .dispatchEvent(new Event('pointerdown', { bubbles: true, cancelable: true }));
    window.dispatchEvent(new Event('pointercancel', { bubbles: true }));
    expect(shellStore.isCollapsed()).toBe(true);
  });

  it('a queued collapse does not fire after the pin is set', async () => {
    // press, then hit the logo before releasing: the explicit expand must win,
    // not be undone a tick later by the collapse the press had queued.
    await mountApp();
    el.querySelector('.main-content')
      .dispatchEvent(new Event('pointerdown', { bubbles: true, cancelable: true }));
    shellStore.toggleSidebar();          // logo: expand + pin
    shellStore.toggleSidebar();          // logo again: collapse, unpinned
    shellStore.releaseFocus();           // navigation clears everything
    window.dispatchEvent(new Event('pointerup', { bubbles: true }));
    await flush();
    expect(shellStore.isCollapsed()).toBe(false);
  });
});
