// Login.jsx
import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { isValidEmail, isNotEmpty } from '../utils/validators';
import LoadingSpinner from '../components/common/LoadingSpinner';
import './AuthForm.css';

function Login() {
  const { login, loginAdmin, role: currentRole, loading: authLoading } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const [selectedRole, setSelectedRole] = useState(searchParams.get('role') === 'admin' ? 'admin' : 'user');

  const [form, setForm] = useState({ email: '', password: '' });
  const [errors, setErrors] = useState({});
  const [submitError, setSubmitError] = useState('');
  const [loading, setLoading] = useState(false);

  if (authLoading) return <LoadingSpinner label="Checking your sessionâ€¦" />;
  if (currentRole === 'admin') return <Navigate to="/admin/dashboard" replace />;
  if (currentRole === 'user') return <Navigate to="/dashboard" replace />;

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
      if (selectedRole === 'admin') {
        await loginAdmin(form);
        navigate('/admin/dashboard', { replace: true });
      } else {
        await login(form);
        navigate(location.state?.from?.pathname || '/dashboard', { replace: true });
      }
    } catch (err) {
      setSubmitError(err.message || 'Login failed. Please try again.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="card card-padded auth-card login-card">
        <div className="login-brand">
          <strong>SecureCart</strong>
          <span>E-Commerce Fraud Protection</span>
        </div>
        <p className="login-prompt">Continue as</p>
        <div className="role-selector" role="group" aria-label="Choose account type">
          <button
            type="button"
            className={`role-choice ${selectedRole === 'user' ? 'active' : ''}`}
            onClick={() => { setSelectedRole('user'); setSubmitError(''); }}
          >
            <strong>User</strong>
            <span>Shop, checkout and manage your orders</span>
          </button>
          <button
            type="button"
            className={`role-choice ${selectedRole === 'admin' ? 'active' : ''}`}
            onClick={() => { setSelectedRole('admin'); setSubmitError(''); }}
          >
            <strong>Admin</strong>
            <span>Monitor transactions and fraud activity</span>
          </button>
        </div>

        <h2>{selectedRole === 'admin' ? 'Admin Login' : 'User Login'}</h2>
        <p style={{ marginBottom: 20 }}>Enter your details to continue.</p>

        {submitError && <div className="form-error-banner">{submitError}</div>}

        <form onSubmit={handleSubmit} noValidate>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              value={form.email}
              onChange={(e) => setForm({ ...form, email: e.target.value })}
            />
            {errors.email && <div className="field-error">{errors.email}</div>}
          </div>

          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={form.password}
              onChange={(e) => setForm({ ...form, password: e.target.value })}
            />
            {errors.password && <div className="field-error">{errors.password}</div>}
          </div>

          <button className="btn btn-primary btn-block" type="submit" disabled={loading}>
            {loading ? 'Logging inâ€¦' : `Continue as ${selectedRole === 'admin' ? 'Admin' : 'User'}`}
          </button>
        </form>

        {selectedRole === 'user' ? (
          <>
            <p style={{ marginTop: 16, fontSize: 13.5 }}>
              Donâ€™t have an account? <Link to="/register">Sign up</Link>
            </p>
            <p className="mock-note">Customer authentication uses your SecureCart account.</p>
          </>
        ) : (
          <p className="mock-note admin-demo-credentials">
            Demo admin: <code>admin@securecart.com</code> / <code>Admin@123</code>
          </p>
        )}
      </div>
    </div>
  );
}

export default Login;
