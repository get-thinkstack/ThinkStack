import { useCallback, useEffect, useRef, useState } from 'react';
import { Gauge, HardDrive, Plus, RefreshCw } from 'lucide-react';
import { modelsApi, registryApi, systemApi } from '../utils/api';
import PageHeader from './PageHeader';
import { MachineReport } from './Diagnostics';
import ModelCard from './ModelCard';
import ModelImport from './ModelImport';
import DiscoveredModels from './DiscoveredModels';
import ModelCatalog from './ModelCatalog';

/**
 * Bench - what this machine can run, and what it runs it with.
 *
 * A lab bench is where you measure and where the instruments live, which is
 * exactly the pair here: the machine's capability, and the models that use it.
 *
 * ONE models card, deliberately. An earlier version of this screen had a
 * registry list AND a separate "Download a better model" button that opened the
 * first-run modal -- two places to add a model, listing overlapping sets, each
 * unaware of the other. Downloading is now just another way to get a row in the
 * same list, so there is one story: here are your models, here is what each is
 * for, here is how to get more.
 *
 * This is the ONLY place models are managed. The first-run modal that used to
 * ask about downloading one is gone: it popped up over whatever the user was
 * doing, offered a model Bench already lists, and kept its own record of what
 * had been declined.
 *
 * Every mutation replaces state from the `snapshot` the server returns rather
 * than patching it locally. Removing a model changes what the OTHER cards say
 * -- a task may now be uncovered, and routing may fall back elsewhere -- so an
 * optimistic update would render a view that never existed on the server.
 */

