// api.js
// Centralized HTTP client configuration.
//
// Every service module in this folder should route its real (non-mock)
// requests through `apiRequest` below rather than calling fetch directly.
// That keeps the base URL, headers, and error handling in one place, so
// swapping in the real Spring Boot backend later means changing this file
// (and flipping VITE_USE_MOCKS to false) — not touching UI components.

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8080/api';

// USE_MOCKS gates every service function between local mock data and a
// real network call. Set VITE_USE_MOCKS=false in your .env once the
// backend is reachable.
export const USE_MOCKS = (import.meta.env.VITE_USE_MOCKS ?? 'true') !== 'false';

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

  let response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...rest,
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch {
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
    throw new ApiError(message, response.status, data);
  }

  return data;
}

/** Simulates network latency for mock service calls so loading states are visible/testable. */
export function mockDelay(ms = 500) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export { ApiError };
