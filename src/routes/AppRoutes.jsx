// AppRoutes.jsx
// Single source of truth for all page routes in the app. Keeping routing
// logic separate from App.jsx keeps App.jsx clean and makes it easy to
// add/remove/reorganize pages as the project grows.

import { Routes, Route } from 'react-router-dom';

import MainLayout from '../layouts/MainLayout';
import AdminLayout from '../layouts/AdminLayout';
import ProtectedRoute from '../components/common/ProtectedRoute';

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
import FraudDashboard from '../pages/admin/FraudDashboard';
import AdminLogin from '../pages/admin/AdminLogin';
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

        {/* Checkout → fraud verification → payment → success require a
            logged-in user, since orders need to be tied to an account. */}
        <Route path="checkout" element={<ProtectedRoute><Checkout /></ProtectedRoute>} />
        <Route path="fraud-verification" element={<ProtectedRoute><FraudVerification /></ProtectedRoute>} />
        <Route path="payment" element={<ProtectedRoute><Payment /></ProtectedRoute>} />
        <Route path="order-success" element={<ProtectedRoute><OrderSuccess /></ProtectedRoute>} />
        <Route path="orders" element={<ProtectedRoute><Orders /></ProtectedRoute>} />
      </Route>

      {/* Separate shell for the internal fraud-monitoring dashboard. */}
      <Route path="/admin" element={<AdminLayout />}>
        <Route path="login" element={<AdminLogin />} />
        <Route path="fraud-dashboard" element={
          <AdminProtectedRoute>
            <FraudDashboard />
          </AdminProtectedRoute>
        } />
      </Route>
    </Routes>
  );
}

export default AppRoutes;
