import { apiRequest } from './api';

export async function login({ email, password }) {
  localStorage.removeItem("mock_users");
  const result = await apiRequest('/auth/login', { method: 'POST', body: { email, password } });
  return { token: result.access_token, user: result.user };
}

export async function loginAdmin({ email, password }) {
  const result = await apiRequest('/admin/auth/login', { method: 'POST', body: { email, password } });
  return { token: result.access_token, user: result.admin };
}

export async function register({ name, email, password }) {
  localStorage.removeItem("mock_users");
  const result = await apiRequest('/auth/register', { method: 'POST', body: { name, email, password } });
  return { token: result.access_token, user: result.user };
}

export function logout() {
  localStorage.removeItem('auth_token');
  localStorage.removeItem('auth_user');
  // Discard legacy demo accounts, which may contain plaintext passwords.
  localStorage.removeItem('mock_users');
}
