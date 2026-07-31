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
 * @returns {Promise<'updating' | 'current' | 'offline' | 'blocked'
 *                   | 'install-failed' | 'restart-needed' | 'unsupported'
 *                   | 'error'>}
 */
export async function checkForUpdatesInteractive() {
  if (!inTauri()) return 'unsupported';

  let update;
  try {
    const { check } = await import('@tauri-apps/plugin-updater');
    update = await check();
  } catch (err) {
    // Distinguish the reasons, because "error" told the user nothing and was
    // shown for the most common case of all: being on the newest version but
    // temporarily offline.
    const msg = String(err?.message ?? err);
    console.warn('[updater] check failed:', msg);

    // No manifest published for this channel yet. There is genuinely nothing
    // to update to, which is "up to date" from where the user is standing.
    if (/404|not found/i.test(msg)) return 'current';

    // Offline, or the release host is unreachable. Not an application fault,
    // and an offline-first app being offline is not an error worth alarming
    // anyone about.
    if (/network|fetch|dns|timed? ?out|connect|unreachable|tls|certificate/i.test(msg)) {
      return 'offline';
    }

    // A denied plugin call means the capability does not cover this origin.
    // That was a real bug: the UI is served from http://127.0.0.1:8000, which
    // Tauri treats as remote content, and the capability only covered
    // tauri://localhost, so every press of the button threw.
    if (/not allowed|forbidden|permission|capabilit/i.test(msg)) return 'blocked';

    return 'error';
  }

  if (!update) return 'current';

  const accepted = await defaultConfirm({ version: update.version });
  if (!accepted) return 'current';

  try {
    // The bundle's signature is verified against the public key in
    // tauri.conf.json before anything is written. A tampered or truncated
    // download fails here, leaving the installed version untouched.
    await update.downloadAndInstall();
  } catch (err) {
    console.warn('[updater] install failed:', err);
    // Deliberately NOT relaunching. The installed version is still the working
    // one, so staying on it is the safe outcome; relaunching after a failed
    // install is how you turn a failed update into a broken application.
    return 'install-failed';
  }

  try {
    const { relaunch } = await import('@tauri-apps/plugin-process');
    await relaunch();
  } catch {
    // Installed but could not restart automatically. Nothing is broken; the
    // new version is live on the next manual start.
    return 'restart-needed';
  }
  return 'updating';
}
