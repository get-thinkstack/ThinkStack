import { useState } from 'react';
import { FolderOpen, X } from 'lucide-react';
import { pickModelFile } from '../utils/filePicker';
import { taskLabel, taskWhere } from '../utils/tasks';

/**
 * Add a model the user already has on disk.
 *
 * Two steps in one panel: choose the file, then say what it is for. The task
 * step is not optional, and it is not inferred. A 7B parameter count says
 * nothing about whether a model follows instructions or emits valid JSON, so
 * guessing would route structured work to a model that cannot do it and leave
 * the user with no idea why their summaries got worse.
 *
 * The file is REFERENCED, never copied -- the panel says so, because "add a
 * model" otherwise reads like it will consume another 7 GB.
 */
export default function ModelImport({ tasks, onImport, onClose, busy, error }) {
  const [path, setPath] = useState('');
  const [label, setLabel] = useState('');
  const [chosen, setChosen] = useState([]);
  const [needsManualPath, setNeedsManualPath] = useState(false);

  const browse = async () => {
    const { path: picked, reason } = await pickModelFile();
    if (picked) {
      setPath(picked);
      return;
    }
    // No dialog here (browser dev build, or the capability refused). Reveal the
    // text field rather than leaving a button that appears to do nothing.
    if (reason === 'unsupported') setNeedsManualPath(true);
  };

  const toggle = (t) =>
    setChosen((c) => (c.includes(t) ? c.filter((x) => x !== t) : [...c, t]));

  const submit = (e) => {
    e.preventDefault();
    if (path.trim()) onImport(path.trim(), chosen, label.trim());
  };

  return (
    <form className="model-import" onSubmit={submit}>
      <div className="model-import-head">
        <h3>Add a model</h3>
        <button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>
          <X size={15} />
        </button>
      </div>

      <p className="model-import-note">
        ThinkStack uses the file where it already is — nothing is copied, so this
        costs no extra disk space.
      </p>

      <div className="model-import-row">
        <button type="button" className="btn btn-secondary" onClick={browse} disabled={busy}>
          <FolderOpen size={15} /><span>Choose a .gguf file…</span>
        </button>
      </div>

      {(needsManualPath || path) && (
        <label className="model-import-field">
          <span>Full path to the model file</span>
          <input
            type="text"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="/home/you/models/mistral-7b-instruct.Q4_K_M.gguf"
            spellCheck={false}
          />
        </label>
      )}

      <label className="model-import-field">
        <span>Name (optional)</span>
        <input
          type="text"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          placeholder="Taken from the filename if left blank"
        />
      </label>

      <div className="model-import-field">
        <span>Use this model for:</span>
        <div className="model-task-grid">
          {tasks.map((t) => (
            <label key={t} className={`model-task-option ${chosen.includes(t) ? 'on' : ''}`}>
              <input type="checkbox" checked={chosen.includes(t)} onChange={() => toggle(t)} />
              <span title={taskWhere(t)}>{taskLabel(t)}</span>
            </label>
          ))}
        </div>
        <p className="model-import-hint">
          You can change this later. Anything left unassigned keeps using the
          bundled model.
        </p>
      </div>

      {error && <p className="model-import-error">{error}</p>}

      <div className="model-card-actions">
        <button type="submit" className="btn btn-primary" disabled={busy || !path.trim()}>
          <span>{busy ? 'Adding…' : 'Add model'}</span>
        </button>
        <button type="button" className="btn btn-secondary" onClick={onClose}>
          <span>Cancel</span>
        </button>
      </div>
    </form>
  );
}
