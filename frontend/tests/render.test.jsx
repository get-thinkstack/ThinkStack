/**
 * Every route must render. This exists because a blank white page shipped
 * twice: the build succeeds (the JSX is valid), and React then throws at
 * render time on a reference that no longer exists, leaving an empty <div>
 * and an error only the browser console ever sees.
 *
 * A build passing is not evidence the app starts.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter } from 'react-router-dom';

// the backend is not running in a test; every call resolves to something shaped
// like the real payload so components render their populated state too.
vi.mock('../src/utils/api', () => {
  const snapshot = {
    models: [], routing: {}, tasks: ['general', 'analysis', 'gap_analysis', 'latex_writer'],
    budget_gb: 3.3, discovered: [], catalog: [], download: { status: 'idle' },
    upgrade: null,
  };
  return {
    registryApi: { get: vi.fn(async () => snapshot), import: vi.fn(), update: vi.fn(), remove: vi.fn() },
    systemApi: { diagnose: vi.fn(async () => ({ machine: {}, engine: {}, limits: {}, advice: [] })),
                 health: vi.fn(async () => ({})), jobs: vi.fn(async () => ({})) },
    modelsApi: { download: vi.fn(), cancelDownload: vi.fn() },
    hfApi: { search: vi.fn(), repo: vi.fn(), download: vi.fn() },
    documentsApi: { list: vi.fn(async () => ({ documents: [] })) },
    graphApi: { get: vi.fn(async () => ({ nodes: [], edges: [], themes: [], gaps: [] })) },
    analysisApi: { history: vi.fn(async () => ({ runs: [] })) },
    gapsApi: { history: vi.fn(async () => ({ runs: [] })) },
    papersApi: { list: vi.fn(async () => ({ projects: [] })) },
    searchApi: {}, encryptionApi: {},
    useJobs: () => ({ active: false, label: '', done: 0, total: 0, queued: 0, error: '' }),
    useLlmBusy: () => ({ busy: false, label: '' }),
    llmBusyStore: { subscribe: () => () => {}, getSnapshot: () => ({ count: 0, label: '' }) },
  };
});

async function renderRoute(path, Component) {
  const el = document.createElement('div');
  document.body.appendChild(el);
  const errors = [];
  const spy = vi.spyOn(console, 'error').mockImplementation((...a) => errors.push(a.join(' ')));
  const root = createRoot(el);
  await new Promise((resolve) => {
    root.render(
      <StrictMode><MemoryRouter initialEntries={[path]}><Component /></MemoryRouter></StrictMode>,
    );
    setTimeout(resolve, 60);
  });
  const html = el.innerHTML;
  root.unmount();
  spy.mockRestore();
  return { html, errors };
}

describe('the application shell renders', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  it('App mounts, which is where the blank page actually came from', async () => {
    // Mounted WITHOUT a router wrapper: App provides its own BrowserRouter.
    // This is the gap that let the bug through -- the tests below mount page
    // components directly, so a missing import in App.jsx was invisible to
    // them while being the exact thing that produced a white screen.
    const { default: App } = await import('../src/App');
    const el = document.createElement('div');
    document.body.appendChild(el);
    const errors = [];
    const spy = vi.spyOn(console, 'error').mockImplementation((...a) => errors.push(a.join(' ')));
    const root = createRoot(el);
    await new Promise((resolve) => {
      root.render(<StrictMode><App /></StrictMode>);
      setTimeout(resolve, 80);
    });
    const html = el.innerHTML;
    root.unmount();
    spy.mockRestore();

    const real = errors.filter((e) => !/not wrapped in act|validateDOMNesting/i.test(e));
    expect(real, `App threw:\n${real.join('\n')}`).toHaveLength(0);
    expect(html.length, 'App rendered an EMPTY page').toBeGreaterThan(200);
    // the shell itself, not just a stray div
    expect(html, 'the sidebar did not render').toContain('sidebar');
  });
});

describe('every screen renders without throwing', () => {
  beforeEach(() => { document.body.innerHTML = ''; });

  const screens = [
    ['Bench', '/bench', () => import('../src/components/Bench')],
    ['Library', '/', () => import('../src/components/Library')],
    ['Scribe', '/write', () => import('../src/components/Scribe')],
    ['LitGraph', '/litgraph', () => import('../src/components/LitGraph')],
  ];

  for (const [name, path, load] of screens) {
    it(`${name} produces markup and logs no React error`, async () => {
      const mod = await load();
      const { html, errors } = await renderRoute(path, mod.default);
      const real = errors.filter((e) => !/not wrapped in act|validateDOMNesting/i.test(e));
      expect(real, `${name} threw:\n${real.join('\n')}`).toHaveLength(0);
      expect(html.length, `${name} rendered an EMPTY page`).toBeGreaterThan(30);
    });
  }
});
