import { useState, useEffect, lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, NavLink, useLocation, useNavigate, Navigate } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { BookOpen, Waypoints, PenLine, Sun, Moon, RefreshCw, Check, AlertCircle, Gauge } from 'lucide-react';
import { systemApi } from './utils/api';
import { checkForUpdatesInteractive, APP_VERSION } from './utils/updater';
// Eager, not lazy: it decides whether to render on first paint, and a
// lazy chunk would let the page settle before the note appears.
import FirstRunNote from './components/FirstRunNote';
import './index.css';

// One page is on screen at a time, so one page is worth downloading at a
// time. Loading all four eagerly meant Recharts and the whole canvas engine
// landed before the first paint of whichever page you actually opened.
const Library = lazy(() => import('./components/Library'));
const LitGraph = lazy(() => import('./components/LitGraph'));
const Scribe = lazy(() => import('./components/Scribe'));
const Bench = lazy(() => import('./components/Bench'));

const THEME_KEY = 'ts-theme';
const SIDEBAR_KEY = 'ts-sidebar-collapsed';

/** Restore the sidebar state. Expanded is the default for a first run. */
function getInitialCollapsed() {
  try {
    return localStorage.getItem(SIDEBAR_KEY) === '1';
  } catch {
    return false;   // private mode / storage disabled
  }
}

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
          <Route path="/" element={<Page><Library /></Page>} />
          <Route path="/litgraph" element={<Page><LitGraph /></Page>} />
          <Route path="/write" element={<Page><Scribe /></Page>} />
          <Route path="/bench" element={<Page><Bench /></Page>} />
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
 * main application shell with sidebar navigation and routing.
 *
 * provides the layout, navigation, light/dark theming (follows the OS
 * until the user toggles), and local llm runtime status.
 */
export default function App() {
  const [llmStatus, setLlmStatus] = useState('checking');
  // Persisted like the theme: a layout choice the user made once should not be
  // undone by quitting the app.
  const [collapsed, setCollapsed] = useState(getInitialCollapsed);

  const toggleSidebar = () =>
    setCollapsed((c) => {
      const next = !c;
      try {
        localStorage.setItem(SIDEBAR_KEY, next ? '1' : '0');
      } catch {
        /* storage unavailable; the choice just will not survive a restart */
      }
      return next;
    });
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

  const runUpdateCheck = async () => {
    setUpdateState('checking');
    setUpdatePercent(null);
    const result = await checkForUpdatesInteractive({
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

  // three sections, in the order the work actually happens:
  // collect -> understand -> write.
  const navItems = [
    { to: '/', icon: BookOpen, label: 'Library' },
    { to: '/litgraph', icon: Waypoints, label: 'LitGraph' },
    { to: '/write', icon: PenLine, label: 'Scribe' },
    { to: '/bench', icon: Gauge, label: 'Bench' },
  ];

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
          {/* Visible only while collapsed. The logo IS the way back -- with the
              sidebar gone there is nothing else left to click. */}
          <button
            className="sidebar-peek"
            onClick={toggleSidebar}
            aria-label="Show sidebar"
            aria-expanded={!collapsed}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="#0A0A0A"
                 strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 2L2 7l10 5 10-5-10-5z" />
              <path d="M2 17l10 5 10-5" />
              <path d="M2 12l10 5 10-5" />
            </svg>
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
                      <svg viewBox="0 0 24 24" fill="none" stroke="#0A0A0A" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                        <path d="M2 17l10 5 10-5"/>
                        <path d="M2 12l10 5 10-5"/>
                      </svg>
                    </div>
                  </button>
                  ThinkStack
                </h1>
              </div>
              <div className="brand-subtitle">Research Intelligence</div>
            </div>

            <nav className="sidebar-nav">
              {navItems.map(({ to, icon: Icon, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
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

          <main className="main-content">
            {/* Shown once on a new install: a model is included and can be
                changed. Inside the router because "Show me" navigates. */}
            <FirstRunBanner />
            <AnimatedRoutes />
          </main>
        </div>
      </BrowserRouter>
    </>
  );
}
