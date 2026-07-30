/**
 * Update check for the tauri desktop build -- user-initiated only.
 *
 * ThinkStack's premise is that nothing leaves the device. An update check is a
 * network request, so it happens ONLY when the user clicks "Update app"; there
 * is deliberately no check on launch. It carries no user data either way, but an
 * offline-first app that quietly phones home on every start is not offline-first
 * in any sense a user would recognise.
 *
 * When accepted, the new bundle is downloaded, verified against the public key
 * in src-tauri/tauri.conf.json, installed, and the app relaunches.
 *
 * No-op in the browser / web dev build (`./scripts/dev.sh`): the tauri plugins
 * exist only inside the desktop shell, so we bail out when the runtime is
 * absent. The plugin modules are imported dynamically so the web bundle never
 * pulls them in.
 */

/** true only when running inside the tauri desktop webview. */
function inTauri() {
  return typeof window !== 'undefined' &&
    (Boolean(window.__TAURI_INTERNALS__) || Boolean(window.__TAURI__));
}

/** default UX: a blocking confirm() with the new version number. */
function defaultConfirm({ version }) {
  return window.confirm(
    `ThinkStack ${version} is available.\n\n` +
    `Install it now and restart? Your papers and data are kept.`
  );
}

/**
 * The version this build reports, baked in from src-tauri/tauri.conf.json.
 *
 * Shown in the UI so a beta tester can say *which* build they hit a bug on
 * without hunting through a filename -- the single most common missing detail
 * in a bug report.
 */
export const APP_VERSION = typeof __APP_VERSION__ === 'string' ? __APP_VERSION__ : 'dev';

/**
 * Update check driven by a button rather than by app start.
 *
 * Every outcome reports something. Staying silent when there is no update is
 * indistinguishable from a broken button, so 'current' is a result the caller
 * is expected to show, not a no-op.
 *
 * @returns {Promise<'updating' | 'current' | 'unsupported' | 'error'>}
 */
export async function checkForUpdatesInteractive() {
  if (!inTauri()) return 'unsupported';

  try {
    const { check } = await import('@tauri-apps/plugin-updater');
    const update = await check();
    if (!update) return 'current';

    const accepted = await defaultConfirm({ version: update.version });
    if (!accepted) return 'current';

    await update.downloadAndInstall();
    const { relaunch } = await import('@tauri-apps/plugin-process');
    await relaunch();
    return 'updating';
  } catch (err) {
    console.warn('[updater] manual update check failed:', err);
    return 'error';
  }
}
