import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

function Dashboard() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();

  function handleLogout() {
    logout();
    navigate('/login', { replace: true });
  }

  return (
    <div>
      <div className="section-heading">
        <div>
          <h1>Welcome, {user?.name || 'Shopper'}</h1>
          <p>{user?.email}</p>
        </div>
        <button className="btn btn-secondary btn-sm" onClick={handleLogout}>Log out</button>
      </div>

      <div className="product-grid">
        <Link to="/products" className="card card-padded dashboard-link-card">
          <h2>Browse products</h2>
          <p>Explore the SecureCart catalog.</p>
        </Link>
        <Link to="/cart" className="card card-padded dashboard-link-card">
          <h2>Your cart</h2>
          <p>Review items and continue to checkout.</p>
        </Link>
        <Link to="/orders" className="card card-padded dashboard-link-card">
          <h2>Order history</h2>
          <p>View the order history page.</p>
        </Link>
      </div>
    </div>
  );
}

export default Dashboard;
