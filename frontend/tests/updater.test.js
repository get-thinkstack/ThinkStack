/**
 * Tests for the update path.
 *
 * This file exists because the frontend had no tests at all, and two bugs
 * shipped straight through as a result:
 *
 *   * downloadAndInstall() was called with no progress callback. The bundle
 *     carries the model weights, so that is a ~900 MB transfer during which
 *     the button read "Checking..." and nothing else. It was reported as
 *     "the update doesn't work" -- correctly, because it is indistinguishable
 *     from a hang.
 *   * every failure returned the same "error", so being offline on the newest
 *     version looked identical to a broken install.
 *
 * The tauri plugins only exist inside the desktop shell, so they are mocked at
 * the module boundary -- which is exactly where the real code imports them.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const check = vi.fn();
const relaunch = vi.fn();

vi.mock('@tauri-apps/plugin-updater', () => ({ check: (...a) => check(...a) }));
vi.mock('@tauri-apps/plugin-process', () => ({ relaunch: (...a) => relaunch(...a) }));

let checkForUpdatesInteractive;

beforeEach(async () => {
  vi.resetModules();
  check.mockReset();
  relaunch.mockReset();
  // pretend we are inside the desktop webview
  globalThis.window = globalThis.window || {};
  window.__TAURI_INTERNALS__ = {};
  window.confirm = vi.fn(() => true);
  ({ checkForUpdatesInteractive } = await import('../src/utils/updater.js'));
});

afterEach(() => {
  delete window.__TAURI_INTERNALS__;
});

/** an update object shaped like the plugin's, driving the progress callback. */
function fakeUpdate({ contentLength = 900 * 1024 * 1024, chunks = 3, fail = false } = {}) {
  return {
    version: '1.6.8',
    contentLength,
    downloadAndInstall: vi.fn(async (onEvent) => {
      if (fail) throw new Error('signature verification failed');
      onEvent?.({ event: 'Started', data: { contentLength } });
      for (let i = 0; i < chunks; i += 1) {
        onEvent?.({ event: 'Progress', data: { chunkLength: contentLength / chunks } });
      }
      onEvent?.({ event: 'Finished' });
    }),
  };
}

describe('progress reporting', () => {
  it('reports progress during the download', async () => {
    check.mockResolvedValue(fakeUpdate());
    const seen = [];
    await checkForUpdatesInteractive({ onProgress: (p) => seen.push(p) });

    expect(seen.length).toBeGreaterThan(0);
    expect(seen.some((p) => p.phase === 'downloading')).toBe(true);
  });

  it('reaches 100 percent and then reports installing', async () => {
    check.mockResolvedValue(fakeUpdate());
    const seen = [];
    await checkForUpdatesInteractive({ onProgress: (p) => seen.push(p) });

    expect(seen.at(-1)).toMatchObject({ phase: 'installing', percent: 100 });
  });

  it('percentages increase monotonically and never exceed 100', async () => {
    check.mockResolvedValue(fakeUpdate({ chunks: 10 }));
    const pct = [];
    await checkForUpdatesInteractive({ onProgress: (p) => pct.push(p.percent) });

    expect(Math.max(...pct)).toBeLessThanOrEqual(100);
    for (let i = 1; i < pct.length; i += 1) expect(pct[i]).toBeGreaterThanOrEqual(pct[i - 1]);
  });

  it('reports null rather than a fabricated percentage without a total', async () => {
    const u = fakeUpdate();
    u.downloadAndInstall = vi.fn(async (onEvent) => {
      onEvent?.({ event: 'Started', data: {} });          // no contentLength
      onEvent?.({ event: 'Progress', data: { chunkLength: 1024 } });
    });
    check.mockResolvedValue(u);
    const seen = [];
    await checkForUpdatesInteractive({ onProgress: (p) => seen.push(p) });

    expect(seen.find((p) => p.phase === 'downloading' && p.done > 0).percent).toBeNull();
  });

  it('works when no progress callback is supplied', async () => {
    check.mockResolvedValue(fakeUpdate());
    await expect(checkForUpdatesInteractive()).resolves.toBe('updating');
  });
});

describe('the size is shown before a ~900 MB download starts', () => {
  it('puts the megabyte figure in the confirmation', async () => {
    check.mockResolvedValue(fakeUpdate({ contentLength: 900 * 1024 * 1024 }));
    await checkForUpdatesInteractive();

    expect(window.confirm).toHaveBeenCalledTimes(1);
    expect(window.confirm.mock.calls[0][0]).toMatch(/900 MB/);
  });

  it('declining changes nothing and never downloads', async () => {
    const u = fakeUpdate();
    check.mockResolvedValue(u);
    window.confirm = vi.fn(() => false);

    await expect(checkForUpdatesInteractive()).resolves.toBe('current');
    expect(u.downloadAndInstall).not.toHaveBeenCalled();
  });
});

describe('outcomes are distinguishable', () => {
  it('no update available is reported, not silence', async () => {
    check.mockResolvedValue(null);
    await expect(checkForUpdatesInteractive()).resolves.toBe('current');
  });

  it('a missing manifest counts as up to date', async () => {
    check.mockRejectedValue(new Error('404 Not Found'));
    await expect(checkForUpdatesInteractive()).resolves.toBe('current');
  });

  it('being offline is not an error', async () => {
    check.mockRejectedValue(new Error('network error: failed to fetch'));
    await expect(checkForUpdatesInteractive()).resolves.toBe('offline');
  });

  it('a denied capability is reported as blocked', async () => {
    check.mockRejectedValue(new Error('url not allowed on the configured scope'));
    await expect(checkForUpdatesInteractive()).resolves.toBe('blocked');
  });

  it('anything else is a plain error', async () => {
    check.mockRejectedValue(new Error('something unexpected'));
    await expect(checkForUpdatesInteractive()).resolves.toBe('error');
  });

  it('outside the desktop shell it is unsupported', async () => {
    delete window.__TAURI_INTERNALS__;
    await expect(checkForUpdatesInteractive()).resolves.toBe('unsupported');
    expect(check).not.toHaveBeenCalled();
  });
});

describe('a failed install must not break the working app', () => {
  it('does NOT relaunch when the install fails', async () => {
    check.mockResolvedValue(fakeUpdate({ fail: true }));

    await expect(checkForUpdatesInteractive()).resolves.toBe('install-failed');
    expect(relaunch).not.toHaveBeenCalled();
  });

  it('reports restart-needed when the install worked but relaunch did not', async () => {
    check.mockResolvedValue(fakeUpdate());
    relaunch.mockRejectedValue(new Error('cannot relaunch'));

    await expect(checkForUpdatesInteractive()).resolves.toBe('restart-needed');
  });

  it('relaunches on success', async () => {
    check.mockResolvedValue(fakeUpdate());
    await expect(checkForUpdatesInteractive()).resolves.toBe('updating');
    expect(relaunch).toHaveBeenCalledTimes(1);
  });
});
