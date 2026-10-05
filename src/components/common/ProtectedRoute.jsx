// ProtectedRoute.jsx
// Guards routes that require an authenticated user (order history,
// checkout flow). Redirects to /login, preserving the intended
// destination so we can send the user back after they sign in.

import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import LoadingSpinner from './LoadingSpinner';

function UserProtectedRoute({ children }) {
  const { role, loading } = useAuth();
  const location = useLocation();

  if (loading) return <LoadingSpinner label="Checking your session…" />;

  if (role === 'admin') {
    return <Navigate to="/admin/dashboard" replace />;
  }

  if (role !== 'user') {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children;
}

export default UserProtectedRoute;
