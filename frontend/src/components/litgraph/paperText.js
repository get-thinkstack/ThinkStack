import { documentsApi } from '../../utils/api';

/**
 * The papers' extracted text, fetched once each.
 *
 * Two panels need it now. The reader needs it to know which passage a claim
 * rests on; the gap panel needs it to find that gap's evidence in every paper
 * it cites, which means several documents at once and usually the ones you are
 * about to open. Sharing the cache means opening a gap warms the reader rather
 * than fetching the same papers twice.
 *
 * It holds the in-flight PROMISE, not the resolved document. Caching the result
 * instead deadlocks under StrictMode's double-invoked effects: the first run's
 * cleanup cancels its own setState, the second run finds the cache already warm
 * and returns without setting anything, and the reader sits on "Loading the
 * paper" forever with the text sitting in the cache beside it. Awaiting one
 * shared promise also means one request per paper however many times it is
 * opened.
 *
 * ponytail: unbounded map. A library is a few dozen papers on one desktop --
 * add an LRU if that ever stops being true.
 */
const textCache = new Map();

export function fetchPaper(id) {
  if (!textCache.has(id)) textCache.set(id, documentsApi.get(id));
  return textCache.get(id);
}

/** A failure must not cache as one; the next open should try again. */
export function forgetPaper(id) {
  textCache.delete(id);
}
