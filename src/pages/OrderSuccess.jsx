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
        <h2>Order recorded successfully</h2>
        <p>{order.paymentMethod === 'COD'
          ? 'Your order was recorded with cash due on delivery. No payment was taken or marked as paid.'
          : 'Your order and simulated payment were recorded. No real charge was made.'}</p>

        <div style={{ textAlign: 'left', marginTop: 20 }}>
          <div className="order-summary-row"><span>Order ID</span><span>{order.id}</span></div>
          <div className="order-summary-row"><span>Date</span><span>{formatDate(order.date)}</span></div>
          <div className="order-summary-row"><span>Items</span><span>{order.items?.join(', ')}</span></div>
          <div className="order-summary-row"><span>Payment method</span><span>{order.paymentMethod === 'COD' ? 'Cash on Delivery (COD)' : order.paymentMethod === 'CARD' ? 'Credit / Debit Card' : order.paymentMethod === 'PAYPAL' ? 'PayPal' : order.paymentMethod === 'BANK_TRANSFER' ? 'Bank Transfer' : order.paymentMethod}</span></div>
          <div className="order-summary-row"><span>Payment status</span><span>{order.paymentStatus === 'PENDING_CASH_COLLECTION' ? 'Cash due on delivery' : order.paymentStatus}</span></div>
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
