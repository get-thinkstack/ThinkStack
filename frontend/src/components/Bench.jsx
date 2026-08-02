import { useCallback, useEffect, useState } from 'react';
import { Gauge, HardDrive, RefreshCw } from 'lucide-react';
import { systemApi } from '../utils/api';
import PageHeader from './PageHeader';
import { MachineReport } from './Diagnostics';
import { OPEN_MODEL_SETUP } from './ModelSetup';

/**
 * Bench - what this machine can run, and what it runs it with.
 *
 * A lab bench is where you measure and where the instruments live, which is
 * exactly the pair here: the machine's capability, and the models that use it.
 * Both already existed as sidebar buttons opening modals. A modal is the wrong
 * shape for something you consult while deciding rather than glance at once.
 *
 * Deliberately thin. Model acquisition (HuggingFace), per-task suggestions and
 * the model registry are being built separately; this is where they land, not a
 * mock-up of them. Placeholder UI written against a data shape that does not
 * exist yet only has to be thrown away when it does.
 *
 * Like the modal it replaces, this screen SHOWS and never acts. Downloading a
 * model costs bytes and belongs behind consent, which is ModelSetup's job.
 */
export default function Bench() {
  const [report, setReport] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const examine = useCallback(() => {
    setBusy(true);
    setError('');
    return systemApi
      .diagnose()
      .then(setReport)
      .catch((e) => setError(e.message || 'could not read this machine'))
      .finally(() => setBusy(false));
  }, []);

  useEffect(() => {
    examine();
  }, [examine]);

  return (
    <div>
      <PageHeader
        className="fade-up stagger-1"
        title="Bench"
        subtitle="What this machine can run, and what it runs it with."
      >
        <button className="btn btn-secondary" onClick={examine} disabled={busy}>
          <RefreshCw size={16} className={busy ? 'spin' : ''} />
          <span>{busy ? 'Examining…' : 'Re-examine'}</span>
        </button>
      </PageHeader>

      <div className="card fade-up stagger-2" style={{ marginBottom: '1.5rem' }}>
        <div className="card-header">
          <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Gauge size={16} /> Your machine
          </span>
        </div>

        {busy && !report && <p style={{ color: 'var(--text-secondary)' }}>Examining this machine…</p>}
        {error && <p style={{ color: 'var(--warning)' }}>Could not read this machine: {error}</p>}
        {report && <MachineReport report={report} />}
      </div>

      <div className="card fade-up stagger-3">
        <div className="card-header">
          <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <HardDrive size={16} /> Models
          </span>
        </div>

        <p style={{ color: 'var(--text-secondary)', fontSize: '0.88rem', lineHeight: 1.7 }}>
          ThinkStack ships one small model so a fresh install works offline
          immediately. A larger one answers structured tasks — summaries, claims,
          gap finding — more reliably, and is fetched only with your permission
          or reused from an Ollama or LM Studio install you already have.
        </p>

        <button
          className="btn btn-primary"
          style={{ marginTop: '1rem' }}
          onClick={() => window.dispatchEvent(new Event(OPEN_MODEL_SETUP))}
        >
          <HardDrive size={16} />
          <span>Add better models</span>
        </button>
      </div>
    </div>
  );
}
