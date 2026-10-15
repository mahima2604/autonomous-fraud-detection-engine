// AdminLayout.jsx
// Enterprise-grade SaaS navigation shell for SecureCart Fraud Detection & Prevention Engine.

import { Outlet, NavLink, Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import './AdminLayout.css';

function AdminLayout() {
  const navigate = useNavigate();
  const location = useLocation();
  const { logout, user } = useAuth();

  const handleLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  const isFraudMonitoringActive = location.pathname === '/admin/dashboard' && location.hash === '#fraud-predictions';
  const isDashboardOverviewActive = location.pathname === '/admin/dashboard' && location.hash !== '#fraud-predictions';

  return (
    <div className="admin-layout">
      <header className="admin-topbar">
        <div className="admin-topbar-inner">
          <div className="admin-brand-section">
            <Link to="/admin/dashboard" className="admin-brand-link">
              <div className="admin-brand-icon" aria-hidden="true">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                  <path d="M9 12l2 2 4-4" />
                </svg>
              </div>
              <div className="admin-brand-text">
                <span className="admin-brand-name">SecureCart</span>
                <span className="admin-brand-tag">FRAUD ENGINE</span>
              </div>
            </Link>
          </div>

          <nav className="admin-nav" aria-label="Admin navigation">
            <NavLink
              to="/admin/dashboard"
              end
              className={({ isActive }) =>
                `admin-nav-link ${isActive && isDashboardOverviewActive ? 'active' : ''}`
              }
            >
              <svg className="admin-nav-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="7" height="7" />
                <rect x="14" y="3" width="7" height="7" />
                <rect x="14" y="14" width="7" height="7" />
                <rect x="3" y="14" width="7" height="7" />
              </svg>
              <span>Dashboard</span>
            </NavLink>

            <Link
              to="/admin/dashboard#fraud-predictions"
              className={`admin-nav-link ${isFraudMonitoringActive ? 'active' : ''}`}
            >
              <svg className="admin-nav-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2z" />
                <path d="M12 6v6l4 2" />
              </svg>
              <span>Fraud Monitoring</span>
            </Link>

            <NavLink
              to="/admin/transactions"
              className={({ isActive }) => `admin-nav-link ${isActive ? 'active' : ''}`}
            >
              <svg className="admin-nav-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="8" y1="6" x2="21" y2="6" />
                <line x1="8" y1="12" x2="21" y2="12" />
                <line x1="8" y1="18" x2="21" y2="18" />
                <line x1="3" y1="6" x2="3.01" y2="6" />
                <line x1="3" y1="12" x2="3.01" y2="12" />
                <line x1="3" y1="18" x2="3.01" y2="18" />
              </svg>
              <span>Transactions</span>
            </NavLink>

            <NavLink
              to="/admin/customers"
              className={({ isActive }) => `admin-nav-link ${isActive ? 'active' : ''}`}
            >
              <svg className="admin-nav-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
                <circle cx="9" cy="7" r="4" />
                <path d="M23 21v-2a4 4 0 0 0-3-3.87" />
                <path d="M16 3.13a4 4 0 0 1 0 7.75" />
              </svg>
              <span>Customers</span>
            </NavLink>
          </nav>

          <div className="admin-topbar-actions">
            <div className="admin-status-indicator" title="Live Fraud Engine: Baseline Logistic Regression model actively scoring checkout transactions (GNN model is in offline research mode)">
              <span className="admin-status-dot" />
              <span className="admin-status-text">Active Engine</span>
            </div>

            <Link to="/products" className="admin-store-link" title="Open Customer Storefront">
              <span>Storefront</span>
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                <polyline points="15 3 21 3 21 9" />
                <line x1="10" y1="14" x2="21" y2="3" />
              </svg>
            </Link>

            <div className="admin-user-pill">
              <span className="admin-avatar">A</span>
              <span className="admin-user-email">{user?.email || 'admin@securecart.com'}</span>
            </div>

            <button onClick={handleLogout} className="admin-logout-button" title="Sign out of Admin Panel">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                <polyline points="16 17 21 12 16 7" />
                <line x1="21" y1="12" x2="9" y2="12" />
              </svg>
              <span>Logout</span>
            </button>
          </div>
        </div>
      </header>

      <main className="page admin-page">
        <div className="admin-content-container">
          <Outlet />
        </div>
      </main>
    </div>
  );
}

export default AdminLayout;
