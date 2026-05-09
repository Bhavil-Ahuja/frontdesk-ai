/**
 * Authenticated fetch helper. Automatically attaches the JWT from localStorage
 * to outgoing requests. Throws on non-2xx responses with the server's detail.
 */

const TOKEN_KEY = 'scheduler_ai_token';

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
  } else {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

/**
 * apiFetch — fetch wrapper that attaches Bearer token and parses JSON.
 *
 * @param {string} path  — URL path (e.g. /api/auth/me)
 * @param {object} options — fetch options. Body objects are JSON-stringified.
 * @returns {Promise<any>} — parsed JSON response
 * @throws {ApiError} — on non-2xx responses
 */
export async function apiFetch(path, options = {}) {
  const token = getToken();
  const headers = {
    Accept: 'application/json',
    ...(options.headers || {}),
  };

  // Attach Bearer token if present
  if (token && !headers.Authorization) {
    headers.Authorization = `Bearer ${token}`;
  }

  // Auto-stringify object bodies
  let body = options.body;
  if (body && typeof body === 'object' && !(body instanceof FormData)) {
    body = JSON.stringify(body);
    if (!headers['Content-Type']) headers['Content-Type'] = 'application/json';
  }

  const res = await fetch(path, { ...options, headers, body });

  // 401 → token expired/invalid, clear and let UI handle redirect
  if (res.status === 401) {
    clearToken();
    const data = await res.json().catch(() => ({}));
    throw new ApiError(data.detail || 'Unauthorized', 401, data);
  }

  // Parse JSON if possible
  const contentType = res.headers.get('content-type') || '';
  let data = null;
  if (contentType.includes('application/json')) {
    data = await res.json().catch(() => null);
  } else if (res.ok) {
    data = await res.text();
  }

  if (!res.ok) {
    const message =
      (data && (data.detail || data.message)) ||
      `Request failed with status ${res.status}`;
    throw new ApiError(message, res.status, data);
  }

  return data;
}
