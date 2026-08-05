import { useState } from 'react';
import { ChevronDown, ChevronRight, Download, Wifi } from 'lucide-react';
import { taskLabel } from '../utils/tasks';
import HuggingFaceBrowser from './HuggingFaceBrowser';

/**
 * Every model ThinkStack can fetch, and how each stands against this machine.
 *
 * Separate from the single "recommended upgrade" above it, because the two
 * answer different questions. The recommendation is often empty -- correctly,
 * once you already have the best thing your machine can run -- and an earlier
 * version let the download button VANISH with it. "We do not recommend this"
 * and "you may not have this" are not the same statement, and a model that
 * claims no tasks is still a model someone may deliberately want.
 *
 * Nothing is hidden. A model too large for the machine is shown, greyed, with
 * the reason: knowing why you cannot have it is more useful than not knowing
 * it exists.
 *
 * Collapsed by default. Most people never open it, and the recommendation
 * above is the answer for them.
 */
export default function ModelCatalog({ catalog, tasks, budgetGb, busy, downloading, onDownload, onRefresh }) {
  const [open, setOpen] = useState(false);
  const available = (catalog || []).filter((m) => !m.installed);

  return (
    <div className="model-catalog">
      <button className="model-catalog-toggle" onClick={() => setOpen((o) => !o)}>
        {open ? <ChevronDown size={15} /> : <ChevronRight size={15} />}
        <span>Get more models{available.length ? ` (${available.length} suggested)` : ''}</span>
      </button>

      {open && (
        <div className="model-catalog-list">
          <p className="model-catalog-note">
            <Wifi size={13} />
            These are fetched from Hugging Face over the internet, only when you
            press Download. Everything else on this screen works offline.
          </p>

          {available.length === 0 && (
            <p className="hf-empty">
              Nothing else we ship fits this machine — search Hugging Face below.
            </p>
          )}

          {available.map((m) => (
            <div key={m.name} className={`catalog-row ${m.fits ? '' : 'is-blocked'} ${m.slow_here ? 'is-slow' : ''}`}>
              <div className="catalog-main">
                <span className="catalog-name">
                  {m.label}
                  {m.recommended_here && <em className="catalog-badge">suited to this machine</em>}
                </span>
                <span className="catalog-desc">{m.description}</span>
                {m.tasks.length > 0 && (
                  <span className="catalog-tasks">
                    Would take over: {m.tasks.map(taskLabel).join(', ')}
                  </span>
                )}
                {!m.tasks.length && (
                  <span className="catalog-tasks">
                    An alternative, not an upgrade — you choose what it does.
                  </span>
                )}
                {!m.fits && (
                  <span className="catalog-blocked">
                    Needs about {m.min_ram_gb} GB free; there is not enough right now.
                  </span>
                )}
                {/* It loads, and then disappoints. Shown rather than hidden:
                    a user with a reason to want a larger model may still take
                    it, but should not find out afterwards. */}
                {m.fits && m.slow_here && (
                  <span className="catalog-blocked">
                    Will be slow on this machine — it runs on the processor,
                    because no graphics acceleration is available here.
                  </span>
                )}
              </div>

              <div className="catalog-action">
                <span className="catalog-size">{m.size_gb.toFixed(2)} GB</span>
                <button
                  className="btn btn-secondary btn-sm"
                  disabled={busy || downloading || !m.fits}
                  onClick={() => onDownload(m.name)}
                  title={m.fits ? `Download ${m.label}` : 'Not enough free memory for this model'}
                >
                  <Download size={14} /><span>Download</span>
                </button>
              </div>
            </div>
          ))}

          {/* Hugging Face is the escape hatch from a curated list: when
              nothing we ship suits the machine, this is where the user goes
              rather than nowhere. */}
          <div className="hf-divider"><span>or search Hugging Face</span></div>
          <HuggingFaceBrowser
            tasks={tasks}
            budgetGb={budgetGb}
            busy={busy || downloading}
            onDownloaded={onRefresh}
          />
        </div>
      )}
    </div>
  );
}