export default function Bench() {
  const [report, setReport] = useState(null);
  const [reportError, setReportError] = useState('');
  const [examining, setExamining] = useState(false);

  const [snapshot, setSnapshot] = useState(null);
  const [busy, setBusy] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState('');
  const [notice, setNotice] = useState('');

  const examine = useCallback(() => {
    setExamining(true);
    setReportError('');
    return systemApi
      .diagnose()
      .then(setReport)
      .catch((e) => setReportError(e.message || 'could not read this machine'))
      .finally(() => setExamining(false));
  }, []);

  const loadRegistry = useCallback(
    () => registryApi.get().then(setSnapshot).catch(() => setSnapshot(null)),
    [],
  );

  useEffect(() => {
    examine();
    loadRegistry();
  }, [examine, loadRegistry]);


  // A notice reports something that already finished, so it should not sit
  // there until the user reloads the webview. Cleared on a timer, and the
  // timer is keyed on the message so a new one restarts it rather than
  // inheriting the previous one's remaining time.
  useEffect(() => {
    if (!notice) return undefined;
    const id = setTimeout(() => setNotice(''), 4000);
    return () => clearTimeout(id);
  }, [notice]);

  // Poll only while a download is actually running. The bundle is ~1 GB, so
  // without a moving number the button is indistinguishable from a hang -- the
  // exact complaint the update button earned.
  const downloading = snapshot?.download?.status === 'downloading';
  const pollRef = useRef(null);
  useEffect(() => {
    if (!downloading) return undefined;
    pollRef.current = setInterval(loadRegistry, 1000);
    return () => clearInterval(pollRef.current);
  }, [downloading, loadRegistry]);

  /** run a mutation, adopt the snapshot it returns, surface its message. */
  const mutate = async (fn, onDone) => {
    setBusy(true);
    setNotice('');
    try {
      const res = await fn();
      if (res?.snapshot) setSnapshot(res.snapshot);
      onDone?.(res);
    } catch (e) {
      setNotice(e.message || 'That did not work.');
    } finally {
      setBusy(false);
    }
  };

  const doImport = (path, tasks, label) => {
    setImportError('');
    setBusy(true);
    registryApi
      .import(path, tasks, label)
      .then((res) => {
        if (res?.snapshot) setSnapshot(res.snapshot);
        setImporting(false);
        setNotice(`Added ${res.model?.label || 'the model'}.`);
      })
      .catch((e) => setImportError(e.message || 'That file could not be added.'))
      .finally(() => setBusy(false));
  };

  const startDownload = (name) =>
    mutate(
      () => modelsApi.download(name).then(loadRegistry).then(() => ({})),
      () => setNotice('Downloading. You can keep working while it runs.'),
    );

  const cancelDownload = () =>
    mutate(() => modelsApi.cancelDownload().then(loadRegistry).then(() => ({})));

  const models = snapshot?.models || [];
  const tasks = snapshot?.tasks || [];
  const discovered = snapshot?.discovered || [];
  const catalog = snapshot?.catalog || [];
  const dl = snapshot?.download || {};

  return (
    <div>
      <PageHeader
        className="fade-up stagger-1"
        title="Bench"
      >
        <button className="btn btn-secondary" onClick={examine} disabled={examining}>
          <RefreshCw size={16} className={examining ? 'spin' : ''} />
          <span>{examining ? 'Examining…' : 'Re-examine'}</span>
        </button>
      </PageHeader>

      <div className="card fade-up stagger-2" style={{ marginBottom: '1.5rem' }}>
        <div className="card-header">
          <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <Gauge size={16} /> Your machine
          </span>
        </div>
        {examining && !report && <p style={{ color: 'var(--text-secondary)' }}>Examining this machine…</p>}
        {reportError && <p style={{ color: 'var(--warning)' }}>Could not read this machine: {reportError}</p>}
        {report && <MachineReport report={report} />}
      </div>

      <div className="card fade-up stagger-3" style={{ marginBottom: '1.5rem' }}>
        <div className="card-header">
          <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <HardDrive size={16} /> Models
          </span>
          {!importing && (
            <button className="btn btn-secondary btn-sm" onClick={() => setImporting(true)} disabled={busy}>
              <Plus size={15} /><span>Add a model</span>
            </button>
          )}
        </div>

        {notice && <p className="model-notice">{notice}</p>}

        {importing && (
          <ModelImport
            tasks={tasks}
            busy={busy}
            error={importError}
            onImport={doImport}
            onClose={() => { setImporting(false); setImportError(''); }}
          />
        )}

        {!snapshot && <p style={{ color: 'var(--text-secondary)' }}>Reading the model list…</p>}

        {/* Reachable by removing the included model, which is allowed. Says
            what stopped working and the three ways back, rather than showing
            an empty list and leaving the user to infer the rest. */}
        {snapshot && models.length === 0 && !importing && (
          <div className="model-empty">
            <strong>ThinkStack has no model, so it cannot answer anything yet.</strong>
            <p>Reading papers, the editor and compiling all still work. To bring
               back summaries, gap finding and AI drafting, do any one of these:</p>
            <ul>
              <li><b>Use one you already have</b> — press “Add a model” above and
                  point at a .gguf file.</li>
              <li><b>Adopt one from Ollama or LM Studio</b> — if either is
                  installed, it is listed below and takes one click.</li>
              <li><b>Download one</b> — open “Get more models”. This is the only
                  option that uses the internet.</li>
            </ul>
          </div>
        )}

        <div className="model-list">
          {models.map((m) => (
            <ModelCard
              key={m.id}
              model={m}
              tasks={tasks}
              busy={busy}
              // No restart. Task routing already swaps the resident model
              // between generations (ollama_client._get_llama unloads and
              // reloads under _gen_lock), which is how analysis and general
              // already run on different models today. The restart caveat in
              // set_model applies to the GLOBAL base model, not to this.
              onAssign={(id, next) =>
                mutate(() => registryApi.update(id, { tasks: next }),
                       () => setNotice('Saved. It applies to your next request.'))}
              onRemove={(id, deleteFile) =>
                mutate(() => registryApi.remove(id, deleteFile),
                       (res) => setNotice(
                         res?.file_deleted
                           ? 'Deleted, and the disk space was reclaimed.'
                           : 'ThinkStack has stopped using it. The file is untouched.'))}
            />
          ))}
        </div>

        <DiscoveredModels
          discovered={discovered}
          tasks={tasks}
          busy={busy}
          onAdd={doImport}
        />

        {/* No separate "a better model is available" card. It listed the same
            models as the section below it, with its own Download button and its
            own internet notice -- two components telling one story, which is
            the duplication this screen keeps growing back. The suggestion is
            now a badge on the row inside "Get more models". */}
        {downloading && (
          <div className="model-offer">
            <div className="model-setup-bar">
              <div className="model-setup-bar-fill" style={{ width: `${dl.percent || 0}%` }} />
            </div>
            <div className="model-offer-head">
              <span>
                {dl.percent || 0}% — {dl.downloaded_mb || 0} of {dl.total_mb || '?'} MB
              </span>
              <button className="btn btn-secondary btn-sm" onClick={cancelDownload}>
                <span>Cancel</span>
              </button>
            </div>
          </div>
        )}

        <ModelCatalog
          catalog={catalog}
          tasks={tasks}
          budgetGb={snapshot?.budget_gb || 0}
          busy={busy}
          downloading={downloading}
          onDownload={startDownload}
          onRefresh={() => { loadRegistry(); setNotice('Downloading. You can keep working while it runs.'); }}
        />

        {dl.status === 'error' && dl.error && (
          <p className="model-import-error">Download failed: {dl.error}</p>
        )}

      </div>

    </div>
  );
}
