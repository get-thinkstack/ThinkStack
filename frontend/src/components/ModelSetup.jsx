/**
 * First-run model setup.
 *
 * The installer ships the baseline model, so the app already works offline when
 * this appears -- nothing here is required. It only asks whether to fetch a
 * larger model that produces noticeably better summaries and gap analysis.
 *
 * It stays silent unless there is something genuinely worth asking about: the
 * backend returns needs_permission=false when the machine cannot run a bigger
 * model, or when an equivalent is already installed (including one the user
 * pulled through Ollama or LM Studio under a different name).
 *
 * What is remembered, and why it is not a boolean: the previous version stored
 * `dismissed=true` for any exit path. That silenced the prompt permanently, for
 * every future model, with no way back -- and the flag lives in the webview's
 * localStorage, outside the app bundle, so reinstalling did not clear it. A
 * tester who clicked "Not now" once could never be offered anything again and
 * would reasonably report that the app never asked. We now record WHICH model
 * was declined, so a different suggestion later still gets asked about, and the
 * sidebar can reopen this at any time.
 */
import { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Download, X, Check, AlertCircle, HardDrive } from 'lucide-react';
import { modelsApi } from '../utils/api';

const CHOICE_KEY = 'thinkstack.modelSetup.choice';
const LEGACY_KEY = 'thinkstack.modelSetup.dismissed';

/** Event any component can dispatch to reopen this dialog. */
export const OPEN_MODEL_SETUP = 'thinkstack:open-model-setup';

/** Read the remembered choice, migrating the legacy boolean if present. */
function readChoice() {
  try {
    const raw = localStorage.getItem(CHOICE_KEY);
    if (raw) return JSON.parse(raw);

    // Legacy `dismissed=true` carried no record of what was declined, so it
    // cannot be honoured for a specific model without silencing every future
    // one. Drop it and ask once more -- most people holding this flag got it
    // from the bug described above, not from an informed decision.
    if (localStorage.getItem(LEGACY_KEY) === 'true') {
      localStorage.removeItem(LEGACY_KEY);
    }
  } catch {
    /* private mode or a corrupt value: behave as if nothing was remembered */
  }
  return null;
}

function rememberChoice(outcome, model) {
  try {
    localStorage.setItem(
      CHOICE_KEY,
      JSON.stringify({ outcome, model: model || null, at: new Date().toISOString() }),
    );
  } catch {
    /* nothing to do; worst case we ask again next launch */
  }
}

