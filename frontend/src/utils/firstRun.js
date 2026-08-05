/**
 * Whether the first-run model note has been shown yet.
 *
 * A separate file from the component purely so the component file exports
 * only a component: React Fast Refresh cannot hot-reload a module that mixes
 * components with plain functions, and the lint rule that enforces this is the
 * reason this module exists.
 */

const SEEN_KEY = 'thinkstack.firstRun.modelNote';

/** Record that the note has been seen, so it never returns. */
export function markFirstRunNoteSeen() {
  try {
    localStorage.setItem(SEEN_KEY, new Date().toISOString());
  } catch {
    /* private mode: worst case it is shown once more */
  }
}

/** Has it already been shown on this install? */
export function firstRunNoteSeen() {
  try {
    return Boolean(localStorage.getItem(SEEN_KEY));
  } catch {
    return false;   // storage unavailable -> show it; a repeat beats silence
  }
}
