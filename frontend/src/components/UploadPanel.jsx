import { useState, useCallback } from 'react';
import { CloudUpload, CheckCircle, AlertCircle } from 'lucide-react';
import { documentsApi } from '../utils/api';

/**
 * document upload component with drag-and-drop support.
 *
 * handles pdf file selection via click or drag-and-drop,
 * shows upload progress, and reports results to the parent.
 */
export default function UploadPanel({ onUploadComplete }) {
  const [uploading, setUploading] = useState(false);
  const [dragover, setDragover] = useState(false);
  const [results, setResults] = useState([]);

  const handleFiles = useCallback(async (files) => {
    const pdfFiles = Array.from(files).filter(
      (f) => f.type === 'application/pdf'
    );

    if (pdfFiles.length === 0) return;

    setUploading(true);
    const uploadResults = [];

    for (const file of pdfFiles) {
      try {
        const result = await documentsApi.upload(file);
        uploadResults.push({
          filename: file.name,
          status: 'success',
          ...result,
        });
      } catch (err) {
        uploadResults.push({
          filename: file.name,
          status: 'error',
          error: err.message,
        });
      }
    }

    setResults(uploadResults);
    setUploading(false);

    if (onUploadComplete) {
      onUploadComplete(uploadResults);
    }
  }, [onUploadComplete]);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragover(false);
    handleFiles(e.dataTransfer.files);
  }, [handleFiles]);

  const handleFileInput = useCallback((e) => {
    handleFiles(e.target.files);
  }, [handleFiles]);

  return (
    <div>
      <div
        className={`upload-zone ${dragover ? 'dragover' : ''}`}
        onDragOver={(e) => { e.preventDefault(); setDragover(true); }}
        onDragLeave={() => setDragover(false)}
        onDrop={handleDrop}
        onClick={() => document.getElementById('file-input').click()}
      >
        <input
          id="file-input"
          type="file"
          accept=".pdf"
          multiple
          onChange={handleFileInput}
          style={{ display: 'none' }}
        />
        {uploading ? (
          <div className="loading-overlay">
            <div className="spinner spinner-lg" />
            <span>processing papers...</span>
          </div>
        ) : (
          <>
            <div className="upload-zone-icon-wrapper">
              <CloudUpload size={24} strokeWidth={1.5} />
            </div>
            <h3>Drag & Drop Research Papers</h3>
            <p>Upload PDFs to extract knowledge and run analyses</p>
            <button
              type="button"
              className="upload-browse-btn"
              onClick={(e) => { e.stopPropagation(); document.getElementById('file-input').click(); }}
            >
              Browse Files
            </button>
          </>
        )}
      </div>

      {results.length > 0 && (
        <div style={{ marginTop: '1rem' }}>
          {results.map((r, i) => (
            <div
              key={i}
              className="doc-item"
              style={{
                borderColor: (r.status === 'success' || r.status === 'ingested')
                  ? 'rgba(52, 211, 153, 0.3)'
                  : 'rgba(248, 113, 113, 0.3)',
              }}
            >
              <div className="doc-icon">
                {r.status === 'success' || r.status === 'ingested' ? (
                  <CheckCircle size={18} color="var(--success)" />
                ) : (
                  <AlertCircle size={18} color="var(--danger)" />
                )}
              </div>
              <div className="doc-info">
                <div className="doc-title">{r.filename}</div>
                {(r.status !== 'success' && r.status !== 'ingested') && (
                  <div className="doc-meta">
                    {r.error}
                  </div>
                )}
              </div>
              <span className={`badge badge-${r.status === 'success' || r.status === 'ingested' ? 'success' : 'danger'}`}>
                {r.status}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
