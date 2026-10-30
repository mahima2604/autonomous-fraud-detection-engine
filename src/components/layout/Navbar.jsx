// Navbar.jsx — Primary site navigation shared by every customer page via MainLayout.
import { useState } from 'react';
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/auth';
import { useCart } from '../../context/cart';
import './Navbar.css';

function Navbar() {
  const { user, role, isAuthenticated, logout } = useAuth();
  const { itemCount } = useCart();
  const navigate = useNavigate();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [navSearch, setNavSearch] = useState('');

  function handleLogout() {
    logout();
    setMobileMenuOpen(false);
    navigate('/login');
  }

  function handleSearchSubmit(e) {
    e.preventDefault();
    if (navSearch.trim()) {
      navigate(`/products?search=${encodeURIComponent(navSearch.trim())}`);
      setNavSearch('');
      setMobileMenuOpen(false);
    }
  }

  return (
    <header className="navbar">
      {/* Top micro announcement bar */}
      <div className="navbar-announcement-bar">
        <div className="container announcement-inner">
          <div className="announcement-left">
            <span className="announcement-shield-dot" />
            <span>Free Express Delivery &amp; 30-Day Returns on all orders</span>
          </div>
          <div className="announcement-right">
            <span>Free Express Delivery on all orders</span>
            <span className="announcement-divider">&middot;</span>
            <Link to="/admin/login" className="announcement-admin-link">Admin Portal</Link>
          </div>
        </div>
      </div>

      <div className="container navbar-inner">
        {/* Brand Link */}
        <Link to="/" className="navbar-brand" onClick={() => setMobileMenuOpen(false)}>
          <div className="navbar-brand-icon" aria-hidden="true">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
              <path d="M9 12l2 2 4-4" />
            </svg>
          </div>
          <span className="navbar-brand-text">SecureCart</span>
        </Link>

        {/* Desktop Navigation Links */}
        <nav className="navbar-links" aria-label="Main Store Navigation">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active' : '')}>
            Home
          </NavLink>
          <NavLink to="/products" className={({ isActive }) => (isActive ? 'active' : '')}>
            Products
          </NavLink>
          {role === 'user' && (
            <>
              <NavLink to="/orders" className={({ isActive }) => (isActive ? 'active' : '')}>
                Orders
              </NavLink>
              <NavLink to="/dashboard" className={({ isActive }) => (isActive ? 'active' : '')}>
                Account
              </NavLink>
            </>
          )}
        </nav>

        {/* Quick Search Bar */}
        <form className="navbar-search-form" onSubmit={handleSearchSubmit}>
          <svg className="search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            id="nav-search-input"
            type="text"
            className="navbar-search-input"
            placeholder="Search catalog..."
            value={navSearch}
            onChange={(e) => setNavSearch(e.target.value)}
          />
        </form>

        {/* Actions Area: Cart + Auth Controls */}
        <div className="navbar-actions">
          {/* Cart Icon Button */}
          <Link to="/cart" className="navbar-cart-btn" aria-label={`Shopping cart with ${itemCount} items`}>
            <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" />
              <line x1="3" y1="6" x2="21" y2="6" />
              <path d="M16 10a4 4 0 0 1-8 0" />
            </svg>
            <span className="navbar-cart-label">Cart</span>
            {itemCount > 0 && <span className="navbar-cart-badge">{itemCount}</span>}
          </Link>

          {/* User Status / Login Buttons */}
          {isAuthenticated ? (
            <div className="navbar-user-group">
              <Link to="/dashboard" className="navbar-user-pill" title="View Account Dashboard">
                <span className="navbar-avatar">{user?.name ? user.name.charAt(0).toUpperCase() : 'U'}</span>
                <span className="navbar-user-name">{user?.name || 'Account'}</span>
              </Link>
              <button
                id="btn-nav-logout"
                className="btn btn-secondary btn-sm navbar-logout-btn"
                onClick={handleLogout}
                title="Log out"
              >
                Log out
              </button>
            </div>
          ) : (
            <div className="navbar-auth-buttons">
              <Link to="/login" className="btn btn-secondary btn-sm">
                Log In
              </Link>
              <Link to="/register" className="btn btn-brand btn-sm">
                Sign Up
              </Link>
            </div>
          )}

          {/* Mobile Menu Hamburger */}
          <button
            type="button"
            className="navbar-hamburger"
            onClick={() => setMobileMenuOpen((prev) => !prev)}
            aria-label={mobileMenuOpen ? 'Close navigation menu' : 'Open navigation menu'}
          >
            {mobileMenuOpen ? (
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            ) : (
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Mobile Drawer Menu */}
      {mobileMenuOpen && (
        <div className="navbar-mobile-drawer">
          <form className="navbar-mobile-search" onSubmit={handleSearchSubmit}>
            <input
              type="text"
              placeholder="Search products..."
              value={navSearch}
              onChange={(e) => setNavSearch(e.target.value)}
            />
            <button type="submit" className="btn btn-brand btn-sm">Search</button>
          </form>

          <nav className="mobile-nav-links">
            <Link to="/" onClick={() => setMobileMenuOpen(false)}>Home</Link>
            <Link to="/products" onClick={() => setMobileMenuOpen(false)}>Browse Products</Link>
            <Link to="/cart" onClick={() => setMobileMenuOpen(false)}>Shopping Cart ({itemCount})</Link>
            {role === 'user' && (
              <>
                <Link to="/orders" onClick={() => setMobileMenuOpen(false)}>My Orders</Link>
                <Link to="/dashboard" onClick={() => setMobileMenuOpen(false)}>Account Dashboard</Link>
              </>
            )}
            <Link to="/admin/login" onClick={() => setMobileMenuOpen(false)} className="mobile-admin-link">
              Admin Portal &rarr;
            </Link>
          </nav>

          <div className="mobile-auth-footer">
            {isAuthenticated ? (
              <button className="btn btn-secondary btn-block" onClick={handleLogout}>
                Log Out ({user?.name || user?.email})
              </button>
            ) : (
              <div className="mobile-auth-actions">
                <Link to="/login" className="btn btn-secondary btn-block" onClick={() => setMobileMenuOpen(false)}>
                  Log In
                </Link>
                <Link to="/register" className="btn btn-brand btn-block" onClick={() => setMobileMenuOpen(false)}>
                  Create Account
                </Link>
              </div>
            )}
          </div>
        </div>
      )}
    </header>
  );
}

export default Navbar;
