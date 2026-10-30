// api.js
// Centralized client for the FastAPI backend.

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api';
export const API_REQUEST_TIMEOUT_MS = 30_000;

class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

/**
 * Thin wrapper around fetch for JSON APIs.
 * @param {string} path - path relative to API_BASE_URL, e.g. '/auth/login'
 * @param {object} options - fetch options (method, body, headers...)
 */
export async function apiRequest(path, options = {}) {
  const {
    body,
    headers,
    timeoutMs = API_REQUEST_TIMEOUT_MS,
    signal: requestSignal,
    ...rest
  } = options;

  const token = localStorage.getItem('auth_token');

  const method = (rest.method || 'GET').toUpperCase();
  const url = `${API_BASE_URL}${path}`;
  let response;
  let data = null;
  const controller = new AbortController();
  let timedOut = false;
  const timeoutId = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const forwardAbort = () => controller.abort(requestSignal.reason);
  if (requestSignal?.aborted) {
    forwardAbort();
  } else {
    requestSignal?.addEventListener('abort', forwardAbort, { once: true });
  }

  try {
    response = await fetch(url, {
      ...rest,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
    const text = await response.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = text;
      }
    }
  } catch (error) {
    console.error('[apiRequest] Fetch/network failure', {
      method,
      url,
      errorName: error?.name || 'Error',
      message: error?.message || 'Request failed before a response was received',
    });
    const message = timedOut
      ? 'The server did not respond in time. Please check that it is running and try again.'
      : requestSignal?.aborted
        ? 'The request was cancelled. Please try again.'
        : 'Unable to reach the server. Please try again.';
    throw new ApiError(message, 0, null);
  } finally {
    clearTimeout(timeoutId);
    requestSignal?.removeEventListener('abort', forwardAbort);
  }

  if (!response.ok) {
    const message = (data && data.detail) || (data && data.message) || `Request failed with status ${response.status}`;
    console.warn('[apiRequest] HTTP error response', { method, url, status: response.status, message });
    throw new ApiError(message, response.status, data);
  }

  return data;
}

export { ApiError };
