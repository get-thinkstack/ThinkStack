import { useState, useEffect, Suspense, useSyncExternalStore, createElement } from 'react';
import { BrowserRouter, Routes, Route, NavLink, useLocation, useNavigate, Navigate } from 'react-router-dom';
import { RefreshCw, Check, AlertCircle } from 'lucide-react';
import { systemApi, documentsApi, analysisApi, gapsApi } from './utils/api';
import { applyEarned, earned, backfill } from './utils/pigments';
import { checkForUpdatesInteractive, APP_VERSION } from './utils/updater';
// Every feature is declared once, here, and the nav / routes / brand mark are
// all rendered from it. The shell no longer names a single feature.
import { FEATURES, featureForPath, markFor } from './features';
import CommandPalette from './components/CommandPalette';
import { papersApi } from './utils/api';
import { shellStore } from './utils/shell';
// Eager, not lazy: it decides whether to render on first paint, and a
// lazy chunk would let the page settle before the note appears.
import FirstRunNote from './components/FirstRunNote';
import PageGuide from './components/PageGuide';
import ConfirmDialog from './components/ConfirmDialog';
import './index.css';

/**
 * A page turns; it does not fly in.
 *
 * No blur filter: it costs a full-page compositing pass every frame of every
 * navigation, on a machine that is also running a language model.
 *
 * What is left is 90ms of opacity, which is a CSS animation (`.page-turn`).
 * framer-motion drove it until it did not earn the ~100 kB it was adding to the
 * entry chunk -- charged on first paint, on every route, for three cross-fades
 * app-wide. The library is worth it for shared-layout transitions, drag physics
 * or spring-following gestures; this app has none of those, and the one place
 * with genuinely hard motion (the LitGraph camera) is its own rAF loop and
 * never used it.
 *
 * The exit half goes with it. AnimatePresence held the outgoing page for its
 * 90ms fade before mounting the next; CSS cannot wait like that, so the old
 * page now leaves at once and the new one fades in. At 90ms nobody can tell.
 */
function Page({ children }) {
  return <div className="page-turn">{children}</div>;
}

/** FirstRunNote needs the router, which only exists below BrowserRouter. */
function FirstRunBanner() {
  const navigate = useNavigate();
  return <FirstRunNote onOpenBench={() => navigate('/bench')} />;
}

