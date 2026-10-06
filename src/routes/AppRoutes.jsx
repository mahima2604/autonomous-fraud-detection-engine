// AppRoutes.jsx
// Single source of truth for all page routes in the app. Keeping routing
// logic separate from App.jsx keeps App.jsx clean and makes it easy to
// add/remove/reorganize pages as the project grows.

import { Routes, Route, Navigate } from 'react-router-dom';

import MainLayout from '../layouts/MainLayout';
import AdminLayout from '../layouts/AdminLayout';
import UserProtectedRoute from '../components/common/ProtectedRoute';

import Home from '../pages/Home';
import Login from '../pages/Login';
import Register from '../pages/Register';
import Products from '../pages/Products';
import ProductDetails from '../pages/ProductDetails';
import Cart from '../pages/Cart';
import Checkout from '../pages/Checkout';
import FraudVerification from '../pages/FraudVerification';
import Payment from '../pages/Payment';
import OrderSuccess from '../pages/OrderSuccess';
import Orders from '../pages/Orders';
import UserDashboard from '../pages/Dashboard';
import FraudDashboard from '../pages/admin/FraudDashboard';
import AdminCustomers from '../pages/admin/AdminCustomers';
import AdminProtectedRoute from '../components/admin/AdminProtectedRoute';

function AppRoutes() {
  return (
    <Routes>
      {/* MainLayout wraps every customer-facing route below it. */}
      <Route path="/" element={<MainLayout />}>
        <Route index element={<Home />} />
        <Route path="login" element={<Login />} />
        <Route path="register" element={<Register />} />
        <Route path="products" element={<Products />} />
        <Route path="products/:id" element={<ProductDetails />} />
        <Route path="cart" element={<Cart />} />
        <Route path="dashboard" element={<UserProtectedRoute><UserDashboard /></UserProtectedRoute>} />

        {/* Checkout → fraud verification → payment → success require a
            logged-in user, since orders need to be tied to an account. */}
        <Route path="checkout" element={<UserProtectedRoute><Checkout /></UserProtectedRoute>} />
        <Route path="fraud-verification" element={<UserProtectedRoute><FraudVerification /></UserProtectedRoute>} />
        <Route path="payment" element={<UserProtectedRoute><Payment /></UserProtectedRoute>} />
        <Route path="order-success" element={<UserProtectedRoute><OrderSuccess /></UserProtectedRoute>} />
        <Route path="orders" element={<UserProtectedRoute><Orders /></UserProtectedRoute>} />
      </Route>

      {/* Separate shell for the internal fraud-monitoring dashboard. */}
      <Route path="/admin" element={<AdminLayout />}>
        <Route index element={<Navigate to="/admin/dashboard" replace />} />
        <Route path="login" element={<Navigate to="/login?role=admin" replace />} />
        <Route path="fraud-dashboard" element={<Navigate to="/admin/dashboard" replace />} />
        <Route path="dashboard" element={
          <AdminProtectedRoute>
            <FraudDashboard />
          </AdminProtectedRoute>
        } />
        <Route path="customers" element={
          <AdminProtectedRoute>
            <AdminCustomers />
          </AdminProtectedRoute>
        } />
      </Route>
    </Routes>
  );
}

export default AppRoutes;
