// Checkout.jsx
// Collects shipping/billing info and payment method choice, then hands
// off to Fraud Verification before any payment is attempted.
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCart } from '../context/CartContext';
import { useAuth } from '../context/AuthContext';
import AddressForm from '../components/checkout/AddressForm';
import OrderSummary from '../components/checkout/OrderSummary';
import { buildTransactionPayload, savePendingCheckout } from '../services/checkoutService';
import EmptyState from '../components/common/EmptyState';

const EMPTY_ADDRESS = { fullName: '', line1: '', city: '', postalCode: '', country: '' };

function Checkout() {
  const { items, subtotal } = useCart();
  const { user } = useAuth();
  const navigate = useNavigate();

  const [shipping, setShipping] = useState(EMPTY_ADDRESS);
  const [billing, setBilling] = useState(EMPTY_ADDRESS);
  const [sameAsShipping, setSameAsShipping] = useState(true);
  const [paymentMethod, setPaymentMethod] = useState('CARD');
  const [error, setError] = useState('');

  if (items.length === 0) {
    return <EmptyState title="Your cart is empty" message="Add products before checking out." />;
  }

  function validate() {
    const requiredFilled = (addr) => Object.values(addr).every((v) => v.trim().length > 0);
    if (!requiredFilled(shipping)) return 'Please complete the shipping address.';
    if (!sameAsShipping && !requiredFilled(billing)) return 'Please complete the billing address.';
    return '';
  }

  function handleSubmit(e) {
    e.preventDefault();
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setError('');

    const billingAddress = sameAsShipping ? shipping : billing;
    const payload = buildTransactionPayload({
      user,
      cartItems: items,
      amount: subtotal,
      paymentMethod,
      billingAddress,
      shippingAddress: shipping,
    });

    savePendingCheckout({ transaction: payload, items, subtotal, paymentMethod });
    navigate('/fraud-verification');
  }

  return (
    <div>
      <h1>Checkout</h1>
      <div className="checkout-layout">
        <form className="checkout-form" onSubmit={handleSubmit} noValidate>
          {error && <div className="form-error-banner">{error}</div>}

          <div className="card card-padded" style={{ marginBottom: 20 }}>
            <h3>Shipping address</h3>
            <AddressForm values={shipping} onChange={setShipping} prefix="ship" />
          </div>

          <div className="card card-padded" style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <h3>Billing address</h3>
              <label style={{ fontSize: 13.5, display: 'flex', alignItems: 'center', gap: 6, fontWeight: 500 }}>
                <input
                  type="checkbox"
                  checked={sameAsShipping}
                  onChange={(e) => setSameAsShipping(e.target.checked)}
                />
                Same as shipping
              </label>
            </div>
            {!sameAsShipping && <AddressForm values={billing} onChange={setBilling} prefix="bill" />}
          </div>

          <div className="card card-padded" style={{ marginBottom: 20 }}>
            <h3>Payment method</h3>
            <div className="payment-method-options">
              {['CARD', 'PAYPAL', 'BANK_TRANSFER'].map((method) => (
                <label key={method} className="payment-method-option">
                  <input
                    type="radio"
                    name="paymentMethod"
                    value={method}
                    checked={paymentMethod === method}
                    onChange={() => setPaymentMethod(method)}
                  />
                  {method === 'CARD' ? 'Credit / Debit Card' : method === 'PAYPAL' ? 'PayPal' : 'Bank Transfer'}
                </label>
              ))}
            </div>
            <p className="mock-note">
              Card details are collected on the payment step only, and are never stored by this app.
            </p>
          </div>

          <button className="btn btn-primary btn-block" type="submit">
            Continue to Fraud Verification
          </button>
        </form>

        <OrderSummary items={items} subtotal={subtotal} />
      </div>
    </div>
  );
}

export default Checkout;
