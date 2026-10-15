// Payment.jsx
// Frontend-only payment simulation. No real payment gateway is
// integrated and no card numbers are collected or stored.
import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { getPendingCheckout, clearPendingCheckout } from '../services/checkoutService';
import { createOrder } from '../services/orderService';
import { useCart } from '../context/CartContext';
import OrderSummary from '../components/checkout/OrderSummary';
import EmptyState from '../components/common/EmptyState';
import { formatCurrency } from '../utils/formatters';
import { useAuth } from '../context/AuthContext';

function Payment() {
  const navigate = useNavigate();
  const { clearCart } = useCart();
  const { user } = useAuth();
  const pending = getPendingCheckout(user?.id);

  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState('');

  if (!pending || !pending.fraudResult) {
    return (
      <EmptyState
        title="Nothing to pay for"
        message="Please start checkout again."
        action={<Link to="/cart" className="btn btn-primary btn-sm">Go to cart</Link>}
      />
    );
  }

  if (pending.fraudResult.decision !== 'APPROVE') {
    return (
      <EmptyState
        title="Payment unavailable"
        message={pending.fraudResult.decision === 'REVIEW'
          ? 'This transaction is awaiting administrator review and cannot be paid until approved.'
          : pending.fraudResult.decision === 'REJECT'
            ? 'This transaction was rejected after administrator review and cannot be paid for.'
            : 'This transaction was blocked during verification and cannot be paid for.'}
        action={<Link to="/cart" className="btn btn-primary btn-sm">Return to cart</Link>}
      />
    );
  }

  async function handlePay() {
    setProcessing(true);
    setError('');
    try {
      const order = await createOrder({
        transactionId: pending.fraudResult.transactionId,
        items: pending.items.map((item) => ({ productId: item.id, quantity: item.quantity })),
        paymentMethod: pending.paymentMethod,
        shippingAddress: pending.shippingAddress,
        billingAddress: pending.billingAddress,
      });

      sessionStorage.setItem('last_order', JSON.stringify(order));
      clearPendingCheckout();
      clearCart();
      navigate('/order-success');
    } catch (err) {
      setError(err.message || 'Payment failed. Please try again.');
    } finally {
      setProcessing(false);
    }
  }

  return (
    <div className="fraud-verification-layout">
      <div>
        <h1>Payment</h1>
        <div className="card card-padded" style={{ marginBottom: 20 }}>
          <h3>Payment simulation</h3>
          <p>
            This records a simulated payment only. No payment provider is connected and no real charge is made.
          </p>
          <p style={{ fontWeight: 600, color: 'var(--color-text)' }}>
            Payment method: {pending.paymentMethod === 'CARD' ? 'Credit / Debit Card' : pending.paymentMethod === 'PAYPAL' ? 'PayPal' : 'Bank Transfer'}
          </p>
          {error && <div className="form-error-banner">{error}</div>}
          <button className="btn btn-primary btn-block" onClick={handlePay} disabled={processing}>
            {processing ? 'Recording order...' : `Confirm simulated payment: ${formatCurrency(pending.subtotal)}`}
          </button>
        </div>
      </div>

      <OrderSummary items={pending.items} subtotal={pending.subtotal} title="Order Summary" />
    </div>
  );
}

export default Payment;
