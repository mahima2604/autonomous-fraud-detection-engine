// CartItemRow.jsx — a single line item on the Cart page.
import { formatCurrency } from '../../utils/formatters';
import { useCart } from '../../context/CartContext';

function CartItemRow({ item }) {
  const { increaseQuantity, decreaseQuantity, removeItem } = useCart();

  return (
    <div className="cart-item-row">
      <img src={item.image} alt={item.name} className="cart-item-image" />
      <div className="cart-item-info">
        <span className="cart-item-name">{item.name}</span>
        <span className="cart-item-price">{formatCurrency(item.price)} each</span>
      </div>
      <div className="cart-item-qty">
        <button className="btn btn-secondary btn-sm" onClick={() => decreaseQuantity(item.id)} aria-label="Decrease quantity">
          −
        </button>
        <span>{item.quantity}</span>
        <button className="btn btn-secondary btn-sm" onClick={() => increaseQuantity(item.id)} aria-label="Increase quantity">
          +
        </button>
      </div>
      <div className="cart-item-total">{formatCurrency(item.price * item.quantity)}</div>
      <button className="btn-link cart-item-remove" onClick={() => removeItem(item.id)}>
        Remove
      </button>
    </div>
  );
}

export default CartItemRow;
