// CartItemRow.jsx — A single line item row in the shopping cart table.
import { Link } from 'react-router-dom';
import { formatCurrency } from '../../utils/formatters';
import { useCart } from '../../context/CartContext';
import './CartItemRow.css';

function CartItemRow({ item }) {
  const { increaseQuantity, decreaseQuantity, removeItem } = useCart();

  return (
    <div className="cart-item-row">
      <Link to={`/products/${item.id}`} className="cart-item-image-wrap">
        <img src={item.image} alt={item.name} className="cart-item-image" />
      </Link>

      <div className="cart-item-info">
        <Link to={`/products/${item.id}`} className="cart-item-name">
          {item.name}
        </Link>
        <span className="cart-item-price">{formatCurrency(item.price)} each</span>
      </div>

      <div className="cart-item-qty">
        <div className="cart-qty-stepper">
          <button
            type="button"
            className="cart-qty-btn"
            onClick={() => decreaseQuantity(item.id)}
            aria-label={`Decrease quantity of ${item.name}`}
          >
            &minus;
          </button>
          <span className="cart-qty-val font-tabular">{item.quantity}</span>
          <button
            type="button"
            className="cart-qty-btn"
            onClick={() => increaseQuantity(item.id)}
            aria-label={`Increase quantity of ${item.name}`}
          >
            +
          </button>
        </div>
      </div>

      <div className="cart-item-total font-tabular">
        {formatCurrency(item.price * item.quantity)}
      </div>

      <button
        id={`btn-remove-cart-${item.id}`}
        type="button"
        className="btn-remove-item"
        onClick={() => removeItem(item.id)}
        title="Remove item from cart"
        aria-label={`Remove ${item.name} from cart`}
      >
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <polyline points="3 6 5 6 21 6" />
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
        </svg>
      </button>
    </div>
  );
}

export default CartItemRow;
