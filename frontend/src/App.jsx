import { useState, useEffect, Suspense, useSyncExternalStore, createElement } from 'react';
import { BrowserRouter, Routes, Route, NavLink, useLocation, useNavigate, Navigate } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { Sun, Moon, RefreshCw, Check, AlertCircle } from 'lucide-react';
import { systemApi } from './utils/api';
import { checkForUpdatesInteractive, APP_VERSION } from './utils/updater';
// Every feature is declared once, here, and the nav / routes / brand mark are
// all rendered from it. The shell no longer names a single feature.
import { FEATURES, featureForPath, markFor } from './features';
import { shellStore } from './utils/shell';
// Eager, not lazy: it decides whether to render on first paint, and a
// lazy chunk would let the page settle before the note appears.
import FirstRunNote from './components/FirstRunNote';
import PageGuide from './components/PageGuide';
import ConfirmDialog from './components/ConfirmDialog';
import './index.css';

const THEME_KEY = 'ts-theme';

/** resolve the initial theme: stored choice wins, else follow the OS. */
function getInitialTheme() {
  try {
    const stored = localStorage.getItem(THEME_KEY);
    if (stored === 'light' || stored === 'dark') return { theme: stored, explicit: true };
  } catch {
    /* localStorage unavailable */
  }
  const prefersDark =
    typeof window !== 'undefined' &&
    window.matchMedia &&
    window.matchMedia('(prefers-color-scheme: dark)').matches;
  return { theme: prefersDark ? 'dark' : 'light', explicit: false };
}

/** spring fade+slide+blur applied to each routed page (Apple-like). */
const pageMotion = {
  initial: { opacity: 0, y: 16, filter: 'blur(6px)' },
  animate: { opacity: 1, y: 0, filter: 'blur(0px)' },
  exit: { opacity: 0, y: -12, filter: 'blur(6px)' },
  transition: { type: 'spring', stiffness: 260, damping: 30, mass: 0.7 },
};

function Page({ children }) {
  return <motion.div {...pageMotion}>{children}</motion.div>;
}

/** FirstRunNote needs the router, which only exists below BrowserRouter. */
function FirstRunBanner() {
  const navigate = useNavigate();
  return <FirstRunNote onOpenBench={() => navigate('/bench')} />;
}

function AnimatedRoutes() {
  const location = useLocation();
  return (
    <AnimatePresence mode="wait">
      {/* No spinner: a chunk off local disk arrives in a frame or two, and a
          spinner that flashes for one frame reads as a glitch. */}
      <Suspense fallback={null}>
        <Routes location={location} key={location.pathname}>
          {FEATURES.map(({ id, path, end, Component }) => (
            <Route key={id} path={path} end={end} element={<Page><Component /></Page>} />
          ))}
          {/* Search, Analysis and Gap Finder all became LitGraph. This is a
              desktop shell, so a stale deep link would otherwise be a dead end. */}
          <Route path="/search" element={<Navigate to="/litgraph" replace />} />
          <Route path="/analysis" element={<Navigate to="/litgraph" replace />} />
          <Route path="/gaps" element={<Navigate to="/litgraph" replace />} />
        </Routes>
      </Suspense>
    </AnimatePresence>
  );
}

/**
 * The brand glyph, which follows whichever feature is open.
 *
 * Lives in its own component because it needs `useLocation`, which only works
 * below <BrowserRouter>; App itself renders the router and so sits above it.
 */
function ActiveMark({ size }) {
  const { pathname } = useLocation();
  // createElement rather than <Mark />: the mark is LOOKED UP, not defined here,
  // and assigning it to a capitalised local reads to the linter as a component
  // declared during render -- which would remount on every navigation.
  return createElement(markFor(featureForPath(pathname)), { size });
}

/**
 * The "i" in the bottom-left corner, filled in from the active feature.
 *
 * Rendered once, here, so no page wires it up and no page can forget to. The
 * copy lives in features.js beside everything else that feature declares.
 */
