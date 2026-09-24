// AdminLayout.jsx
// Separate shell for the admin fraud-monitoring area, distinguished from
// the customer storefront so it reads as an internal tool.

import { Outlet, Link } from 'react-router-dom';

function AdminLayout() {
  return (
    <div className="admin-layout">
      <header style={{ background: 'var(--color-primary)', color: '#fff' }}>
        <div className="container" style={{ height: 60, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{ fontWeight: 800, letterSpacing: '-0.02em' }}>SecureCart Admin</span>
          <Link to="/" style={{ color: '#fff', fontSize: 13.5, textDecoration: 'none', opacity: 0.85 }}>
            ← Back to storefront
          </Link>
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
