// AuthContext.jsx
// Global authentication state. Wraps mock login/register for now (see
// services/authService.js) â€” the shape of `user` and `token` here is
// designed to map directly onto whatever the real backend returns later.

import { createContext, useContext, useEffect, useState } from 'react';
import * as authService from '../services/authService';

const AuthContext = createContext(null);
const ROLE_KEY = 'auth_role';

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [role, setRole] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const storedUser = localStorage.getItem('auth_user');
    const storedToken = localStorage.getItem('auth_token');

    const storedRole = localStorage.getItem(ROLE_KEY);
    localStorage.removeItem('admin_authenticated');

    if (storedUser && storedToken && !storedToken.startsWith("mock-token-")) {
      try {
        const parsedUser = JSON.parse(storedUser);
        setUser(parsedUser);
        const restoredRole = storedRole === 'admin' ? 'admin' : 'user';
        setRole(restoredRole);
        localStorage.setItem(ROLE_KEY, restoredRole);
      } catch {
        authService.logout();
        localStorage.removeItem(ROLE_KEY);
      }
    } else if (storedToken?.startsWith("mock-token-")) {
      authService.logout();
      localStorage.removeItem(ROLE_KEY);
    }
    setLoading(false);
  }, []);

  async function login(credentials) {
    const { token, user: loggedInUser } = await authService.login(credentials);
    localStorage.setItem(ROLE_KEY, 'user');
    localStorage.setItem('auth_token', token);
    localStorage.setItem('auth_user', JSON.stringify(loggedInUser));
    setUser(loggedInUser);
    setRole('user');
    return loggedInUser;
  }

  async function register(details) {
    const { token, user: newUser } = await authService.register(details);
    localStorage.setItem(ROLE_KEY, 'user');
    localStorage.setItem('auth_token', token);
    localStorage.setItem('auth_user', JSON.stringify(newUser));
    setUser(newUser);
    setRole('user');
    return newUser;
  }

  async function loginAdmin(credentials) {
    authService.logout();
    const { token, user: adminUser } = await authService.loginAdmin(credentials);
    localStorage.setItem(ROLE_KEY, 'admin');
    localStorage.setItem('auth_token', token);
    localStorage.setItem('auth_user', JSON.stringify(adminUser));
    setUser(adminUser);
    setRole('admin');
    return adminUser;
  }

  function logout() {
    authService.logout();
    localStorage.removeItem(ROLE_KEY);
    setUser(null);
    setRole(null);
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

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider');
  return ctx;
}
