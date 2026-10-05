// AdminProtectedRoute.jsx
import { Navigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import LoadingSpinner from '../common/LoadingSpinner';

function AdminProtectedRoute({ children }) {
  const { role, loading } = useAuth();

  if (loading) return <LoadingSpinner label="Checking your session…" />;
  if (role === 'user') return <Navigate to="/dashboard" replace />;
  if (role !== 'admin') return <Navigate to="/login?role=admin" replace />;

  return children;
}

export default AdminProtectedRoute;
