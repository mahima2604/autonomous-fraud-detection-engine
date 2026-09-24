// OrderSummary.jsx — reusable order recap shown on Checkout, Fraud
// Verification, and Payment pages so the user always sees what they're
// buying and for how much.
import { formatCurrency } from '../../utils/formatters';

function OrderSummary({ items, subtotal, shipping = 0, title = 'Order Summary' }) {
  const total = subtotal + shipping;

  return (
    <div className="card card-padded order-summary">
      <h3>{title}</h3>
      <div className="order-summary-items">
        {items.map((item) => (
          <div key={item.id} className="order-summary-row">
            <span>
              {item.name} <span style={{ color: 'var(--color-text-faint)' }}>× {item.quantity}</span>
            </span>
            <span>{formatCurrency(item.price * item.quantity)}</span>
          </div>
        ))}
      </div>
      <div className="order-summary-row">
        <span>Subtotal</span>
        <span>{formatCurrency(subtotal)}</span>
      </div>
      <div className="order-summary-row">
        <span>Shipping</span>
        <span>{shipping === 0 ? 'Free' : formatCurrency(shipping)}</span>
      </div>
      <div className="order-summary-row order-summary-total">
        <span>Total</span>
        <span>{formatCurrency(total)}</span>
      </div>
    </div>
  );
}

export default OrderSummary;
