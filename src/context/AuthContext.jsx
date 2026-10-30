// AuthContext.jsx
// Global authentication state. Wraps login/register and restores session
// immediately from localStorage on startup.

import { useState } from 'react';
import * as authService from '../services/authService';
import { AuthContext } from './auth';

const ROLE_KEY = 'auth_role';

function getInitialAuthState() {
  try {
    const storedUser = localStorage.getItem('auth_user');
    const storedToken = localStorage.getItem('auth_token');
    const storedRole = localStorage.getItem(ROLE_KEY);
    localStorage.removeItem('admin_authenticated');

    if (storedUser && storedToken && !storedToken.startsWith('mock-token-')) {
      const parsedUser = JSON.parse(storedUser);
      const restoredRole = storedRole === 'admin' ? 'admin' : 'user';
      return { user: parsedUser, role: restoredRole };
    } else if (storedToken?.startsWith('mock-token-')) {
      authService.logout();
      localStorage.removeItem(ROLE_KEY);
    }
  } catch {
    authService.logout();
    localStorage.removeItem(ROLE_KEY);
  }
  return { user: null, role: null };
}

export function AuthProvider({ children }) {
  const [authState, setAuthState] = useState(getInitialAuthState);
  const loading = false;

  const user = authState.user;
  const role = authState.role;

  async function login(credentials) {
    localStorage.removeItem('cart_items_guest');
    localStorage.removeItem('cart_items');
    sessionStorage.removeItem('last_order');

    const { token, user: loggedInUser } = await authService.login(credentials);
    localStorage.setItem(ROLE_KEY, 'user');
    localStorage.setItem('auth_token', token);
    localStorage.setItem('auth_user', JSON.stringify(loggedInUser));
    setAuthState({ user: loggedInUser, role: 'user' });
    return loggedInUser;
  }

  async function register(details) {
    localStorage.removeItem('cart_items_guest');
    localStorage.removeItem('cart_items');
    sessionStorage.removeItem('last_order');

    const { token, user: newUser } = await authService.register(details);
    localStorage.setItem(ROLE_KEY, 'user');
    localStorage.setItem('auth_token', token);
    localStorage.setItem('auth_user', JSON.stringify(newUser));
    setAuthState({ user: newUser, role: 'user' });
    return newUser;
  }

  async function loginAdmin(credentials) {
    authService.logout();
    const { token, user: adminUser } = await authService.loginAdmin(credentials);
    localStorage.setItem(ROLE_KEY, 'admin');
    localStorage.setItem('auth_token', token);
    localStorage.setItem('auth_user', JSON.stringify(adminUser));
    setAuthState({ user: adminUser, role: 'admin' });
    return adminUser;
  }

  function logout() {
    authService.logout();
    localStorage.removeItem(ROLE_KEY);
    localStorage.removeItem('cart_items_guest');
    localStorage.removeItem('cart_items');
    sessionStorage.removeItem('last_order');
    setAuthState({ user: null, role: null });
  }

  const value = {
    user,
    role,
    isAuthenticated: role === 'user' || role === 'admin',
    isUserAuthenticated: role === 'user',
    isAdminAuthenticated: role === 'admin',
    loading,
    login,
    register,
    loginAdmin,
    logout,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
