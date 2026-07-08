import { useState } from 'react';
import { Search as SearchIcon, FileText, Sparkles } from 'lucide-react';
import { searchApi } from '../utils/api';
import SearchScoreChart from './charts/SearchScoreChart';
import PageHeader from './PageHeader';

/**
 * search interface component.
 *
 * provides a search bar with hybrid semantic and keyword search
 * over the knowledge base. displays ranked results with relevance
 * scores and source metadata.
 */
export default function Search() {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!query.trim()) return;

    setLoading(true);
    setError('');

    try {
      const data = await searchApi.search(query.trim());
      setResults(data);
    } catch (err) {
      setError(err.message);
      setResults(null);
    }
    setLoading(false);
  };

  const getScoreColor = (score) => {
    if (score >= 0.02) return 'var(--success)';
    if (score >= 0.015) return 'var(--warning)';
    return 'var(--text-muted)';
  };

  return (
    <div>
      <PageHeader
        title="Search Papers"
        subtitle="Semantic and keyword search across your knowledge base."
      />

      <div className="card" style={{ marginBottom: '1.5rem' }}>
        <form onSubmit={handleSearch}>
          <div className="input-group" style={{ display: 'flex', gap: '0.75rem' }}>
            <div className="input-group" style={{ flex: 1, position: 'relative' }}>
              <SearchIcon size={16} className="input-icon" />
              <input
                id="search-input"
                type="text"
                className="input input-with-icon"
                placeholder="search your research papers..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading || !query.trim()}
            >
              {loading ? <div className="spinner" /> : <SearchIcon size={16} />}
              <span>search</span>
            </button>
          </div>
        </form>
      </div>

      {error && (
        <div className="toast error" style={{ position: 'static', marginBottom: '1rem' }}>
          {error}
        </div>
      )}

      {results && results.results.length > 0 && (
        <SearchScoreChart results={results.results} />
      )}

      {results && (
        <div className="card">
          <div className="card-header">
            <span className="card-title">
              {results.total_found} results for "{results.query}"
            </span>
            <span className="badge badge-accent">{results.search_type}</span>
          </div>

          {results.results.length === 0 ? (
            <div className="empty-state">
              <SearchIcon size={48} />
              <h3>No Results Found</h3>
              <p>Try different search terms or upload more papers.</p>
            </div>
          ) : (
            results.results.map((result, i) => (
              <div key={result.chunk_id || i} className="result-item">
                <div className="result-meta">
                  <span
                    className="result-score"
                    style={{ color: getScoreColor(result.score) }}
                  >
                    score: {result.score}
                  </span>
                  <span className="badge badge-accent">
                    <FileText size={10} />
                    {result.metadata?.title || result.doc_id}
                  </span>
                  {result.metadata?.year && (
                    <span className="badge badge-info">{result.metadata.year}</span>
                  )}
                  {result.source && (
                    <span className="badge badge-success">{result.source}</span>
                  )}
                </div>
                <p className="result-text">{result.text}</p>
              </div>
            ))
          )}
        </div>
      )}

      {!results && !loading && (
        <div className="empty-state">
          <h3>Start Searching</h3>
          <p>
            Enter a research topic, question, or concept to search
            across all your ingested papers using hybrid semantic
            and keyword matching.
          </p>
        </div>
      )}
    </div>
  );
}
