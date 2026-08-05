/**
 * Ask the user for a file on their own disk, and get back a real PATH.
 *
 * This has to be a native dialog. The UI is served over http://127.0.0.1:8000,
 * so a plain `<input type="file">` hands back a File object with no filesystem
 * path -- the browser deliberately withholds it. Registering a model needs the
 * path, because the whole point is to REFERENCE weights where they already sit
 * rather than copy several gigabytes; going through an upload would mean
 * pushing a 7 GB file through the backend to land it somewhere we then have to
 * store twice.
 *
 * Outside the desktop shell (./scripts/dev.sh in a browser) there is no dialog
 * to open, so `pickModelFile` reports that and the caller falls back to a typed
 * path. That fallback is not dead weight: it is also the escape hatch for a
 * user whose file lives somewhere a dialog makes awkward to reach.
 */

/** true only inside the tauri desktop webview. */
export function inTauri() {
  return typeof window !== 'undefined' &&
    (Boolean(window.__TAURI_INTERNALS__) || Boolean(window.__TAURI__));
}

/**
 * Open a native file dialog filtered to gguf weights.
 *
 * @returns {Promise<{path: string|null, reason: string}>}
 *   `path` is null when the user cancelled or no dialog is available; `reason`
 *   distinguishes those, because "you cancelled" needs no message and "there is
 *   no picker here" needs to reveal the manual input.
 */
export async function pickModelFile() {
  if (!inTauri()) return { path: null, reason: 'unsupported' };

  try {
    const { open } = await import('@tauri-apps/plugin-dialog');
    const selected = await open({
      multiple: false,
      directory: false,
      title: 'Choose a GGUF model',
      filters: [{ name: 'GGUF model', extensions: ['gguf'] }],
    });

    // v2 returns a string path, or null on cancel. Older shapes returned an
    // object with `.path`; tolerate both so a plugin bump cannot break import.
    if (!selected) return { path: null, reason: 'cancelled' };
    const path = typeof selected === 'string' ? selected : selected.path;
    return path ? { path, reason: 'ok' } : { path: null, reason: 'cancelled' };
  } catch (err) {
    // A denied capability lands here. Falling back to the typed path keeps
    // import working rather than presenting a button that silently does
    // nothing -- the failure mode the updater button already taught us about.
    console.warn('[filePicker] native dialog unavailable:', err);
    return { path: null, reason: 'unsupported' };
  }
}
