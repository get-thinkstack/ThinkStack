import { useState, useEffect } from 'react';
import { Target, Compass, FileText, AlertTriangle, TrendingUp, MessageSquare, Lock, Eye, EyeOff, Search, ArrowRight } from 'lucide-react';
import { documentsApi, gapsApi, chatApi, useLlmBusy } from '../utils/api';
import ChatDialog from './ChatDialog';
import GapSeverityChart from './charts/GapSeverityChart';

/**
 * research gap analysis component.
 *
 * orchestrates the full gap analysis pipeline across selected papers.
 * displays identified gaps with severity levels and actionable
 * research direction suggestions.
 * includes an AI chat dialog for interactive Q&A about gaps.
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

  // chat state
  const [chatMessages, setChatMessages] = useState([]);
  const [chatLoading, setChatLoading] = useState(false);

  // single shared local model — disable runs while it's busy elsewhere
  const { busy } = useLlmBusy();

  useEffect(() => {
    const loadDocs = async () => {
      try {
        const data = await documentsApi.list();
        setDocuments(data.documents || []);
      } catch (err) {
        console.error('failed to load documents:', err);
      }
    };
    loadDocs();
  }, []);

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
      setShowSetup(false);
    } catch (err) {
      setError(err.message);
    }
    setLoading(false);
  };

  const handleChatSend = async (text) => {
    const userMsg = { role: 'user', content: text };
    const history = [...chatMessages];
    setChatMessages((prev) => [...prev, userMsg]);
    setChatLoading(true);

    try {
      let context = '';
      if (result) {
        if (result.gaps?.length) {
          context = `Identified gaps: ${result.gaps
            .map((g) => `${g.description} (${g.severity})`)
            .join('; ')}`;
        }
        if (result.suggestions?.length) {
          context += `\nSuggested directions: ${result.suggestions
            .map((s) => `${s.title}: ${s.description}`)
            .join('; ')}`;
        }
      }

      const response = await chatApi.send(text, {
        docIds: selectedDocs,
        history,
        context,
      });

      setChatMessages((prev) => [
        ...prev,
        { role: 'assistant', content: response.answer },
      ]);
    } catch (err) {
      setChatMessages((prev) => [
        ...prev,
        {
          role: 'assistant',
          content: `Sorry, I encountered an error: ${err.message}. Make sure the backend is running and papers are uploaded.`,
        },
      ]);
    }
    setChatLoading(false);
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

  // Find matching suggestions for a gap (simple heuristic: match by index or content)
  const getSuggestionsForGap = (gapIndex) => {
    if (!result?.suggestions) return [];
    // Distribute suggestions across gaps evenly
    const totalGaps = result.gaps?.length || 1;
    const sugPerGap = Math.ceil(result.suggestions.length / totalGaps);
    const start = gapIndex * sugPerGap;
    return result.suggestions.slice(start, start + sugPerGap);
  };

  return (
    <div>
      <div className="page-header fade-up stagger-1">
        <div className="page-header-left">
          <h2>Gap Finder</h2>
          <p>AI-identified research gaps and novel directions in your library.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowSetup(!showSetup)}>
          <Search size={16} />
          <span>Scan Library</span>
        </button>
      </div>

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
                const gapSuggestions = getSuggestionsForGap(i);
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

      <ChatDialog
        title="Gap Finder Assistant"
        messages={chatMessages}
        onSend={handleChatSend}
        loading={chatLoading}
        placeholder="Ask about research gaps and directions..."
      />
    </div>
  );
}
