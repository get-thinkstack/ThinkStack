import { useState } from 'react';
import { AlertTriangle, Check, Cpu, HardDrive, Package, Trash2, X } from 'lucide-react';
import { taskLabel } from '../utils/tasks';

/**
 * One model in the registry, and what it is used for.
 *
 * Extracted from Bench rather than written inline because a card owns real
 * state -- an open task editor, a pending removal confirmation -- and folding
 * that into the page would make Bench re-render every card on every keystroke
 * in one of them.
 *
 * The card never decides policy. Whether removal is dangerous, and what would
 * break, is computed on the server and arrives as `removal_warning`; repeating
 * that rule here in javascript is how the two would drift apart.
 */

const STATUS = {
  present: { text: '', tone: '' },
  missing: { text: 'File is gone', tone: 'bad' },
  too_big: { text: 'Too large for the memory free right now', tone: 'warn' },
  failed: { text: 'Failed to load', tone: 'bad' },
};

const ORIGIN_ICON = {
  bundled: Package,
  downloaded: HardDrive,
  imported: Cpu,
  external: Cpu,
};

export default function ModelCard({ model, tasks, onAssign, onRemove, busy }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(model.tasks || []);
  const [confirming, setConfirming] = useState(false);

  const status = STATUS[model.status] || STATUS.present;
  const OriginIcon = ORIGIN_ICON[model.origin] || Cpu;

  const toggle = (task) =>
    setDraft((d) => (d.includes(task) ? d.filter((t) => t !== task) : [...d, task]));

  const save = () => {
    onAssign(model.id, draft);
    setEditing(false);
  };

  const startEditing = () => {
    setDraft(model.tasks || []);
    setEditing(true);
  };

  return (
    <div className={`model-card ${status.tone ? `is-${status.tone}` : ''}`}>
      <div className="model-card-head">
        <span className="model-card-title">
          <OriginIcon size={15} />
          {model.label}
        </span>
        <span className="model-card-meta">
          {model.size_gb > 0 ? `${model.size_gb.toFixed(2)} GB` : 'size unknown'}
          {' · '}
          {model.origin}
        </span>
      </div>

      {!editing && (
        <div className="model-card-tasks">
          {(model.tasks || []).length === 0 ? (
            <span className="model-task-none">Not assigned to anything</span>
          ) : (
            model.tasks.map((t) => (
              <span key={t} className="model-task-chip">{taskLabel(t)}</span>
            ))
          )}
        </div>
      )}

      {editing && (
        <div className="model-card-editor">
          <p className="model-editor-hint">Use this model for:</p>
          <div className="model-task-grid">
            {tasks.map((t) => (
              <label key={t} className={`model-task-option ${draft.includes(t) ? 'on' : ''}`}>
                <input
                  type="checkbox"
                  checked={draft.includes(t)}
                  onChange={() => toggle(t)}
                />
                <span>{taskLabel(t)}</span>
              </label>
            ))}
          </div>
          <div className="model-card-actions">
            <button className="btn btn-primary btn-sm" onClick={save} disabled={busy}>
              <Check size={14} /><span>Save</span>
            </button>
            <button className="btn btn-secondary btn-sm" onClick={() => setEditing(false)}>
              <X size={14} /><span>Cancel</span>
            </button>
          </div>
        </div>
      )}

      {/* Assigned but not actually doing the job. Replaces the separate
          routing table: the fact only matters next to the model it is about. */}
      {model.not_in_use?.length > 0 && (
        <p className="model-card-status warn">
          <AlertTriangle size={14} />
          Not currently used for {model.not_in_use.map(taskLabel).join(', ')}
          {model.status === 'too_big'
            ? ' — too large for the memory free right now'
            : ' — another model is set for that'}
        </p>
      )}

      {/* It loads and runs; it is simply slow here. Distinct from `too_big`,
          which does not load at all. */}
      {model.slow_here && model.status === 'present' && (
        <p className="model-card-status warn">
          <AlertTriangle size={14} />
          Slow on this machine — it runs on the processor, with no graphics
          acceleration available
        </p>
      )}

      {status.text && (
        <p className={`model-card-status ${status.tone}`}>
          <AlertTriangle size={14} /> {status.text}
          {model.last_error ? ` — ${model.last_error}` : ''}
        </p>
      )}

      {/* The consequence of removal, stated before it happens rather than as a
          bare "are you sure?". Computed server-side: it depends on every other
          entry, so only the server can answer it correctly. */}
      {/* Two different intentions, offered as two buttons rather than one
          word. "Remove" is reversible in a minute; deleting several GB of
          weights is not, and on a metered connection re-downloading is a real
          cost. The destructive option is only shown for files ThinkStack
          created -- an imported model lives in the user's own folder, and
          removing it here must never reach outside the app. */}
      {confirming && (
        <div className="model-card-confirm">
          {model.removal_warning && <p className="confirm-warn">{model.removal_warning}</p>}
          <p>
            {model.managed
              ? 'ThinkStack downloaded this file, so it can also delete it.'
              : 'You added this from your own disk. The file stays where it is.'}
          </p>
          <div className="model-card-actions">
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => { onRemove(model.id, false); setConfirming(false); }}
              disabled={busy}
            >
              <span>Stop using it</span>
            </button>
            {model.managed && (
              <button
                className="btn btn-danger btn-sm"
                onClick={() => { onRemove(model.id, true); setConfirming(false); }}
                disabled={busy}
                title={`Permanently deletes ${model.size_gb?.toFixed(2)} GB from your disk`}
              >
                <Trash2 size={14} />
                <span>Delete permanently ({model.size_gb?.toFixed(1)} GB)</span>
              </button>
            )}
            <button className="btn btn-ghost btn-sm" onClick={() => setConfirming(false)}>
              <span>Cancel</span>
            </button>
          </div>
        </div>
      )}

      {!editing && !confirming && (
        <div className="model-card-actions">
          <button className="btn btn-secondary btn-sm" onClick={startEditing} disabled={busy}>
            <span>Edit tasks</span>
          </button>
          <button className="btn btn-ghost btn-sm" onClick={() => setConfirming(true)} disabled={busy}>
            <Trash2 size={14} /><span>Remove</span>
          </button>
        </div>
      )}
    </div>
  );
}
