// ProductCard.jsx — used on the Products listing page.
import { Link } from 'react-router-dom';
import { formatCurrency } from '../../utils/formatters';
import { useCart } from '../../context/CartContext';
import './ProductCard.css';

function ProductCard({ product }) {
  const { addItem } = useCart();

  return (
    <div className="product-card card">
      <Link to={`/products/${product.id}`} className="product-card-image-link">
        <img src={product.image} alt={product.name} loading="lazy" />
      </Link>
      <div className="product-card-body">
        <span className="product-card-category">{product.category}</span>
        <Link to={`/products/${product.id}`} className="product-card-name">
          {product.name}
        </Link>
        <div className="product-card-footer">
          <span className="product-card-price">{formatCurrency(product.price)}</span>
          <div className="product-card-actions">
            <Link to={`/products/${product.id}`} className="btn btn-secondary btn-sm">
              View
            </Link>
            <button className="btn btn-primary btn-sm" onClick={() => addItem(product, 1)}>
              Add to Cart
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ProductCard;
