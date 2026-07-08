/**
 * api client utility for scholarlens backend.
 *
 * provides typed fetch wrappers for all backend endpoints
 * with consistent error handling and response parsing.
 */

import { useSyncExternalStore } from 'react';

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
};

export const searchApi = {
  search: (query, topK = 10, docIds = []) =>
    request('/search', {
      method: 'POST',
      body: { query, top_k: topK, doc_ids: docIds },
    }),
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
};

export const gapsApi = {
  analyze: (docIds, password) =>
    llmRequest('Finding research gaps', '/gaps/analyze', {
      method: 'POST',
      body: { doc_ids: docIds, password },
    }),
};

export const chatApi = {
  /**
   * ask the rag chat assistant a question.
   *
   * @param {string} message - the user's question.
   * @param {object} [opts] - optional scope and grounding.
   * @param {string[]} [opts.docIds] - restrict retrieval to these documents.
   * @param {{role: string, content: string}[]} [opts.history] - prior turns.
   * @param {string} [opts.context] - current analysis results as extra context.
   */
  send: (message, { docIds = [], history = [], context = '' } = {}) =>
    llmRequest('Assistant thinking', '/chat', {
      method: 'POST',
      body: { message, doc_ids: docIds, history, context },
    }),
};

export const systemApi = {
  health: () => request('/system/health'),
  models: () => request('/system/models'),
  stats: () => request('/system/stats'),
  setModel: (model) =>
    request('/system/model', { method: 'POST', body: { model } }),
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

  generate: (projectId, prompt, currentSource = '', { docIds = [], analysisContext = '' } = {}) =>
    llmRequest('Generating LaTeX', '/papers/generate', {
      method: 'POST',
      body: {
        project_id: projectId,
        prompt,
        current_source: currentSource,
        doc_ids: docIds,
        analysis_context: analysisContext,
      },
    }),

  compile: (projectId) =>
    request('/papers/compile', { method: 'POST', body: { project_id: projectId } }),

  remove: (projectId) =>
    request(`/papers/projects/${projectId}`, { method: 'DELETE' }),

  downloadUrl: (projectId) => `${BASE_URL}/papers/download/${projectId}`,
};

