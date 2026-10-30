// Login.jsx
// Polished customer authentication screen for SecureCart shoppers.

import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/auth';
import { isValidEmail, isNotEmpty } from '../utils/validators';
import LoadingSpinner from '../components/common/LoadingSpinner';
import './AuthForm.css';

function Login() {
  const { login, role: currentRole, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();

  const [form, setForm] = useState({ email: '', password: '' });
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState({});
  const [submitError, setSubmitError] = useState('');
  const [loading, setLoading] = useState(false);

  // If role=admin is requested in query param, redirect to dedicated admin login
  const requestedRole = searchParams.get('role');
  if (requestedRole === 'admin') {
    return <Navigate to="/admin/login" replace />;
  }

  if (authLoading) return <LoadingSpinner label="Checking your session..." />;
  if (currentRole === 'admin') return <Navigate to="/admin/dashboard" replace />;
  if (currentRole === 'user') return <Navigate to={location.state?.from?.pathname || '/dashboard'} replace />;

  function validate() {
    const next = {};
    if (!isValidEmail(form.email)) next.email = 'Enter a valid email address.';
    if (!isNotEmpty(form.password)) next.password = 'Password is required.';
    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setSubmitError('');
    if (!validate()) return;
    setLoading(true);
    try {
      await login(form);
      navigate(location.state?.from?.pathname || '/dashboard', { replace: true });
    } catch (err) {
      setSubmitError(err.message || 'Invalid email or password. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card-wrapper">
        {/* Top brand icon */}
        <div className="auth-brand-center">
          <Link to="/" className="auth-brand-link">
            <div className="auth-shield-icon" aria-hidden="true">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="M9 12l2 2 4-4" />
              </svg>
            </div>
            <span className="auth-brand-name">SecureCart</span>
          </Link>
        </div>

        <div className="card auth-card">
          <div className="auth-header">
            <h2>Welcome Back</h2>
            <p>Sign in to manage your orders and enjoy protected checkout.</p>
          </div>

          {submitError && (
            <div className="form-error-banner" role="alert">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <span>{submitError}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate className="auth-form">
            <div className="field">
              <label htmlFor="customer-email">Email Address</label>
              <div className="input-with-icon">
                <svg className="field-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                  <polyline points="22,6 12,13 2,6" />
                </svg>
                <input
                  id="customer-email"
                  type="email"
                  autoComplete="email"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  aria-invalid={Boolean(errors.email)}
                />
              </div>
              {errors.email && <div className="field-error">{errors.email}</div>}
            </div>

            <div className="field">
              <div className="field-label-row">
                <label htmlFor="customer-password">Password</label>
              </div>
              <div className="input-with-icon">
                <svg className="field-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                </svg>
                <input
                  id="customer-password"
                  type={showPassword ? 'text' : 'password'}
                  autoComplete="current-password"
                  value={form.password}
                  onChange={(e) => setForm({ ...form, password: e.target.value })}
                  aria-invalid={Boolean(errors.password)}
                />
                <button
                  type="button"
                  className="btn-toggle-password"
                  onClick={() => setShowPassword((prev) => !prev)}
                  title={showPassword ? 'Hide password' : 'Show password'}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? (
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
                      <line x1="1" y1="1" x2="23" y2="23" />
                    </svg>
                  ) : (
                    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                      <circle cx="12" cy="12" r="3" />
                    </svg>
                  )}
                </button>
              </div>
              {errors.password && <div className="field-error">{errors.password}</div>}
            </div>

            <button
              id="customer-signin-btn"
              type="submit"
              className="btn btn-primary btn-block auth-submit-btn"
              disabled={loading}
            >
              {loading ? (
                <>
                  <span className="spinner spinner-white" />
                  <span>Signing In...</span>
                </>
              ) : (
                <span>Sign In</span>
              )}
            </button>
          </form>

          <div className="auth-footer-prompt">
            <span>Don't have an account?</span>
            <Link to="/register" className="auth-inline-link">
              Create an account
            </Link>
          </div>
        </div>

        {/* Discreet link to admin console */}
        <div className="auth-admin-footnote">
          <span>Security Personnel & Administrators:</span>
          <Link to="/admin/login">Admin Console Access &rarr;</Link>
        </div>
      </div>
    </div>
  );
}

export default Login;
