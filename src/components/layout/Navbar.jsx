// Navbar.jsx — primary site navigation, shared by every page via MainLayout.
import { Link, NavLink, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { useCart } from '../../context/CartContext';
import './Navbar.css';

function Navbar() {
  const { user, role, isAuthenticated, logout } = useAuth();
  const { itemCount } = useCart();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate('/login');
  }

  return (
    <header className="navbar">
      <div className="container navbar-inner">
        <Link to="/" className="navbar-brand">
          <span className="navbar-brand-mark">SecureCart</span>
        </Link>

        <nav className="navbar-links">
          {role === 'user' && (
            <NavLink to="/dashboard" className={({ isActive }) => (isActive ? 'active' : '')}>
              Dashboard
            </NavLink>
          )}
          <NavLink to="/products" className={({ isActive }) => (isActive ? 'active' : '')}>
            Products
          </NavLink>
          {role === 'user' && (
            <NavLink to="/orders" className={({ isActive }) => (isActive ? 'active' : '')}>
              Orders
            </NavLink>
          )}
        </nav>

        <div className="navbar-actions">
          <Link to="/cart" className="navbar-cart" aria-label={`Cart, ${itemCount} items`}>
            Cart
            {itemCount > 0 && <span className="navbar-cart-badge">{itemCount}</span>}
          </Link>

          {isAuthenticated ? (
            <div className="navbar-user">
              <span className="navbar-user-name">{user.name}</span>
              <button className="btn btn-secondary btn-sm" onClick={handleLogout}>
                Log out
              </button>
            </div>
          ) : (
            <div className="navbar-auth">
              <Link to="/login" className="btn btn-secondary btn-sm">Log in</Link>
              <Link to="/register" className="btn btn-primary btn-sm">Sign up</Link>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}

export default Navbar;