function FeatureGuide() {
  const { pathname } = useLocation();
  const feature = featureForPath(pathname);
  if (!feature?.guide?.length) return null;

  return (
    <PageGuide label={`About ${feature.label}`}>
      {feature.summary && <p className="pg-title">{feature.summary}</p>}
      {feature.guide.map(([term, meaning]) => (
        <div key={term}><b>{term}</b> {meaning}</div>
      ))}
    </PageGuide>
  );
}

/**
 * Hand the sidebar back when the user moves between features.
 *
 * Without this, a sidebar collapsed by opening a paper would stay collapsed
 * after navigating to Bench, and the only way out would be the logo -- so an
 * automatic action would have quietly changed a setting the user never touched.
 * Releasing on navigation keeps the automatic collapse scoped to the thing that
 * asked for it. A deliberate collapse is unaffected: that lives in a separate
 * flag this does not clear.
 */
function ReleaseFocusOnNavigate() {
  const { pathname } = useLocation();
  useEffect(() => {
    shellStore.releaseFocus();
  }, [pathname]);
  return null;
}

/**
 * main application shell with sidebar navigation and routing.
 *
 * provides the layout, navigation, light/dark theming (follows the OS
 * until the user toggles), and local llm runtime status.
 */
export default function App() {
  const [llmStatus, setLlmStatus] = useState('checking');

  // The sidebar is hidden for either of two reasons -- the user asked, or a
  // feature asked for room -- and only the first is remembered between runs.
  // Both live in shellStore so a component at any depth can request the second
  // without a setter threaded down to it. See utils/shell.js.
  const shell = useSyncExternalStore(
    shellStore.subscribe, shellStore.getSnapshot, shellStore.getSnapshot,
  );
  const collapsed = shell.userCollapsed || shell.focus;
  const toggleSidebar = shellStore.toggleSidebar;

  const [{ theme, explicit }, setThemeState] = useState(getInitialTheme);

  // apply the active theme to <html> so every token switches
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // No update check on launch, deliberately. ThinkStack's premise is that
  // nothing leaves the device; reaching out to GitHub unprompted on every start
  // contradicts that even though the request carries no user data. Updates are
  // entirely user-initiated via the sidebar button below.
  const [updateState, setUpdateState] = useState('idle');
  // Percentage of the update download, or null when nothing is downloading.
  // The bundle carries the model weights, so this is a ~900 MB transfer that
  // takes minutes; with no progress the button looked frozen.
  const [updatePercent, setUpdatePercent] = useState(null);

  // The update prompt, as a real dialog rather than window.confirm.
  //
  // Tauri's webview does not implement confirm(): it returns undefined, which
  // the updater read as "no". Pressing Update app found the new version, was
  // told nothing, declined on the user's behalf and reported "Up to date". The
  // rest of the app had already learnt this -- see ConfirmDialog -- and this
  // was the one prompt left calling it.
  const [updatePrompt, setUpdatePrompt] = useState(null);

  const askToUpdate = ({ version, size }) =>
    new Promise((resolve) => setUpdatePrompt({ version, size, resolve }));

  const answerUpdate = (accepted) => {
    updatePrompt?.resolve(accepted);
    setUpdatePrompt(null);
  };

  const runUpdateCheck = async () => {
    setUpdateState('checking');
    setUpdatePercent(null);
    const result = await checkForUpdatesInteractive({
      confirm: askToUpdate,
      onProgress: ({ phase, percent }) => {
        setUpdateState(phase);
        setUpdatePercent(percent);
      },
    });
    setUpdatePercent(null);
    setUpdateState(result);
  };

  // track the OS appearance until the user makes an explicit choice
  useEffect(() => {
    if (explicit || !window.matchMedia) return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const handler = (e) =>
      setThemeState((s) => (s.explicit ? s : { theme: e.matches ? 'dark' : 'light', explicit: false }));
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, [explicit]);

  const toggleTheme = () =>
    setThemeState((s) => {
      const next = s.theme === 'dark' ? 'light' : 'dark';
      try {
        localStorage.setItem(THEME_KEY, next);
      } catch {
        /* ignore */
      }
      return { theme: next, explicit: true };
    });

  useEffect(() => {
    const checkHealth = async () => {
      try {
        const data = await systemApi.health();
        setLlmStatus(data.llm?.status || data.ollama?.status || 'disconnected');
      } catch {
        setLlmStatus('disconnected');
      }
    };
    checkHealth();
    const interval = setInterval(checkHealth, 30000);
    return () => clearInterval(interval);
  }, []);

  const isDark = theme === 'dark';

  return (
    <>
      {/* The first-run "your machine can run a better model" modal is gone.
          It interrupted whatever the user was doing to offer a model Bench
          already lists, kept its own localStorage record of what had been
          declined, and reappeared during page load after the model it was
          offering had been dealt with elsewhere. Bench is the one place. */}
      <div className="ambient-bg">
        <div className="ambient-orb orb-1"></div>
        <div className="ambient-orb orb-2"></div>
      </div>
      <BrowserRouter>
        <div className={`app-layout ${collapsed ? 'is-collapsed' : ''}`}>
          {/* Gives the sidebar back after any collapse, deliberate or automatic.
              While the sidebar is shut this button is the only thing on screen
              that says where you are, so it carries the ACTIVE feature's mark
              rather than a fixed logo. */}
          <ReleaseFocusOnNavigate />
          <button
            className="sidebar-peek"
            onClick={toggleSidebar}
            aria-label="Show sidebar"
            aria-expanded={!collapsed}
          >
            <ActiveMark size={18} />
          </button>
          <aside className="sidebar">
            <div className="sidebar-brand">
              <div className="brand-logo-container">
                <h1>
                  <button
                    className="brand-logo-button"
                    onClick={toggleSidebar}
                    aria-label="Collapse sidebar"
                    aria-expanded="true"
                  >
                    <div className="brand-logo-icon">
                      <ActiveMark size={18} />
                    </div>
                  </button>
                  ThinkStack
                </h1>
              </div>
              <div className="brand-subtitle">Research Intelligence</div>
            </div>

            <nav className="sidebar-nav">
              {FEATURES.map(({ id, path: to, end, icon: Icon, label }) => (
                <NavLink
                  key={id}
                  to={to}
                  end={end}
                  className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`}
                >
                  <Icon size={18} />
                  <span>{label}</span>
                </NavLink>
              ))}
            </nav>

            <div className="sidebar-footer">
              <button
                className="theme-toggle"
                onClick={toggleTheme}
                title={`Switch to ${isDark ? 'light' : 'dark'} mode`}
                aria-label="Toggle color theme"
              >
                <span className="theme-toggle-label">
                  {isDark ? <Moon size={16} /> : <Sun size={16} />}
                  {isDark ? 'Dark' : 'Light'}
                </span>
                <span className="theme-switch">
                  <span className="theme-knob" />
                </span>
              </button>

              <div className="status-indicator">
                <div className={`status-dot ${llmStatus !== 'connected' ? 'disconnected' : ''}`} />
                <span>{llmStatus === 'connected' ? 'System Online' : `LLM: ${llmStatus}`}</span>
                <span className="status-meta">local · slm</span>
              </div>

              {/* The model prompt is asked once, so there has to be a way back
                  to it: declining used to be irreversible from inside the app,
                  because the flag lives in the webview's localStorage, which
                  even reinstalling does not clear. */}
              <div className="sidebar-tools">
                <button
                  className={`sidebar-tool ${
                    ['current', 'offline', 'restart-needed'].includes(updateState) ? 'is-ok' : ''
                  } ${
                    ['error', 'install-failed', 'blocked'].includes(updateState) ? 'is-bad' : ''
                  }`}
                  onClick={runUpdateCheck}
                  disabled={['checking', 'downloading', 'installing'].includes(updateState)}
                  title={
                    updateState === 'current'
                      ? `You are on the latest version (v${APP_VERSION}). Click to check again.`
                      : updateState === 'offline'
                      ? 'Could not reach the release server. Nothing was changed.'
                      : updateState === 'install-failed'
                      ? 'The download failed verification or could not be written. '
                        + 'Your installed version is untouched.'
                      : updateState === 'restart-needed'
                      ? 'Installed. Restart ThinkStack to use the new version.'
                      : 'Check for a new version of ThinkStack'
                  }
                >
                  {updateState === 'current' || updateState === 'restart-needed' ? (
                    <Check size={15} />
                  ) : updateState === 'error' || updateState === 'install-failed'
                      || updateState === 'blocked' ? (
                    <AlertCircle size={15} />
                  ) : (
                    <RefreshCw
                      size={15}
                      className={['checking', 'downloading', 'installing'].includes(updateState)
                        ? 'spin' : ''}
                    />
                  )}
                  <span>
                    {/* The bundle carries the model weights, so this is a
                        ~900 MB transfer. Without a percentage the button read
                        "Checking..." for several minutes, which is
                        indistinguishable from a hang. */}
                    {updateState === 'downloading'
                      ? (updatePercent === null
                          ? 'Downloading…'
                          : `Downloading ${updatePercent}%`)
                      : updateState === 'installing' ? 'Installing…'
                      : updateState === 'checking' ? 'Checking…'
                      : updateState === 'current' ? 'Up to date'
                      : updateState === 'offline' ? 'Up to date (offline)'
                      : updateState === 'restart-needed' ? 'Restart to finish'
                      : updateState === 'install-failed' ? 'Update failed, kept current'
                      : updateState === 'blocked' ? 'Update blocked'
                      : updateState === 'declined' ? 'Update available'
                      : updateState === 'unsupported' ? 'Desktop app only'
                      : updateState === 'error' ? 'Check failed, retry'
                      : 'Update app'}
                  </span>
                </button>

                {/* the version a bug report should quote */}
                <div className="sidebar-version">v{APP_VERSION}</div>
              </div>
            </div>
          </aside>

          {/* ── the auto-collapse mechanism, in one place ──
              Any interaction with the page itself gets the sidebar out of the
              way. Watched here rather than wired into each feature: features
              would each have to remember to call it, every new one would start
              out not doing it, and "any action" is not a list anybody can keep
              complete -- it is every button, field, canvas drag and keystroke
              on four screens.

              pointerdown, not click: LitGraph's lasso is a drag that may never
              produce a click at all.

              Capture phase: several children call stopPropagation (the delete
              buttons on a paper row, the canvas handlers), and a bubbling
              listener would simply never hear about those.

              The press ARMS the collapse; the gesture ending applies it. This
              used to collapse on the press itself, which slid the page 220px
              out from under the button still being held and left the click with
              nowhere to land -- the sidebar shut and the action never ran. See
              requestFocusFromPointer.

              Keyboard stays immediate: activating a focused control does not
              depend on where that control is, so moving it cannot break it.

              The sidebar is deliberately OUTSIDE this element, so using the nav
              or the theme toggle does not count as "using the page". */}
          <main
            className="main-content"
            onPointerDownCapture={shellStore.requestFocusFromPointer}
            onKeyDownCapture={shellStore.requestFocus}
          >
            {/* Shown once on a new install: a model is included and can be
                changed. Inside the router because "Show me" navigates. */}
            <FirstRunBanner />
            <AnimatedRoutes />
          </main>

          {/* Outside <main> on purpose: the shell collapses the sidebar on any
              interaction with the PAGE, and asking what a screen is for is not
              working on it. Fixed to the content's bottom-left corner. */}
          <FeatureGuide />

          {/* Also outside <main>: answering the update prompt is not "using the
              page", and collapsing the sidebar underneath an open dialog would
              be movement nobody asked for. */}
          {updatePrompt && (
            <ConfirmDialog
              title={`ThinkStack ${updatePrompt.version} is available`}
              body={
                `${updatePrompt.size ? `About ${Math.round(updatePrompt.size / 1024 / 1024)} MB. ` : ''}`
                + 'The download includes the local model, so it is large and may take '
                + 'a few minutes. Your papers and data are kept.'
              }
              confirmLabel="Install and restart"
              cancelLabel="Not now"
              danger={false}
              onConfirm={() => answerUpdate(true)}
              onCancel={() => answerUpdate(false)}
            />
          )}
        </div>
      </BrowserRouter>
    </>
  );
}