function AnimatedRoutes() {
  const location = useLocation();
  return (
    /* Keyed on the pathname, which is what remounts the tree on navigation --
       and therefore what replays `.page-turn`. AnimatePresence used to need
       this key too, so nothing here changed when it left. */
    /* No spinner: a chunk off local disk arrives in a frame or two, and a
       spinner that flashes for one frame reads as a glitch. */
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
 * The page region, and the one place that decides how wide a page may be.
 *
 * A document page is width-capped for reading; a workspace (Scribe) takes the
 * whole window. Which one a page is, is declared in features.js, never
 * matched on a path here.
 *
 * A component because it needs useLocation, which only works below the router.
 */
function MainRegion({ children }) {
  const { pathname } = useLocation();
  const feature = featureForPath(pathname);
  return (
    <main
      className={feature?.fills ? 'main-content is-workspace' : 'main-content'}
      /* ── the auto-collapse mechanism, in one place ──
         Any interaction with the page itself gets the sidebar out of the way.
         The press ARMS the collapse; the gesture ending applies it, because
         collapsing on the press slid the page out from under the button being
         held and the click had nowhere to land. See requestFocusFromPointer.

         Capture phase: several children call stopPropagation, and a bubbling
         listener would never hear those. Keyboard stays immediate -- activating
         a focused control does not depend on where that control is. */
      onPointerDownCapture={shellStore.requestFocusFromPointer}
      onKeyDownCapture={shellStore.requestFocus}
    >
      {children}
    </main>
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
/**
 * Ctrl+K, and everything it can reach.
 *
 * The application had exactly one shortcut before this -- Ctrl+Enter in Scribe
 * -- so finding a paper and opening it was entirely mouse. Ctrl+K is the key
 * every editor and half the web already use, and borrowing it costs nothing
 * and saves teaching.
 *
 * It lives inside the router because half of what it offers is navigation, and
 * the commands are assembled here rather than inside the palette because what
 * is reachable is a fact about the shell: the screens it knows and the papers
 * that exist. A palette offering actions that do nothing where you stand is
 * worse than a smaller one.
 */
function Commands() {
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const [papers, setPapers] = useState([]);

  useEffect(() => {
    const onKey = (e) => {
      if (!(e.ctrlKey || e.metaKey) || e.shiftKey) return;
      if (e.key.toLowerCase() !== 'k') return;
      e.preventDefault();
      setOpen((v) => !v);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Fetched when the palette is first asked for rather than on every render of
  // the shell: most sessions never open it, and the list is only useful once
  // it is on screen.
  useEffect(() => {
    if (!open || papers.length) return;
    let cancelled = false;
    papersApi.list()
      .then((d) => { if (!cancelled) setPapers(d.projects || []); })
      .catch(() => { if (!cancelled) setPapers([]); });
    return () => { cancelled = true; };
  }, [open, papers.length]);

  if (!open) return null;

  const commands = [
    ...FEATURES.map((f) => ({
      id: `go:${f.id}`,
      label: `Go to ${f.label}`,
      group: 'Screen',
      run: () => navigate(f.path),
    })),
    ...papers.map((p) => ({
      id: `paper:${p.project_id}`,
      label: p.name || 'untitled',
      group: 'Paper',
      run: () => navigate(`/write?project=${encodeURIComponent(p.project_id)}`),
    })),
  ];

  return <CommandPalette commands={commands} onClose={() => setOpen(false)} />;
}


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

  // Paint whatever colour this install has earned, before anything renders.
  //
  // An install that predates earned colour has a full library and an empty
  // earned set, and opening it to a grey app would read as a downgrade rather
  // than a beginning -- so the first launch after upgrading grants what the
  // library already proves. backfill() is inert once anything has been earned,
  // which is why this can run on every start without fighting a real
  // milestone. See utils/pigments.js.
  useEffect(() => {
    applyEarned();
    if (earned().length > 0) return;
    (async () => {
      try {
        const [docs, analyses, gaps] = await Promise.all([
          documentsApi.list(),
          analysisApi.history(),
          gapsApi.history(),
        ]);
        const gapRuns = gaps.runs || [];
        backfill({
          papers: docs.total ?? (docs.documents || []).length,
          analyses: (analyses.runs || []).length,
          // A scan that ran but found nothing has not earned the red pen.
          gaps: gapRuns.reduce((n, r) => n + (r.total_gaps ?? 0), 0),
        });
      } catch {
        /* offline or backend not up yet: the app is simply grey, and the
           first real milestone will colour it anyway */
      }
    })();
  }, []);

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

  return (
    <>
      <BrowserRouter>
        <div className={`app-layout ${collapsed ? 'is-collapsed' : ''}`}>
          <ReleaseFocusOnNavigate />
          <Commands />
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

              <div className="status-indicator">
                <div className={`status-dot ${llmStatus !== 'connected' ? 'disconnected' : ''}`} />
                {/* The dot and the words are the whole signal; "local" is not
                    news in an app where everything is local. */}
                <span>{llmStatus === 'connected' ? 'System Online' : `LLM: ${llmStatus}`}</span>
              </div>

              {/* Update app: the updater checks for a release only on this
                  click, never on launch (ADR 2026-07-30). */}
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

          <MainRegion>
            {/* Shown once on a new install: a model is included and can be
                changed. Inside the router because "Show me" navigates. */}
            <FirstRunBanner />
            <AnimatedRoutes />
          </MainRegion>

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
