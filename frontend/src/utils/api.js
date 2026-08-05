/**
 * api client utility for scholarlens backend.
 *
 * provides typed fetch wrappers for all backend endpoints
 * with consistent error handling and response parsing.
 */

import { useEffect, useState, useSyncExternalStore } from 'react';

const BASE_URL = '/api';

/* ----------------------------------------------------------------
 * Single-model busy tracker.
 * There is one local LLM, serialized on the server, so only one
 * generation runs at a time. We track in-flight LLM calls here so the
 * UI can react (disable the assistant / run buttons, show why) instead
 * of silently queueing and appearing to hang.
 * ---------------------------------------------------------------- */
let _llm = { count: 0, label: '' };
const _llmListeners = new Set();
const _llmEmit = () => _llmListeners.forEach((l) => l());

export const llmBusyStore = {
  subscribe(cb) {
    _llmListeners.add(cb);
    return () => _llmListeners.delete(cb);
  },
  getSnapshot() {
    return _llm;
  },
  begin(label) {
    _llm = { count: _llm.count + 1, label: label || _llm.label };
    _llmEmit();
  },
  end() {
    const count = Math.max(0, _llm.count - 1);
    _llm = { count, label: count === 0 ? '' : _llm.label };
    _llmEmit();
  },
};

/** react hook → { busy, label } reflecting whether the local LLM is generating. */
export function useLlmBusy() {
  const snap = useSyncExternalStore(
    llmBusyStore.subscribe,
    llmBusyStore.getSnapshot,
    llmBusyStore.getSnapshot,
  );
  return { busy: snap.count > 0, label: snap.label };
}

/**
 * Background analysis progress, polled from the server.
 *
 * Distinct from `useLlmBusy`, which only knows about calls THIS tab started.
 * Ingest-time analysis is queued server-side and outlives the request that
 * triggered it, so the only way to know it is running is to ask.
 *
 * Polls slowly and only while there is something to report — an idle app makes
 * one request every 5 s, and a busy one every 1.5 s, which is well inside the
 * granularity of jobs measured in tens of seconds.
 *
 * @returns {{active: boolean, label: string, done: number, total: number,
 *            queued: number, error: string}}
 */
export function useJobs() {
  const [state, setState] = useState({
    active: false, label: '', done: 0, total: 0, queued: 0, error: '',
  });

  useEffect(() => {
    let alive = true;
    let timer = null;

    const tick = async () => {
      try {
        const s = await systemApi.jobs();
        if (!alive) return;
        const active = !!s.running || s.queued > 0;
        setState({
          active,
          label: s.label || '',
          done: s.done || 0,
          total: s.total || 0,
          queued: s.queued || 0,
          error: s.last_error || '',
        });
        timer = setTimeout(tick, active ? 1500 : 5000);
      } catch {
        // The backend may still be starting, or already gone. Back off rather
        // than hammering it, and never surface this as a user-facing error —
        // failing to read a progress bar is not something to interrupt for.
        if (alive) timer = setTimeout(tick, 5000);
      }
    };

    tick();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, []);

  return state;
}

async function request(path, options = {}) {
  const url = `${BASE_URL}${path}`;
  const config = {
    headers: {
      'Content-Type': 'application/json',
    },
    ...options,
  };

  if (config.body && typeof config.body === 'object' && !(config.body instanceof FormData)) {
    config.body = JSON.stringify(config.body);
  }

  if (config.body instanceof FormData) {
    delete config.headers['Content-Type'];
  }

  const response = await fetch(url, config);

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `request failed: ${response.status}`);
  }

  return response.json();
}

/** wrap an LLM-bound request so the global busy tracker reflects it. */
async function llmRequest(label, path, options) {
  llmBusyStore.begin(label);
  try {
    return await request(path, options);
  } finally {
    llmBusyStore.end();
  }
}

export const documentsApi = {
  upload: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return request('/documents/upload', {
      method: 'POST',
      body: formData,
    });
  },

  list: () => request('/documents'),

  get: (docId) => request(`/documents/${docId}`),

  delete: (docId) => request(`/documents/${docId}`, { method: 'DELETE' }),

  /** the originally uploaded pdf, served inline for the litgraph reader */
  pdfUrl: (docId) => `${BASE_URL}/documents/${docId}/pdf`,
};

export const searchApi = {
  /** ranked chunks, best passage first */
  search: (query, topK = 10, docIds = []) =>
    request('/search', {
      method: 'POST',
      body: { query, top_k: topK, doc_ids: docIds },
    }),

  /**
   * the same search rolled up to papers, each carrying every chunk of its
   * that matched. the canvas asks "which papers does this touch, and where
   * in each", which a flat chunk list cannot answer.
   */
  papers: (query, topK = 20, docIds = []) =>
    request('/search', {
      method: 'POST',
      body: { query, top_k: topK, doc_ids: docIds, group_by_doc: true },
    }),
};

/**
 * The library graph. Derived on every request from embeddings, the analysis
 * cache and past runs -- there is no graph state to invalidate, so this is
 * simply re-fetched whenever the library or a run changes.
 */
export const graphApi = {
  get: () => request('/graph'),
};

export const analysisApi = {
  summarize: (docIds, password) =>
    llmRequest('Summarizing papers', '/analysis/summarize', {
      method: 'POST',
      body: { doc_ids: docIds, password },
    }),

  extractClaims: (docIds, password) =>
    llmRequest('Extracting claims', '/analysis/claims', {
      method: 'POST',
      body: { doc_ids: docIds, password },
    }),

  clusterThemes: (docIds, password) =>
    llmRequest('Clustering themes', '/analysis/themes', {
      method: 'POST',
      body: { doc_ids: docIds, password },
    }),

  /** past analysis runs (summaries/claims/themes), newest first */
  history: () => request('/analysis/history'),

  /** delete a single saved analysis run by id */
  deleteRun: (runId) =>
    request(`/analysis/history/${runId}`, { method: 'DELETE' }),
};

