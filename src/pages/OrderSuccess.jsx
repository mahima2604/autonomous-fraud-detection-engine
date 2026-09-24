// OrderSuccess.jsx
import { Link } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { formatCurrency, formatDate } from '../utils/formatters';
import EmptyState from '../components/common/EmptyState';

function OrderSuccess() {
  const [order, setOrder] = useState(null);

  useEffect(() => {
    try {
      setOrder(JSON.parse(sessionStorage.getItem('last_order')));
    } catch {
      setOrder(null);
    }
  }, []);

  if (!order) {
    return (
      <EmptyState
        title="No recent order"
        message="We couldn't find a recent order to show."
        action={<Link to="/products" className="btn btn-primary btn-sm">Continue shopping</Link>}
      />
    );
  }

  return (
    <div className="auth-page">
      <div className="card card-padded auth-card" style={{ textAlign: 'center', maxWidth: 480 }}>
        <div style={{ fontSize: 40, marginBottom: 8 }}>✓</div>
        <h2>Order placed successfully</h2>
        <p>Thank you — your order is confirmed.</p>

        <div style={{ textAlign: 'left', marginTop: 20 }}>
          <div className="order-summary-row"><span>Order ID</span><span>{order.id}</span></div>
          <div className="order-summary-row"><span>Date</span><span>{formatDate(order.date)}</span></div>
          <div className="order-summary-row"><span>Items</span><span>{order.items?.join(', ')}</span></div>
          <div className="order-summary-row order-summary-total"><span>Total</span><span>{formatCurrency(order.amount)}</span></div>
        </div>

        <div style={{ display: 'flex', gap: 12, marginTop: 20 }}>
          <Link to="/products" className="btn btn-secondary btn-block">Continue shopping</Link>
          <Link to="/orders" className="btn btn-primary btn-block">View orders</Link>
        </div>
      </div>
    </div>
  );
}

export default OrderSuccess;
