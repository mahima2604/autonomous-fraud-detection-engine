// Cart.jsx
import { Link, useNavigate } from 'react-router-dom';
import { useCart } from '../context/CartContext';
import { useAuth } from '../context/AuthContext';
import CartItemRow from '../components/cart/CartItemRow';
import EmptyState from '../components/common/EmptyState';
import { formatCurrency } from '../utils/formatters';

function Cart() {
  const { items, subtotal, clearCart } = useCart();
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();

  if (items.length === 0) {
    return (
      <EmptyState
        title="Your cart is empty"
        message="Browse our products and add something you like."
        action={<Link to="/products" className="btn btn-primary btn-sm">Browse products</Link>}
      />
    );
  }

  function handleCheckout() {
    if (!isAuthenticated) {
      navigate('/login', { state: { from: { pathname: '/checkout' } } });
      return;
    }
    navigate('/checkout');
  }

  return (
    <div>
      <div className="section-heading">
        <h1>Your Cart</h1>
        <button className="btn-link" onClick={clearCart}>Clear cart</button>
      </div>

      <div className="cart-layout">
        <div className="card card-padded">
          {items.map((item) => (
            <CartItemRow key={item.id} item={item} />
          ))}
        </div>

        <div className="card card-padded">
          <h3>Summary</h3>
          <div className="order-summary-row">
            <span>Subtotal</span>
            <span>{formatCurrency(subtotal)}</span>
          </div>
          <div className="order-summary-row">
            <span>Shipping</span>
            <span>Free</span>
          </div>
          <div className="order-summary-row order-summary-total">
            <span>Total</span>
            <span>{formatCurrency(subtotal)}</span>
          </div>
          <button className="btn btn-primary btn-block" style={{ marginTop: 12 }} onClick={handleCheckout}>
            Proceed to Checkout
          </button>
          <Link to="/products" className="btn btn-secondary btn-block" style={{ marginTop: 8 }}>
            Continue shopping
          </Link>
        </div>
      </div>
    </div>
  );
}

export default Cart;
