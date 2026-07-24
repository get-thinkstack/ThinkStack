import { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, NavLink, useLocation } from 'react-router-dom';
import { AnimatePresence, motion } from 'framer-motion';
import { BookOpen, Search, Brain, Target, PenLine, Sun, Moon } from 'lucide-react';
import { systemApi } from './utils/api';
import { checkForUpdates } from './utils/updater';
import Library from './components/Library';
import SearchPage from './components/Search';
import Analysis from './components/Analysis';
import GapAnalysis from './components/GapAnalysis';
import PaperWriter from './components/PaperWriter';
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

function AnimatedRoutes() {
  const location = useLocation();
  return (
    <AnimatePresence mode="wait">
      <Routes location={location} key={location.pathname}>
        <Route path="/" element={<Page><Library /></Page>} />
        <Route path="/search" element={<Page><SearchPage /></Page>} />
        <Route path="/analysis" element={<Page><Analysis /></Page>} />
        <Route path="/gaps" element={<Page><GapAnalysis /></Page>} />
        <Route path="/write" element={<Page><PaperWriter /></Page>} />
      </Routes>
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
  const [{ theme, explicit }, setThemeState] = useState(getInitialTheme);

  // apply the active theme to <html> so every token switches
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  // check github releases for a newer desktop build once on launch.
  // no-op in the browser/web build; never throws.
  useEffect(() => {
    checkForUpdates();
  }, []);

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

  const navItems = [
    { to: '/', icon: BookOpen, label: 'Library' },
    { to: '/search', icon: Search, label: 'Search' },
    { to: '/analysis', icon: Brain, label: 'Analysis' },
    { to: '/gaps', icon: Target, label: 'Gap Finder' },
    { to: '/write', icon: PenLine, label: 'Paper Writer' },
  ];

  return (
    <>
      <div className="ambient-bg">
        <div className="ambient-orb orb-1"></div>
        <div className="ambient-orb orb-2"></div>
      </div>
      <BrowserRouter>
        <div className="app-layout">
          <aside className="sidebar">
            <div className="sidebar-brand">
              <div className="brand-logo-container">
                <h1>
                  <div className="brand-logo-icon">
                    <svg viewBox="0 0 24 24" fill="none" stroke="#0A0A0A" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M12 2L2 7l10 5 10-5-10-5z"/>
                      <path d="M2 17l10 5 10-5"/>
                      <path d="M2 12l10 5 10-5"/>
                    </svg>
                  </div>
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
            </div>
          </aside>

          <main className="main-content">
            <AnimatedRoutes />
          </main>
        </div>
      </BrowserRouter>
    </>
  );
}
