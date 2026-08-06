/**
 * The shell store: what collapses the sidebar, and what is remembered.
 *
 * The bug this guards against is not a crash. It is that opening one paper
 * teaches the app to launch collapsed forever -- a setting the user never
 * chose, changed by an action that had nothing to do with settings, and with no
 * obvious way to work out what did it. That is why "the user asked" and "a
 * feature asked" are two flags rather than one, and most of what follows is
 * checking they stay separate.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import { shellStore, __resetShell } from '../src/utils/shell';

const KEY = 'ts-sidebar-collapsed';

beforeEach(() => {
  localStorage.clear();
  __resetShell();
});

describe('the two reasons a sidebar is shut', () => {
  it('starts open on a fresh install', () => {
    expect(shellStore.isCollapsed()).toBe(false);
  });

  it('the logo collapses it, and that is remembered', () => {
    shellStore.toggleSidebar();
    expect(shellStore.isCollapsed()).toBe(true);
    expect(localStorage.getItem(KEY)).toBe('1');
  });

  it('a feature can collapse it too', () => {
    shellStore.requestFocus();
    expect(shellStore.isCollapsed()).toBe(true);
  });

  it('but a feature collapsing it is NOT remembered', () => {
    shellStore.requestFocus();
    expect(shellStore.isCollapsed()).toBe(true);
    // the whole point: nothing was written, so a restart opens expanded
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it('releasing focus reopens it', () => {
    shellStore.requestFocus();
    shellStore.releaseFocus();
    expect(shellStore.isCollapsed()).toBe(false);
  });

  it('releasing focus does NOT reopen one the user shut deliberately', () => {
    shellStore.toggleSidebar();     // user wants it closed
    shellStore.requestFocus();      // a feature also asks
    shellStore.releaseFocus();      // the feature is done
    expect(shellStore.isCollapsed()).toBe(true);   // the user's choice stands
  });
});

describe('the logo is the master switch', () => {
  it('reopens a sidebar that a FEATURE closed', () => {
    // Without clearing focus here the logo would appear broken: you click it,
    // and nothing moves, because the automatic flag is still holding it shut.
    shellStore.requestFocus();
    shellStore.toggleSidebar();
    expect(shellStore.isCollapsed()).toBe(false);
  });

  it('and having done so, a later release does not re-collapse it', () => {
    shellStore.requestFocus();
    shellStore.toggleSidebar();
    shellStore.releaseFocus();
    expect(shellStore.isCollapsed()).toBe(false);
  });
});

describe('persistence', () => {
  it('a deliberate collapse survives a reload', async () => {
    shellStore.toggleSidebar();
    expect(localStorage.getItem(KEY)).toBe('1');

    // re-import with storage already set: what a real reload does
    vi.resetModules();
    const fresh = await import('../src/utils/shell?reload=1');
    expect(fresh.shellStore.isCollapsed()).toBe(true);
  });

  it('an automatic collapse does not', async () => {
    shellStore.requestFocus();
    vi.resetModules();
    const fresh = await import('../src/utils/shell?reload=2');
    expect(fresh.shellStore.isCollapsed()).toBe(false);
  });

  it('survives storage being unavailable', () => {
    const spy = vi.spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => { throw new Error('denied'); });
    // private mode: the choice cannot be saved, but must still take effect
    expect(() => shellStore.toggleSidebar()).not.toThrow();
    expect(shellStore.isCollapsed()).toBe(true);
    spy.mockRestore();
  });
});

describe('subscribers', () => {
  it('are notified when the state changes', () => {
    const seen = vi.fn();
    const stop = shellStore.subscribe(seen);
    shellStore.requestFocus();
    expect(seen).toHaveBeenCalledTimes(1);
    stop();
  });

  it('are NOT notified when nothing actually changed', () => {
    // useSyncExternalStore compares snapshots by reference, so publishing a new
    // object for a no-op would re-render the whole shell for nothing.
    shellStore.requestFocus();
    const seen = vi.fn();
    const stop = shellStore.subscribe(seen);
    shellStore.requestFocus();   // already focused
    expect(seen).not.toHaveBeenCalled();
    stop();
  });

  it('stop hearing about it after unsubscribing', () => {
    const seen = vi.fn();
    shellStore.subscribe(seen)();
    shellStore.requestFocus();
    expect(seen).not.toHaveBeenCalled();
  });

  it('hand back a stable snapshot while unchanged', () => {
    expect(shellStore.getSnapshot()).toBe(shellStore.getSnapshot());
  });
});
