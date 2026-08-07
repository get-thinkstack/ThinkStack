/**
 * The application shell's own state, separate from any feature that asks it to
 * change.
 *
 * Why a store rather than `useState` in App: a feature that wants more room --
 * LitGraph opening a paper, Scribe opening a project -- sits three or four
 * components below the shell. Threading a setter down to it would mean every
 * intermediate component accepting and forwarding a prop it does not use, and
 * every new feature repeating that. Here a component at any depth calls
 * `requestFocus()` and nothing in between has to know.
 *
 * This is the same `useSyncExternalStore` idiom as `llmBusyStore` in api.js,
 * deliberately: one pattern for cross-component state, not two.
 *
 * ── The two collapse states, and why they are not one ──
 *
 * `userCollapsed` is a decision. You clicked the logo because you wanted more
 * room, and that should survive quitting the app, exactly as the theme does.
 *
 * `focus` is a consequence. You opened a paper and the shell got out of the way.
 *
 * Collapsing them into one persisted flag would mean opening a single paper
 * teaches the app to launch collapsed forever, which nobody asked for. So the
 * automatic one is session-only and is forgotten on reload, while the
 * deliberate one persists. The sidebar is hidden when EITHER is set, and the
 * logo clears BOTH -- it is the master switch, so it can always undo whatever
 * a feature did.
 */

const SIDEBAR_KEY = 'ts-sidebar-collapsed';

function readPersisted() {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === '1';
  } catch {
    return false; // private mode / storage disabled
  }
}

function persist(collapsed) {
  try {
    localStorage.setItem(SIDEBAR_KEY, collapsed ? '1' : '0');
  } catch {
    /* storage unavailable; the choice just will not survive a restart */
  }
}

// `focus` starts false on every load on purpose -- see the note above.
let state = { userCollapsed: readPersisted(), focus: false };

const listeners = new Set();
const emit = () => listeners.forEach((l) => l());

function set(next) {
  // Reference equality is what useSyncExternalStore compares, so only publish a
  // new object when something actually changed. Emitting an equal-but-new object
  // on every action would re-render the whole shell for nothing.
  if (next.userCollapsed === state.userCollapsed && next.focus === state.focus) return;
  state = next;
  emit();
}

export const shellStore = {
  subscribe(cb) {
    listeners.add(cb);
    return () => listeners.delete(cb);
  },

  getSnapshot() {
    return state;
  },

  /** true when the sidebar is hidden, for either reason. */
  isCollapsed() {
    return state.userCollapsed || state.focus;
  },

  /**
   * The logo. The master switch, and the only thing that persists.
   *
   * Expanding clears `focus` as well as `userCollapsed`: without that, a user
   * who collapsed by opening a paper would click the logo and see nothing
   * happen, because the automatic flag would still be holding it shut.
   */
  toggleSidebar() {
    if (shellStore.isCollapsed()) {
      persist(false);
      set({ userCollapsed: false, focus: false });
    } else {
      persist(true);
      set({ ...state, userCollapsed: true });
    }
  },

  /**
   * A feature asking for room -- opening a paper, a node, a project.
   *
   * Never persisted, and deliberately not an error to call twice.
   */
  requestFocus() {
    set({ ...state, focus: true });
  },

  /** Give the room back. Called on navigation; harmless if focus is not set. */
  releaseFocus() {
    set({ ...state, focus: false });
  },
};

/** Test seam: drop persisted state and start clean. Not used by the app. */
export function __resetShell() {
  try {
    localStorage.removeItem(SIDEBAR_KEY);
  } catch { /* nothing to clear */ }
  state = { userCollapsed: false, focus: false };
  emit();
}
