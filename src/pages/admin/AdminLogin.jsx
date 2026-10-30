// AdminLogin.jsx
// Dedicated, security-focused authentication portal for SecureCart Administrators.

import { useState } from 'react';
import { Link, Navigate, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/auth';
import { isValidEmail, isNotEmpty } from '../../utils/validators';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import './AdminLogin.css';

function AdminLogin() {
  const { loginAdmin, role: currentRole, loading: authLoading } = useAuth();
  const navigate = useNavigate();

  const [form, setForm] = useState({ email: '', password: '' });
  const [showPassword, setShowPassword] = useState(false);
  const [errors, setErrors] = useState({});
  const [submitError, setSubmitError] = useState('');
  const [loading, setLoading] = useState(false);

  if (authLoading) return <LoadingSpinner label="Checking security session..." />;
  if (currentRole === 'admin') return <Navigate to="/admin/dashboard" replace />;
  if (currentRole === 'user') return <Navigate to="/dashboard" replace />;

  function validate() {
    const next = {};
    if (!isValidEmail(form.email)) next.email = 'Enter a valid administrator email.';
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
      await loginAdmin(form);
      navigate('/admin/dashboard', { replace: true });
    } catch (err) {
      setSubmitError(err.message || 'Invalid administrator credentials or unauthorized access.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="admin-login-page">
      <div className="admin-login-container">
        {/* Top Back Link */}
        <div className="admin-login-topbar">
          <Link to="/" className="admin-back-store-link">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M19 12H5M12 19l-7-7 7-7" />
            </svg>
            <span>Back to Storefront</span>
          </Link>
          <span className="admin-security-badge">
            <span className="admin-pulse-dot" />
            Protected administrator access
          </span>
        </div>

        {/* Security Card */}
        <div className="admin-login-card">
          <div className="admin-login-brand">
            <div className="admin-shield-icon" aria-hidden="true">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="M9 12l2 2 4-4" />
              </svg>
            </div>
            <div>
              <h1 className="admin-brand-title">SecureCart</h1>
              <span className="admin-brand-sub">Fraud Intelligence Console</span>
            </div>
          </div>

          <div className="admin-login-header">
            <h2>Admin Sign In</h2>
            <p>Authorized fraud analysts and platform operators only.</p>
          </div>

          <div className="admin-security-notice" role="note">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            <span>Restricted system: All login attempts and review actions are audited.</span>
          </div>

          {submitError && (
            <div className="admin-login-error" role="alert">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="12" cy="12" r="10" />
                <line x1="12" y1="8" x2="12" y2="12" />
                <line x1="12" y1="16" x2="12.01" y2="16" />
              </svg>
              <span>{submitError}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} noValidate className="admin-login-form">
            <div className="field">
              <label htmlFor="admin-email">Administrator Email</label>
              <div className="input-with-icon">
                <svg className="field-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                  <polyline points="22,6 12,13 2,6" />
                </svg>
                <input
                  id="admin-email"
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
              <label htmlFor="admin-password">Console Password</label>
              <div className="input-with-icon">
                <svg className="field-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                  <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                </svg>
                <input
                  id="admin-password"
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
              id="admin-submit-btn"
              type="submit"
              className="btn-admin-submit"
              disabled={loading}
            >
              {loading ? (
                <>
                  <span className="spinner spinner-white" />
                  <span>Verifying Credentials...</span>
                </>
              ) : (
                <>
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                    <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
                    <polyline points="10 17 15 12 10 7" />
                    <line x1="15" y1="12" x2="3" y2="12" />
                  </svg>
                  <span>Sign In to Admin Console</span>
                </>
              )}
            </button>
          </form>

          <div className="admin-login-footer">
            <span>Customer account?</span>
            <Link to="/login" className="admin-customer-login-link">
              Go to Customer Login →
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

export default AdminLogin;
