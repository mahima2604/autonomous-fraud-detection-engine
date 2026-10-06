// AdminLayout.jsx
// Separate shell for the admin fraud-monitoring area, distinguished from
// the customer storefront so it reads as an internal tool.

import { Outlet, Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

function AdminLayout() {
  const navigate = useNavigate();
  const { logout } = useAuth();

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <div className="admin-layout">
      <header style={{ background: 'var(--color-primary)', color: '#fff' }}>
        <div className="container" style={{ height: 60, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontWeight: 800, letterSpacing: '-0.02em' }}>SecureCart Admin</span>
          <div style={{ display: 'flex', gap: '16px', alignItems: 'center' }}>
            <Link to="/admin/dashboard" style={{ color: '#fff', fontSize: 13.5, textDecoration: 'none', opacity: 0.85 }}>
              Dashboard
            </Link>
            <Link to="/admin/dashboard#fraud-predictions" style={{ color: '#fff', fontSize: 13.5, textDecoration: 'none', opacity: 0.85 }}>Fraud predictions</Link>
            <Link to="/admin/customers" style={{ color: '#fff', fontSize: 13.5, textDecoration: 'none', opacity: 0.85 }}>Customers</Link>
            <Link to="/admin/dashboard#transactions" style={{ color: '#fff', fontSize: 13.5, textDecoration: 'none', opacity: 0.85 }}>Transactions</Link>
            <button 
              onClick={handleLogout} 
              style={{ background: 'transparent', border: '1px solid rgba(255,255,255,0.3)', color: '#fff', padding: '4px 12px', borderRadius: '4px', cursor: 'pointer', fontSize: 12 }}
            >
              Logout
            </button>
          </div>
        </div>
      </header>
      <main className="page">
        <div className="container">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

export default AdminLayout;
