import { useState, useEffect } from 'react';
import { Target, AlertTriangle, Lock, Eye, EyeOff, Search, ArrowRight, X, Clock } from 'lucide-react';
import { documentsApi, gapsApi, useLlmBusy } from '../utils/api';
import GapSeverityChart from './charts/GapSeverityChart';
import PageHeader from './PageHeader';

/**
 * research gap analysis component.
 *
 * orchestrates the full gap analysis pipeline across selected papers.
 * displays identified gaps with severity levels and actionable
 * research direction suggestions.
 */
export default function GapAnalysis() {
  const [documents, setDocuments] = useState([]);
  const [selectedDocs, setSelectedDocs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showSetup, setShowSetup] = useState(false);
  const [history, setHistory] = useState([]);
  const [activeRunId, setActiveRunId] = useState(null);

  // single shared local model — disable runs while it's busy elsewhere
  const { busy } = useLlmBusy();

  useEffect(() => {
    const load = async () => {
      try {
        const [docs, past] = await Promise.all([
          documentsApi.list(),
          gapsApi.history(),
        ]);
        setDocuments(docs.documents || []);
        const runs = past.runs || [];
        setHistory(runs);
        // surface the most recent scan on arrival so past work persists
        // visually instead of the page opening blank.
        if (runs.length > 0) {
          setResult(runs[0]);
          setActiveRunId(runs[0].run_id);
        }
      } catch (err) {
        console.error('failed to load gap finder data:', err);
      }
    };
    load();
  }, []);

  const refreshHistory = async () => {
    try {
      const past = await gapsApi.history();
      setHistory(past.runs || []);
    } catch (err) {
      console.error('failed to refresh history:', err);
    }
  };

  const selectRun = (run) => {
    setResult(run);
    setActiveRunId(run.run_id);
    setError('');
    setShowSetup(false);
  };

  const deleteRun = async (runId) => {
    try {
      await gapsApi.deleteRun(runId);
      const remaining = history.filter((r) => r.run_id !== runId);
      setHistory(remaining);
      // if the open run was deleted, fall back to the newest remaining one
      if (activeRunId === runId) {
        if (remaining.length > 0) {
          setResult(remaining[0]);
          setActiveRunId(remaining[0].run_id);
        } else {
          setResult(null);
          setActiveRunId(null);
        }
      }
    } catch (err) {
      setError(err.message);
    }
  };

  const formatRunDate = (iso) => {
    if (!iso) return 'scan';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return 'scan';
    return d.toLocaleString([], {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    });
  };

  const toggleDoc = (docId) => {
    setSelectedDocs((prev) =>
      prev.includes(docId)
        ? prev.filter((id) => id !== docId)
        : [...prev, docId]
    );
  };

  const selectAll = () => {
    if (selectedDocs.length === documents.length) {
      setSelectedDocs([]);
    } else {
      setSelectedDocs(documents.map((d) => d.doc_id));
    }
  };

  const runGapAnalysis = async () => {
    if (selectedDocs.length < 2) return;

    setLoading(true);
    setError('');
    setResult(null);

    try {
      const data = await gapsApi.analyze(selectedDocs, password);
      setResult(data);
      setActiveRunId(data.run_id || null);
      setShowSetup(false);
      // the run is saved server-side; pull the refreshed log so it appears
      // in Past scans without wiping the run we just opened.
      refreshHistory();
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  };

  const severityLabel = (severity) => {
    switch (severity) {
      case 'high': return 'HIGH PRIORITY';
      case 'medium': return 'MEDIUM PRIORITY';
      default: return 'LOW PRIORITY';
    }
  };

  const gapTypeLabel = (type) => {
    const labels = {
      contradictions: 'contradiction',
      under_explored: 'under-explored area',
      methodological: 'methodological gap',
      missing_validation: 'missing validation',
      temporal: 'temporal gap',
    };
    return labels[type] || type;
  };

  // suggestions the model explicitly linked to this gap, matched by the
  // gap_id the backend assigns (not by position). the backend populates each
  // suggestion's related_gaps with the ids of the gaps it addresses.
  const getSuggestionsForGap = (gap) =>
    (result?.suggestions || []).filter((s) =>
      (s.related_gaps || []).includes(gap.gap_id)
    );

  // suggestions not tied to any shown gap shouldn't silently vanish — collect
  // them so they can be surfaced separately.
  const gapIds = new Set((result?.gaps || []).map((g) => g.gap_id));
  const orphanSuggestions = (result?.suggestions || []).filter(
    (s) => !(s.related_gaps || []).some((id) => gapIds.has(id))
  );

  return (
    <div>
      <PageHeader
        className="fade-up stagger-1"
        title="Gap Finder"
        subtitle="AI-identified research gaps and novel directions in your library."
      >
        <button className="btn btn-primary" onClick={() => setShowSetup(!showSetup)}>
          <Search size={16} />
          <span>Scan Library</span>
        </button>
      </PageHeader>

      {showSetup && (
        <div className="card fade-up stagger-2" style={{ marginBottom: '1.5rem' }}>
          <div className="card-header">
            <span className="card-title">Select papers for gap analysis (min. 2)</span>
            <button className="btn btn-secondary btn-sm" onClick={selectAll}>
              {selectedDocs.length === documents.length ? 'Deselect all' : 'Select all'}
            </button>
          </div>

          {documents.length === 0 ? (
            <div className="empty-state">
              <h3>No papers available</h3>
              <p>Upload at least 2 papers in the Library first.</p>
            </div>
          ) : (
            <div style={{ maxHeight: '240px', overflowY: 'auto' }}>
              {documents.map((doc) => (
                <div key={doc.doc_id} className="doc-item" onClick={() => toggleDoc(doc.doc_id)} style={{ cursor: 'pointer' }}>
                  <label className="checkbox-wrap" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selectedDocs.includes(doc.doc_id)}
                      onChange={() => toggleDoc(doc.doc_id)}
                    />
                  </label>
                  <div className="doc-info">
                    <div className="doc-title">{doc.filename}</div>
                    <div className="doc-meta">{doc.chunks} chunks</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {(() => {
            const encryptedSelectedDocs = documents.filter(d => 
              selectedDocs.includes(d.doc_id) && (d.metadata?.is_encrypted === 'true' || d.metadata?.is_encrypted === true)
            );
            
            if (encryptedSelectedDocs.length === 0) return null;
            
            return (
              <div style={{ marginTop: '1rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.8rem', color: 'var(--warning)' }}>
                  <Lock size={14} />
                  <span>Password required for: <strong>{encryptedSelectedDocs.map(d => d.filename).join(', ')}</strong></span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
                  <input
                    type={showPassword ? "text" : "password"}
                    className="input"
                    style={{ width: '300px' }}
                    placeholder="Enter encryption password..."
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                  />
                  <button className="btn-icon btn-icon-accent" onClick={() => setShowPassword(!showPassword)} title="toggle visibility">
                    {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
                  </button>
                </div>
              </div>
            );
          })()}

          <div style={{ marginTop: '1rem' }}>
            <button
              className="btn btn-primary"
              onClick={runGapAnalysis}
              disabled={loading || busy || selectedDocs.length < 2}
            >
              {loading || busy ? <div className="spinner" /> : <Target size={16} />}
              <span>{loading ? 'Analyzing gaps...' : busy ? 'Model busy…' : 'Run Gap Analysis'}</span>
            </button>
            {selectedDocs.length < 2 && selectedDocs.length > 0 && (
              <span style={{ marginLeft: '0.75rem', fontSize: '0.8rem', color: 'var(--warning)' }}>
                Select at least 2 papers
              </span>
            )}
          </div>
        </div>
      )}

      {error && (
        <div className="toast error" style={{ position: 'static', marginBottom: '1rem' }}>
          {error}
        </div>
      )}

      {history.length > 0 && (
        <div className="card gap-history-card fade-up stagger-2" style={{ marginBottom: '1.5rem' }}>
          <div className="card-header" style={{ marginBottom: '1rem' }}>
            <span className="card-title" style={{ display: 'flex', alignItems: 'center', gap: '0.55rem' }}>
              <Clock size={16} style={{ color: 'var(--accent)' }} />
              Past scans
            </span>
            <span className="doc-meta">{history.length} saved</span>
          </div>
          <div className="gap-history-list">
            {history.map((run) => (
              <div
                key={run.run_id}
                className={`gap-history-item ${activeRunId === run.run_id ? 'active' : ''}`}
              >
                <button className="gap-history-main" onClick={() => selectRun(run)}>
                  <span className="gap-history-date">{formatRunDate(run.created_at)}</span>
                  <span className="gap-history-meta">
                    {run.papers_analyzed} {run.papers_analyzed === 1 ? 'paper' : 'papers'}
                    {' · '}
                    {run.total_gaps} {run.total_gaps === 1 ? 'gap' : 'gaps'}
                  </span>
                </button>
                <button
                  className="btn-icon btn-icon-danger gap-history-del"
                  onClick={() => deleteRun(run.run_id)}
                  title="Delete this scan"
                  aria-label="Delete this scan"
                >
                  <X size={15} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {loading && (
        <div className="card fade-up stagger-3">
          <div className="loading-overlay">
            <div className="spinner spinner-lg" />
            <span>Running gap analysis pipeline...</span>
            <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', maxWidth: '400px', textAlign: 'center' }}>
              This may take a few minutes. The system is summarizing papers,
              extracting claims, and analyzing gaps using the local SLM.
            </p>
          </div>
        </div>
      )}

      {result && (
        <>
          {result.gaps && result.gaps.length > 0 && (
            <GapSeverityChart gaps={result.gaps} />
          )}

          {result.gaps && result.gaps.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              {result.gaps.map((gap, i) => {
                const gapSuggestions = getSuggestionsForGap(gap);
                return (
                  <div key={i} className={`gap-card severity-${gap.severity} fade-up stagger-${(i % 4) + 1}`}>
                    <div className="gap-card-header">
                      <h4 className="gap-card-title">
                        {gap.description?.split('.')[0] || gapTypeLabel(gap.gap_type)}
                      </h4>
                      <span className="badge badge-priority">
                        {severityLabel(gap.severity)}
                      </span>
                    </div>

                    <p className="gap-card-description">
                      {gap.description}
                    </p>

                    {gap.evidence && gap.evidence.length > 0 && (
                      <div style={{ marginBottom: '1rem' }}>
                        <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 500 }}>evidence:</span>
                        <ul style={{ listStyle: 'none', padding: 0, marginTop: '0.25rem' }}>
                          {gap.evidence.map((ev, j) => (
                            <li key={j} style={{ fontSize: '0.8rem', color: 'var(--text-muted)', padding: '0.2rem 0', fontStyle: 'italic' }}>
                              - {ev}
                            </li>
                          ))}
                        </ul>
                      </div>
                    )}

                    {gapSuggestions.length > 0 && (
                      <div className="gap-suggestions">
                        <div className="gap-suggestions-title">
                          <AlertTriangle size={14} />
                          <span>Suggested Directions</span>
                        </div>
                        {gapSuggestions.map((sug, j) => (
                          <div key={j} className="gap-suggestion-item">
                            <ArrowRight size={14} className="gap-suggestion-arrow" />
                            <span>{sug.title ? `${sug.title}: ${sug.description}` : sug.description}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {orphanSuggestions.length > 0 && (
            <div className="gap-suggestions" style={{ marginTop: '1rem' }}>
              <div className="gap-suggestions-title">
                <AlertTriangle size={14} />
                <span>Other Suggested Directions</span>
              </div>
              {orphanSuggestions.map((sug, j) => (
                <div key={j} className="gap-suggestion-item">
                  <ArrowRight size={14} className="gap-suggestion-arrow" />
                  <span>{sug.title ? `${sug.title}: ${sug.description}` : sug.description}</span>
                </div>
              ))}
            </div>
          )}

          {result.gaps && result.gaps.length === 0 && (
            <div className="card fade-up stagger-4">
              <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '2rem' }}>No significant gaps identified.</p>
            </div>
          )}
        </>
      )}

      {!result && !loading && !showSetup && (
        <div className="empty-state fade-up stagger-2">
          <h3>Find Research Gaps</h3>
          <p>
            Click "Scan Library" to select papers and identify contradictions,
            under-explored areas, and promising research directions.
          </p>
        </div>
      )}
    </div>
  );
}
