import { useState, useEffect } from 'react';
import { Brain, Lightbulb, Layers, FileText, MessageSquare, Lock, Eye, EyeOff, Plus, Target } from 'lucide-react';
import { documentsApi, analysisApi, chatApi, useLlmBusy } from '../utils/api';
import ChatDialog from './ChatDialog';

/**
 * analysis dashboard component.
 *
 * allows users to select documents and run summarization,
 * claim extraction, or theme clustering via the slm.
 * displays structured analysis results.
 * includes an AI chat dialog for interactive Q&A about analysis.
 */
export default function Analysis() {
  const [documents, setDocuments] = useState([]);
  const [selectedDocs, setSelectedDocs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('summarize');
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showNewAnalysis, setShowNewAnalysis] = useState(false);

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

  const runAnalysis = async () => {
    if (selectedDocs.length === 0) return;

    setLoading(true);
    setError('');
    setResult(null);

    try {
      let data;
      switch (activeTab) {
        case 'summarize':
          data = await analysisApi.summarize(selectedDocs, password);
          break;
        case 'claims':
          data = await analysisApi.extractClaims(selectedDocs, password);
          break;
        case 'themes':
          data = await analysisApi.clusterThemes(selectedDocs, password);
          break;
        default:
          return;
      }
      setResult(data);
      setShowNewAnalysis(false);
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
        if (activeTab === 'summarize' && result.summary_text) {
          context = `Analysis summary: ${result.summary_text}`;
          if (result.key_points?.length) {
            context += `\nKey points: ${result.key_points.join('; ')}`;
          }
        } else if (activeTab === 'claims' && result.claims) {
          context = `Extracted claims: ${result.claims.map(c => c.claim_text).join('; ')}`;
        } else if (activeTab === 'themes' && result.themes) {
          context = `Themes: ${result.themes.map(t => `${t.label}: ${t.description}`).join('; ')}`;
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
          content: `Sorry, I encountered an error: ${err.message}. Please make sure the backend is running and papers are uploaded.`,
        },
      ]);
    }
    setChatLoading(false);
  };

  const tabs = [
    { id: 'summarize', label: 'Summarize', icon: Brain },
    { id: 'claims', label: 'Extract Claims', icon: Lightbulb },
    { id: 'themes', label: 'Cluster Themes', icon: Layers },
  ];

  return (
    <div>
      <div className="page-header fade-up stagger-1">
        <div className="page-header-left">
          <h2>Analysis</h2>
          <p>Run cross-paper analyses and synthesize findings.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setShowNewAnalysis(!showNewAnalysis)}>
          <Plus size={16} />
          <span>New Analysis</span>
        </button>
      </div>

      {showNewAnalysis && (
        <>
          <div className="card fade-up stagger-2" style={{ marginBottom: '1.5rem' }}>
            <div className="card-header">
              <span className="card-title">Select papers to analyze</span>
              <button className="btn btn-secondary btn-sm" onClick={selectAll}>
                {selectedDocs.length === documents.length ? 'Deselect all' : 'Select all'}
              </button>
            </div>

            {documents.length === 0 ? (
              <div className="empty-state">
                <h3>No papers available</h3>
                <p>Upload papers in the Library first.</p>
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
          </div>

          <div className="fade-up stagger-3" style={{ display: 'flex', gap: '0.5rem', marginBottom: '1.5rem' }}>
            {tabs.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                className={`btn ${activeTab === id ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => { setActiveTab(id); setResult(null); }}
              >
                <Icon size={16} />
                <span>{label}</span>
              </button>
            ))}
          </div>

          {(() => {
            const encryptedSelectedDocs = documents.filter(d => 
              selectedDocs.includes(d.doc_id) && (d.metadata?.is_encrypted === 'true' || d.metadata?.is_encrypted === true)
            );
            
            if (encryptedSelectedDocs.length === 0) return null;
            
            return (
              <div style={{ marginBottom: '1.5rem', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
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

          <button
            className="btn btn-primary fade-up stagger-4"
            onClick={runAnalysis}
            disabled={loading || busy || selectedDocs.length === 0}
            style={{ marginBottom: '1.5rem' }}
          >
            {loading || busy ? <div className="spinner" /> : <Brain size={16} />}
            <span>{loading ? 'Analyzing...' : busy ? 'Model busy…' : `Run ${activeTab}`}</span>
          </button>
        </>
      )}

      {error && (
        <div className="toast error" style={{ position: 'static', marginBottom: '1rem' }}>
          {error}
        </div>
      )}

      {result && (
        <div className="card fade-up stagger-4">
          {activeTab === 'summarize' && (
            <div className="analysis-section">
              <h3><Brain size={18} /> Summary</h3>
              <p style={{ color: 'var(--text-secondary)', lineHeight: '1.8', marginBottom: '1rem' }}>
                {result.summary_text}
              </p>
              {result.key_points && result.key_points.length > 0 && (
                <>
                  <h3 style={{ fontSize: '0.95rem', marginTop: '1rem' }}>Key Points</h3>
                  <ul className="key-points">
                    {result.key_points.map((point, i) => (
                      <li key={i}>{point}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}

          {activeTab === 'claims' && result.claims && (
            <div className="analysis-section">
              <h3><Lightbulb size={18} /> Extracted Claims ({result.total})</h3>
              {result.claims.map((claim, i) => (
                <div key={i} className="result-item">
                  <div className="result-meta">
                    <span className="badge badge-accent">{claim.claim_type}</span>
                    <span className="badge badge-info">{claim.confidence}</span>
                    <span className="badge badge-success">{claim.doc_id}</span>
                  </div>
                  <p className="result-text">{claim.claim_text}</p>
                  {claim.supporting_text && (
                    <p style={{ fontSize: '0.8rem', color: 'var(--text-muted)', marginTop: '0.5rem', fontStyle: 'italic' }}>
                      {claim.supporting_text}
                    </p>
                  )}
                </div>
              ))}
            </div>
          )}

          {activeTab === 'themes' && result.themes && (
            <div className="analysis-section">
              <h3><Layers size={18} /> Thematic Clusters ({result.total})</h3>
              {result.themes.map((theme, i) => (
                <div key={i} className="suggestion-card">
                  <div className="suggestion-title">{theme.label}</div>
                  <p style={{ color: 'var(--text-secondary)', fontSize: '0.875rem', marginBottom: '0.75rem' }}>
                    {theme.description}
                  </p>
                  <div style={{ display: 'flex', gap: '0.3rem', flexWrap: 'wrap' }}>
                    {theme.keywords?.map((kw, j) => (
                      <span key={j} className="badge badge-accent">{kw}</span>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {!result && !loading && !showNewAnalysis && (
        <div className="card fade-up stagger-2">
          <div className="empty-state">
            <h3>No Analyses Yet</h3>
            <p>
              Run an AI analysis across multiple papers to synthesize findings.
            </p>
            <button className="btn btn-primary" onClick={() => setShowNewAnalysis(true)} style={{ marginTop: '1rem' }}>
              Create your first analysis
            </button>
          </div>
        </div>
      )}

      <ChatDialog
        title="Analysis Assistant"
        messages={chatMessages}
        onSend={handleChatSend}
        loading={chatLoading}
        placeholder="Ask about your analysis results..."
      />
    </div>
  );
}
