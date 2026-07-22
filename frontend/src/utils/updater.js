/**
 * auto-update check for the tauri desktop build.
 *
 * on launch the app asks github releases (via the signed `latest.json`
 * manifest configured in src-tauri/tauri.conf.json) whether a newer version
 * exists. if so, the user is asked to install it; on accept the new bundle is
 * downloaded, verified against the public key, installed, and the app relaunches.
 *
 * this is a no-op in the browser / web dev build (`./scripts/dev.sh`) — the
 * tauri plugins only exist inside the desktop shell, so we bail out early when
 * the tauri runtime is absent. the plugin modules are imported dynamically so
 * the web bundle never pulls them in.
 */

/** true only when running inside the tauri desktop webview. */
function inTauri() {
  return typeof window !== 'undefined' &&
    (Boolean(window.__TAURI_INTERNALS__) || Boolean(window.__TAURI__));
}

/**
 * check for an update and, if the user accepts, install it and relaunch.
 *
 * safe to call unconditionally on app start: it returns immediately in the
 * web build and never throws (failures are logged, not surfaced), so a
 * flaky network or an offline machine can't block the app from loading.
 *
 * @param {(info: {version: string, notes?: string}) => boolean | Promise<boolean>} [confirmInstall]
 *   optional callback to decide whether to install a found update. defaults to
 *   a native confirm() dialog. return true to install.
 */
export async function checkForUpdates(confirmInstall) {
  if (!inTauri()) return;

  try {
    const { check } = await import('@tauri-apps/plugin-updater');
    const update = await check();
    if (!update) return; // already on the latest version

    const decide = confirmInstall || defaultConfirm;
    const accepted = await decide({ version: update.version, notes: update.body });
    if (!accepted) return;

    // download + install; the bundle's signature is verified against the
    // pubkey in tauri.conf.json before anything is applied.
    await update.downloadAndInstall();

    const { relaunch } = await import('@tauri-apps/plugin-process');
    await relaunch();
  } catch (err) {
    // never let an update failure break app startup — just log it.
    console.warn('[updater] update check failed:', err);
  }
}

/** default UX: a blocking confirm() with the new version number. */
function defaultConfirm({ version }) {
  return window.confirm(
    `ThinkStack ${version} is available.\n\n` +
    `Install it now and restart? Your papers and data are kept.`
  );
}
