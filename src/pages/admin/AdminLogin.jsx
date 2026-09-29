// AdminLogin.jsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import './AdminLogin.css';

function AdminLogin() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const handleLogin = (e) => {
    e.preventDefault();
    setError('');

    // Demo admin authentication for college project
    if (email === 'admin@securecart.com' && password === 'Admin@123') {
      localStorage.setItem('admin_authenticated', 'true');
      navigate('/admin/fraud-dashboard');
    } else {
      setError('Invalid admin credentials. Please try again.');
    }
  };

  return (
    <div className="admin-login-container">
      <div className="admin-login-card card">
        <h2 className="admin-login-title">Admin Login</h2>
        <p className="admin-login-subtitle">
          SecureCart Fraud Monitoring Access
        </p>
        
        {error && <div className="admin-login-error">{error}</div>}
        
        <form onSubmit={handleLogin} className="admin-login-form">
          <div className="form-group">
            <label htmlFor="email">Email</label>
            <input
              type="email"
              id="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              type="password"
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <button type="submit" className="btn btn-primary admin-login-btn">
            Login to Dashboard
          </button>
        </form>

        <div className="admin-demo-note">
          <strong>Note:</strong> Demo admin access for project evaluation.
          <br />
          Email: <code>admin@securecart.com</code>
          <br />
          Password: <code>Admin@123</code>
        </div>
      </div>
    </div>
  );
}

export default AdminLogin;
