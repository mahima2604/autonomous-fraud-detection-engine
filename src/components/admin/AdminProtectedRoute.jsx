// AdminProtectedRoute.jsx
import { Navigate } from 'react-router-dom';

function AdminProtectedRoute({ children }) {
  const isAdminAuthenticated = localStorage.getItem('admin_authenticated') === 'true';
  
  if (!isAdminAuthenticated) {
    return <Navigate to="/admin/login" replace />;
  }
  
  return children;
}

export default AdminProtectedRoute;
