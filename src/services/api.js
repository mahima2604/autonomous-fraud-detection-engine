// api.js
// Centralized client for the FastAPI backend.

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000/api';

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
  const { body, headers, ...rest } = options;

  const token = localStorage.getItem('auth_token');

  const method = (rest.method || 'GET').toUpperCase();
  const url = `${API_BASE_URL}${path}`;
  let response;
  try {
    response = await fetch(url, {
      ...rest,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (error) {
    console.error('[apiRequest] Fetch/network failure', {
      method,
      url,
      errorName: error?.name || 'Error',
      message: error?.message || 'Request failed before a response was received',
    });
    throw new ApiError('Unable to reach the server. Please try again.', 0, null);
  }

  let data = null;
  const text = await response.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!response.ok) {
    const message = (data && data.detail) || (data && data.message) || `Request failed with status ${response.status}`;
    console.warn('[apiRequest] HTTP error response', { method, url, status: response.status, message });
    throw new ApiError(message, response.status, data);
  }

  return data;
}

export { ApiError };
