import { useState } from 'react';
import { Check, Plus, X } from 'lucide-react';
import { taskLabel, taskWhere } from '../utils/tasks';

/**
 * Models already on this machine that ThinkStack is not yet using.
 *
 * `discovery.py` has always known about these -- LM Studio's directory, gguf
 * files sitting in ThinkStack's own models dir, a running Ollama -- but the
 * list existed only to decide whether to OFFER a download. So a user with LM
 * Studio was told nothing, and to actually use those weights had to go find the
 * file and paste its path into a text box, for a model the app had already
 * located. That is the gap this closes.
 *
 * Assignment happens inline: tick the jobs, press Add. No path, no dialog.
 *
 * Ollama entries are shown but NOT assignable. Ollama keeps its weights as
 * content-addressed blobs that llama.cpp cannot open, so registering one as a
 * file entry would produce something that fails at load time. The router
 * already reaches Ollama over HTTP when a task's model is missing from disk,
 * so those models are not unusable -- they are just not ours to file.
 */

const SOURCE_LABEL = {
  thinkstack: 'in ThinkStack’s models folder',
  lmstudio: 'from LM Studio',
  ollama: 'served by Ollama',
  'ollama-disk': 'pulled by Ollama',
};

export default function DiscoveredModels({ discovered, tasks, busy, onAdd }) {
  const [openFor, setOpenFor] = useState(null);
  const [chosen, setChosen] = useState([]);

  if (!discovered?.length) return null;

  const start = (name) => {
    setOpenFor(name);
    setChosen([]);
  };

  const toggle = (t) =>
    setChosen((c) => (c.includes(t) ? c.filter((x) => x !== t) : [...c, t]));

  return (
    <div className="model-available">
      <p className="model-available-head">
        Already on this machine, not set up yet
      </p>

      {discovered.map((m) => (
        <div key={`${m.source}:${m.name}`} className="discovered-row">
          <div className="discovered-main">
            <span className="discovered-name">{m.label || m.name}</span>
            <span className="discovered-meta">
              {m.size_gb > 0 ? `${m.size_gb.toFixed(2)} GB · ` : ''}
              {SOURCE_LABEL[m.source] || m.source}
            </span>
          </div>

          {m.assignable ? (
            openFor === m.name ? null : (
              <button className="btn btn-secondary btn-sm" disabled={busy}
                      onClick={() => start(m.name)}>
                <Plus size={14} /><span>Use this</span>
              </button>
            )
          ) : (
            // Honest rather than hidden: the user can see ThinkStack knows
            // about it, and why it is not a button.
            <span className="discovered-note">
              used automatically when a job’s model is missing
            </span>
          )}

          {openFor === m.name && (
            <div className="discovered-assign">
              <p className="model-editor-hint">Use it for:</p>
              <div className="model-task-grid">
                {tasks.map((t) => (
                  <label key={t} className={`model-task-option ${chosen.includes(t) ? 'on' : ''}`}>
                    <input type="checkbox" checked={chosen.includes(t)}
                           onChange={() => toggle(t)} />
                    <span title={taskWhere(t)}>{taskLabel(t)}</span>
                  </label>
                ))}
              </div>
              <div className="model-card-actions">
                <button className="btn btn-primary btn-sm" disabled={busy || !chosen.length}
                        onClick={() => { onAdd(m.path, chosen, m.label || m.name); setOpenFor(null); }}>
                  <Check size={14} /><span>Add</span>
                </button>
                <button className="btn btn-secondary btn-sm" onClick={() => setOpenFor(null)}>
                  <X size={14} /><span>Cancel</span>
                </button>
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
