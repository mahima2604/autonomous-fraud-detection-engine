// MainLayout.jsx
// Shared shell for all customer-facing pages: navbar + page content + footer.
// <Outlet /> renders whichever page matched the current route.

import { Outlet } from 'react-router-dom';
import Navbar from '../components/layout/Navbar';
import Footer from '../components/layout/Footer';

function MainLayout() {
  return (
    <div className="main-layout">
      <Navbar />
      <main className="page">
        <div className="container">
          <Outlet />
        </div>
      </main>
      <Footer />
    </div>
  );
}

export default MainLayout;
