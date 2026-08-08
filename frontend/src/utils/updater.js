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

/** human-readable byte size, for a download measured in hundreds of megabytes. */
function mb(bytes) {
  return `${Math.round(bytes / 1024 / 1024)} MB`;
}

/**
 * Fallback prompt, for the browser dev build only.
 *
 * The desktop app injects its own dialog, because THIS DOES NOT WORK THERE and
 * failed in the worst available way. Tauri's webview does not implement
 * `confirm()`: it returns `undefined` rather than a boolean, so `if (!accepted)`
 * read a missing feature as "the user said no" and the updater reported "Up to
 * date" while an update sat there uninstalled. Silent, and indistinguishable
 * from working.
 *
 * The codebase already knew -- ConfirmDialog exists for exactly this, and both
 * FileTree and Scribe were fixed for it. This module was missed because it is
 * the one prompt no test could reach: it only appears when a real release is
 * newer than the running build.
 *
 * So `null` is returned for "could not ask", which is a different fact from
 * "asked, told no", and the caller is no longer allowed to confuse them.
 *
 * The size is not a detail. ThinkStack ships the model weights inside the
 * bundle, so an update is ~900 MB, not the few MB people expect from an "update
 * now?" prompt. Someone on a metered or slow connection needs to know that
 * before saying yes, and someone who says yes needs to understand why it then
 * takes several minutes.
 */
function defaultConfirm({ version, size }) {
  const weight = size ? ` (about ${mb(size)})` : '';
  const answer = typeof window.confirm === 'function' ? window.confirm(
    `ThinkStack ${version} is available${weight}.\n\n` +
    `The download includes the local model, so it is large and may take a few ` +
    `minutes. Your papers and data are kept.\n\n` +
    `Install it now and restart?`
  ) : undefined;
  return typeof answer === 'boolean' ? answer : null;
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
 * `confirm` is injected so the desktop build can ask with a real dialog. It may
 * be async, and returning `null` means "could not ask" -- never "no".
 *
 * @returns {Promise<'updating' | 'current' | 'declined' | 'offline' | 'blocked'
 *                   | 'install-failed' | 'restart-needed' | 'unsupported'
 *                   | 'error'>}
 */
export async function checkForUpdatesInteractive({ onProgress, confirm = defaultConfirm } = {}) {
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

  const accepted = await confirm({
    version: update.version,
    size: update.contentLength,
  });

  // Three outcomes, not two. Collapsing them is the bug this whole path had:
  // "could not ask" was reported as "up to date", so the update never happened
  // and nothing ever said so.
  if (accepted === null || accepted === undefined) {
    console.warn('[updater] no way to ask the user; not installing');
    return 'error';
  }
  // Declined is not "current" either -- there IS a newer version, and telling
  // someone they are up to date right after they pressed Not now is a lie the
  // next press cannot correct.
  if (accepted === false) return 'declined';

  try {
    // The bundle's signature is verified against the public key in
    // tauri.conf.json before anything is written. A tampered or truncated
    // download fails here, leaving the installed version untouched.
    //
    // The progress callback is not decoration. The bundle carries the model
    // weights, so this transfers ~900 MB: without it the button sat on
    // "Checking..." for several minutes with no output, which is
    // indistinguishable from a hang, and the first person to try it reasonably
    // concluded the updater was broken.
    let total = 0;
    let done = 0;
    await update.downloadAndInstall((event) => {
      switch (event.event) {
        case 'Started':
          total = event.data?.contentLength ?? 0;
          done = 0;
          onProgress?.({ phase: 'downloading', done, total, percent: 0 });
          break;
        case 'Progress':
          done += event.data?.chunkLength ?? 0;
          onProgress?.({
            phase: 'downloading',
            done,
            total,
            // No total means no percentage; report bytes rather than a
            // fabricated one.
            percent: total ? Math.min(100, Math.round((done / total) * 100)) : null,
          });
          break;
        case 'Finished':
          onProgress?.({ phase: 'installing', done: total, total, percent: 100 });
          break;
        default:
          break;
      }
    });
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
