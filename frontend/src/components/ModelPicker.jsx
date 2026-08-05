import { useCallback, useEffect, useState } from 'react';
import { Cpu } from 'lucide-react';
import { registryApi } from '../utils/api';
import { taskLabel } from '../utils/tasks';

/**
 * Choose the model for ONE job, from the screen that job belongs to.
 *
 * A second view onto `registry.json`, not a second source of truth. Bench
 * answers "what do all my models do?"; this answers "what does this screen
 * use?" -- same data, different question. The moment either kept its own copy
 * we would be back to the ModelSetup-versus-Bench duplication.
 *
 * Selecting writes through the same PATCH endpoint Bench uses, so the two stay
 * in step by construction rather than by remembering to update both.
 *
 * No restart is needed. Task routing already swaps the resident model between
 * generations (ollama_client._get_llama unloads and reloads under _gen_lock),
 * which is how analysis and general already run on different models today.
 *
 * Renders nothing until it knows the options. A select that appears empty and
 * then pops in is worse than one that arrives late.
 */
export default function ModelPicker({ task, compact = false, onChanged }) {
  const [snapshot, setSnapshot] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(
    () => registryApi.get().then(setSnapshot).catch(() => setSnapshot(null)),
    [],
  );

  useEffect(() => {
    load();
  }, [load]);

  // Reload when another view changes assignments, so Bench and this picker
  // never disagree about what is selected.
  useEffect(() => {
    const onChange = () => load();
    window.addEventListener(MODELS_CHANGED, onChange);
    return () => window.removeEventListener(MODELS_CHANGED, onChange);
  }, [load]);

  const choose = async (id) => {
    setBusy(true);
    setError('');
    try {
      const current = snapshot.models.find((m) => m.tasks.includes(task));
      // Take the task off whatever holds it, then give it to the new model.
      // Without the first step two models claim one job and the winner is
      // decided by capability rank -- which is right for a default, and wrong
      // for something the user just explicitly picked.
      if (current && current.id !== id) {
        await registryApi.update(current.id, {
          tasks: current.tasks.filter((t) => t !== task),
        });
      }
      const target = snapshot.models.find((m) => m.id === id);
      if (target && !target.tasks.includes(task)) {
        await registryApi.update(id, { tasks: [...target.tasks, task] });
      }
      await load();
      onChanged?.();
      window.dispatchEvent(new Event(MODELS_CHANGED));
    } catch (e) {
      setError(e.message || 'Could not change the model.');
    } finally {
      setBusy(false);
    }
  };

  if (!snapshot) return null;

  const usable = (snapshot.models || []).filter((m) => m.status !== 'missing');
  if (usable.length === 0) return null;

  const assigned = usable.find((m) => m.tasks.includes(task));
  const routed = snapshot.routing?.[task];
  // What is ASSIGNED and what will RUN can differ -- a built-in default covers
  // a task nobody assigned. Showing the assignment alone would make the picker
  // disagree with the result the user actually gets.
  const effective = assigned?.id;

  return (
    <div className={`model-picker ${compact ? 'is-compact' : ''}`}>
      <label className="model-picker-label" htmlFor={`pick-${task}`}>
        <Cpu size={14} />
        <span>{compact ? taskLabel(task) : `Model for ${taskLabel(task)}`}</span>
      </label>

      <select
        id={`pick-${task}`}
        value={effective || ''}
        disabled={busy}
        onChange={(e) => e.target.value && choose(e.target.value)}
      >
        {!effective && (
          <option value="">
            {routed?.path
              ? `Default (${routed.path.split(/[\\/]/).pop()})`
              : 'Not set'}
          </option>
        )}
        {usable.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
            {m.status === 'too_big'
              ? ' — too large right now'
              : m.slow_here
                ? ' — slow without acceleration'
                : ''}
          </option>
        ))}
      </select>

      {error && <span className="model-picker-error">{error}</span>}
    </div>
  );
}

/** Fired after an assignment changes, so other views reload. */
export const MODELS_CHANGED = 'thinkstack:models-changed';
