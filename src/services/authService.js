import { apiRequest } from './api';

const AUTH_REQUEST_TIMEOUT_MS = 15_000;

export async function login({ email, password }) {
  localStorage.removeItem("mock_users");
  localStorage.removeItem("cart_items_guest");
  localStorage.removeItem("cart_items");
  sessionStorage.removeItem("last_order");
  const result = await apiRequest('/auth/login', {
    method: 'POST',
    body: { email, password },
    timeoutMs: AUTH_REQUEST_TIMEOUT_MS,
  });
  return { token: result.access_token, user: result.user };
}

export async function loginAdmin({ email, password }) {
  const result = await apiRequest('/admin/auth/login', {
    method: 'POST',
    body: { email, password },
    timeoutMs: AUTH_REQUEST_TIMEOUT_MS,
  });
  return { token: result.access_token, user: result.admin };
}

export async function register({ name, email, password }) {
  localStorage.removeItem("mock_users");
  localStorage.removeItem("cart_items_guest");
  localStorage.removeItem("cart_items");
  sessionStorage.removeItem("last_order");
  const result = await apiRequest('/auth/register', {
    method: 'POST',
    body: { name, email, password },
    timeoutMs: AUTH_REQUEST_TIMEOUT_MS,
  });
  return { token: result.access_token, user: result.user };
}

export function logout() {
  localStorage.removeItem('auth_token');
  localStorage.removeItem('auth_user');
  // Discard legacy demo accounts, which may contain plaintext passwords.
  localStorage.removeItem('mock_users');
  localStorage.removeItem('cart_items_guest');
  localStorage.removeItem('cart_items');
  sessionStorage.removeItem('last_order');
}
