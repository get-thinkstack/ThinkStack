import { useState, useEffect, useCallback } from 'react';
import { Clock, CheckCircle, FileText, Trash2, RefreshCw, ChevronDown, ChevronUp, Lock, ShieldCheck, ShieldOff, Eye, EyeOff, BarChart2, Brain, Target } from 'lucide-react';
import { documentsApi, encryptionApi } from '../utils/api';
import UploadPanel from './UploadPanel';
import LibraryChart from './charts/LibraryChart';
import PageHeader from './PageHeader';

/**
 * paper library component.
 *
 * displays all ingested documents, allows upload of new papers,
 * and provides document deletion and encryption controls.
 * shows metadata, chunk counts, and encryption status for each paper.
 */
export default function Library() {
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({ total: 0, total_chunks: 0 });
  const [expandedDoc, setExpandedDoc] = useState(null);
  const [docDetails, setDocDetails] = useState({});

  // encryption state
  const [encryptingDoc, setEncryptingDoc] = useState(null);
  const [encryptPassword, setEncryptPassword] = useState('');
  const [encryptAction, setEncryptAction] = useState(null);
  const [encryptError, setEncryptError] = useState('');
  const [encryptBusy, setEncryptBusy] = useState(false);
  const [decryptedText, setDecryptedText] = useState(null);
  const [showPassword, setShowPassword] = useState(false);

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const data = await documentsApi.list();
      setDocuments(data.documents || []);
      setStats({ total: data.total, total_chunks: data.total_chunks });
    } catch (err) {
      console.error('failed to load documents:', err);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadDocuments();
  }, [loadDocuments]);

  const handleDelete = async (docId) => {
    try {
      await documentsApi.delete(docId);
      loadDocuments();
    } catch (err) {
      console.error('failed to delete document:', err);
    }
  };

  const toggleExpand = async (docId) => {
    if (expandedDoc === docId) {
      setExpandedDoc(null);
      return;
    }
    setExpandedDoc(docId);
    if (!docDetails[docId]) {
      try {
        const details = await documentsApi.get(docId);
        setDocDetails((prev) => ({ ...prev, [docId]: details }));
      } catch (err) {
        console.error('failed to load document details:', err);
      }
    }
  };

  // --- Encryption handlers ---

  const openEncryptDialog = (docId, action) => {
    setEncryptingDoc(docId);
    setEncryptAction(action);
    setEncryptPassword('');
    setEncryptError('');
    setDecryptedText(null);
    setShowPassword(false);
  };

  const closeEncryptDialog = () => {
    setEncryptingDoc(null);
    setEncryptAction(null);
    setEncryptPassword('');
    setEncryptError('');
    setDecryptedText(null);
    setShowPassword(false);
  };

  const handleEncryptSubmit = async (e) => {
    e.preventDefault();
    if (!encryptPassword.trim()) {
      setEncryptError('password is required');
      return;
    }

    setEncryptBusy(true);
    setEncryptError('');

    try {
      if (encryptAction === 'encrypt') {
        await encryptionApi.encrypt(encryptingDoc, encryptPassword);
        closeEncryptDialog();
        loadDocuments();
      } else if (encryptAction === 'view') {
        const result = await encryptionApi.decrypt(encryptingDoc, encryptPassword);
        setDecryptedText(result.full_text);
      } else if (encryptAction === 'remove') {
        await encryptionApi.removeEncryption(encryptingDoc, encryptPassword);
        closeEncryptDialog();
        loadDocuments();
      }
    } catch (err) {
      setEncryptError(err.message || 'operation failed');
    }

    setEncryptBusy(false);
  };

  const isDocEncrypted = (doc) => {
    const meta = doc.metadata || {};
    return meta.is_encrypted === 'true' || meta.is_encrypted === true;
  };

  const actionLabels = {
    encrypt: { title: 'encrypt paper', button: 'encrypt', icon: Lock },
    view: { title: 'view encrypted paper', button: 'decrypt & view', icon: Eye },
    remove: { title: 'remove encryption', button: 'remove encryption', icon: ShieldOff },
  };

  return (
    <div>
      <PageHeader
        className="fade-up stagger-1"
        title="Library"
        subtitle="Manage your collection of ingested research papers."
      />

      <div className="stat-row fade-up stagger-2">
        <div className="stat-card">
          <div className="stat-card-top">
            <span className="stat-card-label">Papers Ingested</span>
            <FileText size={16} className="stat-card-icon" />
          </div>
          <div className="stat-value">{stats.total || '-'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-top">
            <span className="stat-card-label">Knowledge Chunks</span>
            <BarChart2 size={16} className="stat-card-icon" />
          </div>
          <div className="stat-value">{stats.total_chunks || '-'}</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-top">
            <span className="stat-card-label">Analyses Run</span>
            <Brain size={16} className="stat-card-icon" />
          </div>
          <div className="stat-value">-</div>
        </div>
        <div className="stat-card">
          <div className="stat-card-top">
            <span className="stat-card-label">Gaps Found</span>
            <Target size={16} className="stat-card-icon" />
          </div>
          <div className="stat-value">-</div>
        </div>
      </div>

      {documents.length > 0 && <LibraryChart documents={documents} />}

      <div className="fade-up stagger-3">
        <UploadPanel onUploadComplete={loadDocuments} />
      </div>

      <h3 className="section-heading fade-up stagger-4" style={{ marginTop: '2rem' }}>Ingested Papers</h3>

      <div className="card fade-up stagger-4">
        <div className="card-header">
          <span className="card-title"></span>
          <button className="btn btn-secondary btn-sm" onClick={loadDocuments}>
            <RefreshCw size={14} />
            <span>refresh</span>
          </button>
        </div>

        {loading ? (
          <div className="loading-overlay">
            <div className="spinner spinner-lg" />
            <span>loading papers...</span>
          </div>
        ) : documents.length === 0 ? (
          <div className="empty-state">
            <FileText size={48} />
            <h3>no papers yet</h3>
            <p>upload pdf research papers above to start building your knowledge base.</p>
          </div>
        ) : (
          documents.map((doc) => (
            <div key={doc.doc_id}>
              <div className="doc-item" onClick={() => toggleExpand(doc.doc_id)} style={{ cursor: 'pointer' }}>
                <div className="doc-icon">
                  {isDocEncrypted(doc) ? (
                    <Lock size={18} color="var(--accent-secondary)" />
                  ) : (
                    <CheckCircle size={18} color="var(--success)" />
                  )}
                </div>
                <div className="doc-info">
                  <div className="doc-title">
                    {doc.filename}
                    {isDocEncrypted(doc) && (
                      <span className="badge badge-warning" style={{ marginLeft: '0.5rem', fontSize: '0.65rem' }}>
                        encrypted
                      </span>
                    )}
                  </div>
                  <div className="doc-meta">
                    <Clock size={12} /> {doc.metadata?.timestamp || new Date().toLocaleDateString()}
                  </div>
                </div>
                <div className="doc-actions" style={{ display: 'flex', gap: '0.25rem', alignItems: 'center' }}>
                  {isDocEncrypted(doc) ? (
                    <>
                      <button
                        className="btn-icon btn-icon-accent"
                        onClick={(e) => { e.stopPropagation(); openEncryptDialog(doc.doc_id, 'view'); }}
                        title="view decrypted text"
                      >
                        <Eye size={20} />
                      </button>
                      <button
                        className="btn-icon btn-icon-warning"
                        onClick={(e) => { e.stopPropagation(); openEncryptDialog(doc.doc_id, 'remove'); }}
                        title="remove encryption"
                      >
                        <ShieldOff size={20} />
                      </button>
                    </>
                  ) : (
                    <button
                      className="btn-icon btn-icon-accent"
                      onClick={(e) => { e.stopPropagation(); openEncryptDialog(doc.doc_id, 'encrypt'); }}
                      title="encrypt paper"
                    >
                      <ShieldCheck size={20} />
                    </button>
                  )}
                  <button
                    className="btn-icon btn-icon-danger"
                    onClick={(e) => { e.stopPropagation(); handleDelete(doc.doc_id); }}
                    title="delete paper"
                  >
                    <Trash2 size={20} />
                  </button>
                  {expandedDoc === doc.doc_id ? (
                    <ChevronUp size={16} color="var(--text-muted)" />
                  ) : (
                    <ChevronDown size={16} color="var(--text-muted)" />
                  )}
                </div>
              </div>
              {expandedDoc === doc.doc_id && docDetails[doc.doc_id] && (
                <div style={{ padding: '0 1.25rem 1rem', marginTop: '-0.25rem' }}>
                  <div className="card" style={{ background: 'var(--bg-tertiary)' }}>
                    {isDocEncrypted(doc) ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--warning)', fontSize: '0.85rem' }}>
                        <Lock size={14} />
                        <span>this document is encrypted. use the view button to read.</span>
                      </div>
                    ) : (
                      <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: '1.7' }}>
                        {docDetails[doc.doc_id].full_text?.substring(0, 800)}
                        {docDetails[doc.doc_id].full_text?.length > 800 && '...'}
                      </p>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* ── Encryption Modal ── */}
      {encryptingDoc && encryptAction && (
        <div
          className="modal-overlay"
          onClick={closeEncryptDialog}
          style={{
            position: 'fixed', inset: 0, zIndex: 1000,
            background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
        >
          <div
            className="card"
            onClick={(e) => e.stopPropagation()}
            style={{
              width: '100%', maxWidth: '460px',
              padding: '1.5rem', animation: 'fadeIn 0.2s ease',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '1rem' }}>
              {(() => { const Icon = actionLabels[encryptAction]?.icon || Lock; return <Icon size={20} />; })()}
              <h3 style={{ margin: 0 }}>{actionLabels[encryptAction]?.title}</h3>
            </div>

            {decryptedText ? (
              <div>
                <div className="card" style={{ background: 'var(--bg-tertiary)', maxHeight: '400px', overflowY: 'auto' }}>
                  <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', lineHeight: '1.7', whiteSpace: 'pre-wrap' }}>
                    {decryptedText.substring(0, 3000)}
                    {decryptedText.length > 3000 && '...'}
                  </p>
                </div>
                <button
                  className="btn btn-secondary"
                  onClick={closeEncryptDialog}
                  style={{ marginTop: '1rem', width: '100%' }}
                >
                  close
                </button>
              </div>
            ) : (
              <form onSubmit={handleEncryptSubmit}>
                <div style={{ position: 'relative', marginBottom: '1rem' }}>
                  <input
                    type={showPassword ? 'text' : 'password'}
                    className="input"
                    placeholder="enter password…"
                    value={encryptPassword}
                    onChange={(e) => setEncryptPassword(e.target.value)}
                    autoFocus
                    style={{ width: '100%', paddingRight: '2.5rem' }}
                  />
                  <button
                    type="button"
                    className="btn-icon btn-icon-accent"
                    onClick={() => setShowPassword((v) => !v)}
                    style={{ position: 'absolute', right: '0.25rem', top: '50%', transform: 'translateY(-50%)' }}
                    title={showPassword ? 'hide password' : 'show password'}
                  >
                    {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
                  </button>
                </div>

                {encryptError && (
                  <div style={{
                    color: 'var(--danger)', background: 'rgba(248,113,113,0.1)',
                    padding: '0.5rem 0.75rem', borderRadius: '0.5rem',
                    fontSize: '0.85rem', marginBottom: '1rem',
                  }}>
                    {encryptError}
                  </div>
                )}

                <div style={{ display: 'flex', gap: '0.5rem' }}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={closeEncryptDialog}
                    style={{ flex: 1 }}
                  >
                    cancel
                  </button>
                  <button
                    type="submit"
                    className={`btn ${encryptAction === 'remove' ? 'btn-danger' : 'btn-primary'}`}
                    disabled={encryptBusy}
                    style={{ flex: 1 }}
                  >
                    {encryptBusy ? (
                      <div className="spinner" style={{ width: '16px', height: '16px' }} />
                    ) : (
                      actionLabels[encryptAction]?.button
                    )}
                  </button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