export const gapsApi = {
  analyze: (docIds, password) =>
    llmRequest('Finding research gaps', '/gaps/analyze', {
      method: 'POST',
      body: { doc_ids: docIds, password },
    }),

  /** past gap-analysis runs, newest first */
  history: () => request('/gaps/history'),

  /** delete a single saved run by id */
  deleteRun: (runId) =>
    request(`/gaps/history/${runId}`, { method: 'DELETE' }),
};

export const systemApi = {
  health: () => request('/system/health'),
  models: () => request('/system/models'),
  stats: () => request('/system/stats'),
  jobs: () => request('/system/jobs'),
  setModel: (model) =>
    request('/system/model', { method: 'POST', body: { model } }),
  // POST, not GET: it discards the cached hardware profile and looks again.
  // Reads nothing the user owns and changes no setting.
  diagnose: () => request('/system/diagnose', { method: 'POST' }),
};

/**
 * Model setup.
 *
 * The baseline model ships inside the installer, so the app is fully usable
 * offline the moment it starts. Heavier models are optional: `setup` reports
 * whether this machine can run a better one AND does not already have it (from
 * ThinkStack, Ollama or LM Studio), and only then does the UI ask permission.
 * Nothing is ever downloaded without an explicit `download` call.
 */
export const modelsApi = {
  setup: () => request('/models/setup'),
  catalog: () => request('/models/catalog'),
  download: (name) =>
    request('/models/download', { method: 'POST', body: { name } }),
  downloadStatus: () => request('/models/download/status'),
  cancelDownload: () => request('/models/download/cancel', { method: 'POST' }),
};

/**
 * The model registry: what this install has, and what each model is used for.
 *
 * Every mutating call returns a fresh `snapshot` alongside its own result, so
 * the UI re-renders from one authoritative payload instead of stitching a
 * local guess onto the previous state. Removing a model changes what every
 * OTHER card says (a task may now be uncovered), and optimistic updates would
 * show a view that never actually existed on the server.
 */
export const registryApi = {
  get: () => request('/models/registry'),
  import: (path, tasks, label = '') =>
    request('/models/registry/import', { method: 'POST', body: { path, tasks, label } }),
  update: (id, body) =>
    request(`/models/registry/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
  // deleteFile is opt-in: forgetting a model and destroying several GB of
  // weights are different intentions, and only one of them is reversible.
  // `${!!deleteFile}` renders true/false with no quotes on purpose: quotes
  // inside the template literal break the api-contract test's parser, which
  // scans this file to prove every caller hits a real route.
  remove: (id, deleteFile = false) =>
    request(`/models/registry/${encodeURIComponent(id)}?delete_file=${!!deleteFile}`, {
      method: 'DELETE',
    }),
};

/**
 * Hugging Face. The ONLY part of this client that reaches the internet.
 *
 * Every call here is the direct result of a click -- there is deliberately no
 * prefetch and no search-as-you-type, because an offline-first app that fires
 * a remote request on every keystroke is not one.
 */
export const hfApi = {
  search: (q, limit = 20) =>
    request(`/hf/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  repo: (repoId) => {
    const [owner, name] = String(repoId).split('/');
    return request(`/hf/repo/${encodeURIComponent(owner)}/${encodeURIComponent(name)}`);
  },
  download: (repoId, filename, tasks = []) =>
    request('/hf/download', {
      method: 'POST',
      body: { repo_id: repoId, filename, tasks },
    }),
};

export const encryptionApi = {
  encrypt: (docId, password) =>
    request('/encryption/encrypt', {
      method: 'POST',
      body: { doc_id: docId, password },
    }),

  decrypt: (docId, password) =>
    request('/encryption/decrypt', {
      method: 'POST',
      body: { doc_id: docId, password },
    }),

  removeEncryption: (docId, password) =>
    request('/encryption/remove', {
      method: 'POST',
      body: { doc_id: docId, password },
    }),
};

export const papersApi = {
  list: () => request('/papers/projects'),

  create: (name) =>
    request('/papers/projects', { method: 'POST', body: { name } }),

  get: (projectId) => request(`/papers/projects/${projectId}`),

  save: (projectId, source) =>
    request('/papers/save', {
      method: 'POST',
      body: { project_id: projectId, source },
    }),

  generate: (projectId, prompt, currentSource = '', { docIds = [], analysisContext = '', cursor = null } = {}) =>
    llmRequest('Generating LaTeX', '/papers/generate', {
      method: 'POST',
      body: {
        project_id: projectId,
        prompt,
        current_source: currentSource,
        // where the author is working, so the model is shown that part of the
        // document rather than its opening
        cursor,
        doc_ids: docIds,
        analysis_context: analysisContext,
      },
    }),

  compile: (projectId) =>
    request('/papers/compile', { method: 'POST', body: { project_id: projectId } }),

  remove: (projectId) =>
    request(`/papers/projects/${projectId}`, { method: 'DELETE' }),

  /* inline disposition - renders inside the preview <iframe> */
  previewUrl: (projectId) => `${BASE_URL}/papers/download/${projectId}`,

  /* attachment disposition - triggers a save-to-disk */
  downloadUrl: (projectId) => `${BASE_URL}/papers/download/${projectId}?download=1`,
};

