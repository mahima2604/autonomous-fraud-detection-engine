// Payment.jsx
// Frontend-only payment simulation. No real payment gateway is
// integrated and no card numbers are collected or stored.
import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { getPendingCheckout, clearPendingCheckout } from '../services/checkoutService';
import { processPayment } from '../services/paymentService';
import { createOrder } from '../services/orderService';
import { useCart } from '../context/CartContext';
import OrderSummary from '../components/checkout/OrderSummary';
import EmptyState from '../components/common/EmptyState';
import { formatCurrency } from '../utils/formatters';

function Payment() {
  const navigate = useNavigate();
  const { clearCart } = useCart();
  const pending = getPendingCheckout();

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

  if (pending.fraudResult.decision === 'BLOCK') {
    return (
      <EmptyState
        title="Payment unavailable"
        message="This transaction was blocked during verification and cannot be paid for."
        action={<Link to="/cart" className="btn btn-primary btn-sm">Return to cart</Link>}
      />
    );
  }

  async function handlePay() {
    setProcessing(true);
    setError('');
    try {
      const payment = await processPayment({
        transactionId: pending.fraudResult.transactionId,
        amount: pending.subtotal,
        paymentMethod: pending.paymentMethod,
      });

      const order = await createOrder({
        items: pending.items.map((i) => i.name),
        amount: pending.subtotal,
        paymentId: payment.paymentId,
        transactionId: pending.fraudResult.transactionId,
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
          <h3>Secure checkout</h3>
          <p>
            This is a simulated payment for demonstration purposes. No real charge is made and
            no card numbers are collected or stored by this application.
          </p>
          <p style={{ fontWeight: 600, color: 'var(--color-text)' }}>
            Payment method: {pending.paymentMethod === 'CARD' ? 'Credit / Debit Card' : pending.paymentMethod === 'PAYPAL' ? 'PayPal' : 'Bank Transfer'}
          </p>
          {error && <div className="form-error-banner">{error}</div>}
          <button className="btn btn-primary btn-block" onClick={handlePay} disabled={processing}>
            {processing ? 'Processing payment…' : `Pay ${formatCurrency(pending.subtotal)}`}
          </button>
        </div>
      </div>

      <OrderSummary items={pending.items} subtotal={pending.subtotal} title="Order Summary" />
    </div>
  );
}

export default Payment;