export default function ModelSetup() {
  const [info, setInfo] = useState(null);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState('');
  const [open, setOpen] = useState(false);
  // set when the user opens this deliberately from the sidebar, which must show
  // the dialog even when there is nothing to upgrade -- otherwise the button
  // looks broken.
  const [forced, setForced] = useState(false);

  /** Reopen deliberately (sidebar button): always show, whatever the state. */
  const reload = useCallback(async () => {
    try {
      setInfo(await modelsApi.setup());
    } catch {
      setError('Could not read model information.');
    }
    setOpen(true);
  }, []);

  // Ask the backend once on mount. State is set inside the promise callback
  // rather than by calling load() directly, which would set state synchronously
  // during the effect.
  useEffect(() => {
    let alive = true;
    modelsApi
      .setup()
      .then((d) => {
        if (!alive) return;
        setInfo(d);
        if (!d?.needs_permission || !d?.suggested_upgrade) return;
        // Only stay quiet about the exact model already answered for.
        const choice = readChoice();
        if (choice && choice.model === d.suggested_upgrade.name) return;
        setOpen(true);
      })
      .catch(() => {
        // The app runs on the bundled model regardless, so a failure on launch
        // is not worth surfacing. The sidebar button reports it if asked.
      });
    return () => {
      alive = false;
    };
  }, []);

  // reopen on demand (sidebar button)
  useEffect(() => {
    const reopen = () => {
      setForced(true);
      setError('');
      setProgress(null);
      reload();
    };
    window.addEventListener(OPEN_MODEL_SETUP, reopen);
    return () => window.removeEventListener(OPEN_MODEL_SETUP, reopen);
  }, [reload]);

  // poll while a download runs so the bar actually moves
  useEffect(() => {
    if (progress?.status !== 'downloading') return;
    const id = setInterval(async () => {
      try {
        const p = await modelsApi.downloadStatus();
        setProgress(p);
        if (p.status === 'error') setError(p.error || 'download failed');
      } catch {
        /* transient; the next tick retries */
      }
    }, 1000);
    return () => clearInterval(id);
  }, [progress?.status]);

  const close = useCallback(
    (outcome) => {
      // Record declining and installing distinctly. They are different answers:
      // one means "not this model", the other means "already have it", and a
      // single flag could not tell them apart.
      if (!forced) rememberChoice(outcome, info?.suggested_upgrade?.name);
      setOpen(false);
      setForced(false);
    },
    [forced, info],
  );

  const start = useCallback(async () => {
    setError('');
    try {
      await modelsApi.download(info.suggested_upgrade.name);
      setProgress({ status: 'downloading', percent: 0 });
    } catch (e) {
      setError(e.message || 'could not start the download');
    }
  }, [info]);

  const cancel = useCallback(async () => {
    try {
      await modelsApi.cancelDownload();
    } catch {
      /* it may have finished between render and click */
    }
    setProgress(null);
  }, []);

  if (!open) return null;

  const m = info?.suggested_upgrade;
  const done = progress?.status === 'done';
  const busy = progress?.status === 'downloading';

  return (
    <AnimatePresence>
      <motion.div
        className="model-setup-backdrop"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
      >
        <motion.div
          className="model-setup-card"
          initial={{ opacity: 0, y: 16, scale: 0.98 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: 16, scale: 0.98 }}
          transition={{ type: 'spring', stiffness: 260, damping: 24 }}
        >
          <button
            className="model-setup-close"
            onClick={() => close('declined')}
            aria-label="Close"
          >
            <X size={18} />
          </button>

          {done ? (
            <>
              <div className="model-setup-icon success"><Check size={22} /></div>
              <h3>{m?.label} is ready</h3>
              <p>
                It is already in use — summaries and gap analysis will pick it up
                on your next request. No restart, nothing to configure.
              </p>
              <div className="model-setup-actions">
                <button className="btn-primary" onClick={() => close('installed')}>
                  Done
                </button>
              </div>
            </>
          ) : !m ? (
            // Opened from the sidebar with nothing to offer. Report the state
            // rather than showing an empty dialog.
            <>
              <div className="model-setup-icon success"><Check size={22} /></div>
              <h3>Your models are set up</h3>
              <p>
                {error
                  ? error
                  : 'Nothing to add — you already have the best model this machine can run comfortably.'}
              </p>
              {info?.installed?.length > 0 && (
                <div className="model-setup-meta">
                  <span><strong>Installed</strong></span>
                  {info.installed.map((i) => (
                    <span key={i.name}>{i.name} ({i.size_gb} GB)</span>
                  ))}
                </div>
              )}
              {info?.hardware && (
                <p className="model-setup-note">
                  Detected {info.hardware.total_ram_gb} GB RAM,{' '}
                  {info.hardware.budget_gb} GB usable for models, GPU:{' '}
                  {info.hardware.gpu}.
                </p>
              )}
              <div className="model-setup-actions">
                <button className="btn-primary" onClick={() => close('declined')}>
                  Close
                </button>
              </div>
            </>
          ) : (
            <>
              <div className="model-setup-icon"><HardDrive size={22} /></div>
              <h3>Your machine can run a better model</h3>
              <p>{m.description}</p>

              <div className="model-setup-meta">
                <span><strong>{m.label}</strong></span>
                <span>{m.size_gb} GB download</span>
                <span>{info.hardware.budget_gb} GB available</span>
              </div>

              <p className="model-setup-note">
                ThinkStack already works without this — the built-in model is
                installed and ready. This only improves analysis quality.
              </p>

              {busy && (
                <div className="model-setup-progress">
                  <div className="model-setup-bar">
                    <div
                      className="model-setup-bar-fill"
                      style={{ width: `${progress.percent || 0}%` }}
                    />
                  </div>
                  <span>
                    {progress.percent || 0}% — {progress.downloaded_mb || 0} of{' '}
                    {progress.total_mb || '?'} MB
                  </span>
                </div>
              )}

              {error && (
                <div className="model-setup-error">
                  <AlertCircle size={15} /> {error}
                </div>
              )}

              <div className="model-setup-actions">
                {busy ? (
                  <button className="btn-secondary" onClick={cancel}>Cancel</button>
                ) : (
                  <>
                    <button className="btn-secondary" onClick={() => close('declined')}>
                      Not now
                    </button>
                    <button className="btn-primary" onClick={start}>
                      <Download size={15} /> Download
                    </button>
                  </>
                )}
              </div>
            </>
          )}
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
}
