import { useState } from 'react';
import { ArrowLeft, Download, Search, Wifi } from 'lucide-react';
import { hfApi } from '../utils/api';
import { taskLabel } from '../utils/tasks';

/**
 * Find a model on Hugging Face and fetch it.
 *
 * Two steps, never more: search for a repository, then choose which
 * quantisation of it to download. A GGUF repo commonly carries eight variants
 * of one model and most of the difference is irrelevant on CPU, so the one we
 * would pick is marked and the rest are simply listed.
 *
 * Search runs ON SUBMIT, never as you type. Search-as-you-type would fire a
 * request to a third party on every keystroke, which is precisely the
 * behaviour this app claims not to have -- and the banner would be a lie.
 *
 * The internet notice is not decoration. Everything else in ThinkStack works
 * with the network off; this is the one place that does not, and a user should
 * not have to infer that from a spinner.
 */
export default function HuggingFaceBrowser({ tasks, budgetGb, busy, onDownloaded }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [repo, setRepo] = useState(null);
  const [chosenTasks, setChosenTasks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const runSearch = async (e) => {
    e?.preventDefault();
    const q = query.trim();
    if (!q) return;
    setLoading(true);
    setError('');
    setRepo(null);
    try {
      // A repo id typed in full is not a search -- go straight to its files.
      if (/^[\w.-]+\/[\w.-]+$/.test(q)) {
        setResults(null);
        setRepo(await hfApi.repo(q));
      } else {
        setResults((await hfApi.search(q)).results);
      }
    } catch (err) {
      setError(err.message || 'Could not reach Hugging Face.');
    } finally {
      setLoading(false);
    }
  };

  const openRepo = async (repoId) => {
    setLoading(true);
    setError('');
    try {
      setRepo(await hfApi.repo(repoId));
    } catch (err) {
      setError(err.message || 'Could not read that repository.');
    } finally {
      setLoading(false);
    }
  };

  const fetchFile = async (filename) => {
    setLoading(true);
    setError('');
    try {
      await hfApi.download(repo.repo_id, filename, chosenTasks);
      onDownloaded?.();
    } catch (err) {
      setError(err.message || 'Could not start the download.');
    } finally {
      setLoading(false);
    }
  };

  const toggleTask = (t) =>
    setChosenTasks((c) => (c.includes(t) ? c.filter((x) => x !== t) : [...c, t]));

  return (
    <div className="hf-browser">
      <p className="model-catalog-note">
        <Wifi size={13} />
        Searching Hugging Face uses the internet. Nothing is sent but your search
        words, and it only happens when you press Search.
      </p>

      <form className="hf-search" onSubmit={runSearch}>
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search models, or paste an owner/name repository id"
          spellCheck={false}
        />
        <button className="btn btn-secondary btn-sm" type="submit" disabled={loading || !query.trim()}>
          <Search size={14} /><span>{loading ? 'Searching…' : 'Search'}</span>
        </button>
      </form>

      {error && <p className="model-import-error">{error}</p>}

      {/* step 1 — repositories */}
      {results && !repo && (
        results.length === 0 ? (
          <p className="hf-empty">Nothing found. Try a shorter search, or paste the repository id.</p>
        ) : (
          <div className="hf-results">
            {results.map((r) => (
              <button key={r.repo_id} className="hf-result" onClick={() => openRepo(r.repo_id)}>
                <span className="hf-result-name">{r.name}</span>
                <span className="hf-result-meta">
                  {r.owner} · {r.downloads.toLocaleString()} downloads
                </span>
              </button>
            ))}
          </div>
        )
      )}

      {/* step 2 — which quantisation */}
      {repo && (
        <div className="hf-repo">
          <div className="hf-repo-head">
            <button className="btn btn-ghost btn-sm" onClick={() => setRepo(null)}>
              <ArrowLeft size={14} /><span>Back</span>
            </button>
            <strong>{repo.repo_id}</strong>
          </div>

          <div className="model-import-field">
            <span>Use it for (you can change this later):</span>
            <div className="model-task-grid">
              {tasks.map((t) => (
                <label key={t} className={`model-task-option ${chosenTasks.includes(t) ? 'on' : ''}`}>
                  <input type="checkbox" checked={chosenTasks.includes(t)}
                         onChange={() => toggleTask(t)} />
                  <span>{taskLabel(t)}</span>
                </label>
              ))}
            </div>
          </div>

          {repo.files.map((f) => (
            <div key={f.filename} className={`hf-file ${f.fits ? '' : 'is-blocked'}`}>
              <div className="hf-file-main">
                <span className="hf-file-name">
                  {f.quant || f.filename}
                  {f.filename === repo.recommended && <em className="catalog-badge">recommended</em>}
                </span>
                <span className="hf-file-meta">
                  {f.size_gb ? `${f.size_gb.toFixed(2)} GB` : 'size unknown'}
                  {!f.fits && budgetGb > 0 && ` · larger than the ${budgetGb} GB free`}
                </span>
              </div>
              <button
                className="btn btn-secondary btn-sm"
                disabled={busy || loading}
                onClick={() => fetchFile(f.filename)}
                title={f.fits ? `Download ${f.filename}` : 'This is larger than the memory free right now'}
              >
                <Download size={14} /><span>Download</span>
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
