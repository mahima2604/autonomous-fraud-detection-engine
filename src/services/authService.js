// authService.js
// Auth calls the frontend will need. Backed by mock logic (isolated below)
// until POST /api/auth/login and POST /api/auth/register are available.
//
// SECURITY NOTE: mock auth stores a fake token in localStorage purely to
// simulate a logged-in session for UI development. This is NOT secure and
// is not a substitute for real backend-issued, verified authentication.

import { apiRequest, USE_MOCKS, mockDelay } from './api';

const MOCK_USERS_KEY = 'mock_users';

function readMockUsers() {
  try {
    return JSON.parse(localStorage.getItem(MOCK_USERS_KEY)) || [];
  } catch {
    return [];
  }
}

function writeMockUsers(users) {
  localStorage.setItem(MOCK_USERS_KEY, JSON.stringify(users));
}

export async function login({ email, password }) {
  if (USE_MOCKS) {
    await mockDelay(600);
    const users = readMockUsers();
    const user = users.find((u) => u.email === email && u.password === password);
    if (!user) {
      throw new Error('Invalid email or password.');
    }
    const token = `mock-token-${user.id}`;
    return { token, user: { id: user.id, name: user.name, email: user.email } };
  }

  // Real backend call: POST /api/auth/login
  return apiRequest('/auth/login', { method: 'POST', body: { email, password } });
}

export async function register({ name, email, password }) {
  if (USE_MOCKS) {
    await mockDelay(600);
    const users = readMockUsers();
    if (users.some((u) => u.email === email)) {
      throw new Error('An account with this email already exists.');
    }
    const newUser = { id: `u-${Date.now()}`, name, email, password };
    writeMockUsers([...users, newUser]);
    const token = `mock-token-${newUser.id}`;
    return { token, user: { id: newUser.id, name: newUser.name, email: newUser.email } };
  }

  // Real backend call: POST /api/auth/register
  return apiRequest('/auth/register', { method: 'POST', body: { name, email, password } });
}

export function logout() {
  localStorage.removeItem('auth_token');
  localStorage.removeItem('auth_user');
}
