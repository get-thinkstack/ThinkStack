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
 *
 * ── Why undoing has to stick ──
 *
 * `pinned` is the third state, and it exists because the master switch was not
 * one. Any press inside the page collapses the sidebar, so bringing it back
 * used to last exactly one click: you clicked the logo, then clicked the thing
 * you opened the nav to reach, and it shut again on the way. The undo could not
 * survive the action it was undoing.
 *
 * So an explicit expand pins it open, and `requestFocus` is a no-op until
 * navigation clears the pin. "Any action collapses it" still holds -- it is
 * simply not allowed to overrule someone who just said otherwise. Not
 * persisted: it is a statement about this visit to this screen.
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

// `focus` and `pinned` start false on every load on purpose -- see the note
// above.
let state = { userCollapsed: readPersisted(), focus: false, pinned: false };

const listeners = new Set();
const emit = () => listeners.forEach((l) => l());

// An armed-but-not-yet-applied pointer collapse. At most one: a second press
// before the first resolves is the same gesture as far as the sidebar cares.
let pendingPointerFocus = null;

function disarmPointerFocus() {
  if (!pendingPointerFocus) return;
  const { onUp, onCancel, timer } = pendingPointerFocus;
  window.removeEventListener('pointerup', onUp, true);
  window.removeEventListener('pointercancel', onCancel, true);
  if (timer) clearTimeout(timer);
  pendingPointerFocus = null;
}

function set(next) {
  // Reference equality is what useSyncExternalStore compares, so only publish a
  // new object when something actually changed. Emitting an equal-but-new object
  // on every action would re-render the whole shell for nothing.
  if (next.userCollapsed === state.userCollapsed
    && next.focus === state.focus
    && next.pinned === state.pinned) return;
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
      set({ userCollapsed: false, focus: false, pinned: true });
    } else {
      persist(true);
      set({ ...state, userCollapsed: true, pinned: false });
    }
  },

  /**
   * A feature asking for room -- opening a paper, a node, a project.
   *
   * Never persisted, and deliberately not an error to call twice. Ignored while
   * pinned: someone who just reopened the nav is not asking for it to shut on
   * their next click.
   */
  requestFocus() {
    if (state.pinned) return;
    set({ ...state, focus: true });
  },

  /**
   * The same request, but from a POINTER, and therefore deferred to the end of
   * the gesture.
   *
   * Collapsing during `pointerdown` ate the press that caused it. The sidebar
   * is 220px wide and the page is offset by it, so collapsing slides everything
   * 220px left over 180ms -- starting while the button is still held down. A
   * click is not an event the page sends; it is a conclusion the browser draws
   * when mousedown and mouseup land on the same element. Move the element
   * between them and the conclusion is never drawn, so the sidebar closed and
   * the button did nothing. The handler was never wrong; it was never called.
   *
   * `pointerdown` is still the right trigger -- LitGraph's lasso is a drag that
   * may never produce a click, and children calling stopPropagation are why the
   * listener is in the capture phase. Only the CONSEQUENCE moves.
   *
   * setTimeout and not queueMicrotask: microtasks drain after each callback,
   * which is still ahead of mouseup and click. A macrotask is the first point
   * that is reliably after the browser has finished the whole input sequence.
   *
   * A cancelled pointer collapses at once -- no click is coming, so there is
   * nothing left to protect.
   */
  requestFocusFromPointer() {
    if (state.pinned || state.focus || pendingPointerFocus) return;

    const finish = () => {
      disarmPointerFocus();
      shellStore.requestFocus();
    };
    const onUp = () => {
      // the gesture is over; let the click that follows it be delivered first
      if (pendingPointerFocus) pendingPointerFocus.timer = setTimeout(finish, 0);
    };
    pendingPointerFocus = { onUp, onCancel: finish, timer: null };
    window.addEventListener('pointerup', onUp, true);
    window.addEventListener('pointercancel', finish, true);
  },

  /**
   * Give the room back. Called on navigation; harmless if focus is not set.
   *
   * Also ends the pin. Navigating is leaving the screen the nav was reopened
   * for, so the automatic behaviour resumes on the next one.
   */
  releaseFocus() {
    disarmPointerFocus();  // a queued collapse must not outlive the screen
    set({ ...state, focus: false, pinned: false });
  },
};

/** Test seam: drop persisted state and start clean. Not used by the app. */
export function __resetShell() {
  try {
    localStorage.removeItem(SIDEBAR_KEY);
  } catch { /* nothing to clear */ }
  disarmPointerFocus();
  state = { userCollapsed: false, focus: false, pinned: false };
  emit();
}
