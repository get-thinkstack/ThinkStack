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
 * pulled through Ollama or LM Studio under a different name). Declining is
 * remembered, so this is asked once rather than on every launch.
 */
import { useCallback, useEffect, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Download, X, Check, AlertCircle, HardDrive } from 'lucide-react';
import { modelsApi } from '../utils/api';

const DISMISSED_KEY = 'thinkstack.modelSetup.dismissed';

export default function ModelSetup() {
  const [info, setInfo] = useState(null);
  const [progress, setProgress] = useState(null);
  const [error, setError] = useState('');
  const [dismissed, setDismissed] = useState(
    () => localStorage.getItem(DISMISSED_KEY) === 'true',
  );

  // ask the backend once on mount. a failure here is not worth surfacing: the
  // app works on the bundled model regardless, so it degrades to showing nothing.
  useEffect(() => {
    if (dismissed) return;
    let alive = true;
    modelsApi
      .setup()
      .then((d) => alive && d?.needs_permission && setInfo(d))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, [dismissed]);

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

  const dismiss = useCallback(() => {
    localStorage.setItem(DISMISSED_KEY, 'true');
    setDismissed(true);
    setInfo(null);
  }, []);

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

  if (dismissed || !info?.suggested_upgrade) return null;

  const m = info.suggested_upgrade;
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
          <button className="model-setup-close" onClick={dismiss} aria-label="Not now">
            <X size={18} />
          </button>

          {done ? (
            <>
              <div className="model-setup-icon success"><Check size={22} /></div>
              <h3>{m.label} is ready</h3>
              <p>
                Summaries and gap analysis will use it from the next run. Nothing
                else to do.
              </p>
              <div className="model-setup-actions">
                <button className="btn-primary" onClick={dismiss}>Done</button>
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
                    <button className="btn-secondary" onClick={dismiss}>Not now</button>
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
