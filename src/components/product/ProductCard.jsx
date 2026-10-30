// ProductCard.jsx — Reusable, high-conversion product card for catalog & home page.
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { formatCurrency } from '../../utils/formatters';
import { useCart } from '../../context/cart';
import './ProductCard.css';

function ProductCard({ product }) {
  const { addItem } = useCart();
  const [justAdded, setJustAdded] = useState(false);

  function handleAddToCart(e) {
    e.preventDefault();
    e.stopPropagation();
    addItem(product, 1);
    setJustAdded(true);
    setTimeout(() => setJustAdded(false), 1400);
  }

  return (
    <div className="product-card card">
      <Link to={`/products/${product.id}`} className="product-card-image-link" aria-label={`View details for ${product.name}`}>
        <img src={product.image} alt={product.name} loading="lazy" />
        <span className="product-badge-overlay">{product.category}</span>
      </Link>

      <div className="product-card-body">
        <Link to={`/products/${product.id}`} className="product-card-name" title={product.name}>
          {product.name}
        </Link>
        <p className="product-card-desc">{product.description}</p>

        <div className="product-card-footer">
          <div className="product-price-stack">
            <span className="product-price-label">Price</span>
            <span className="product-card-price">{formatCurrency(product.price)}</span>
          </div>

          <div className="product-card-actions">
            <Link to={`/products/${product.id}`} className="btn-card-view" title="View details">
              View
            </Link>
            <button
              id={`btn-add-to-cart-${product.id}`}
              type="button"
              className={`btn-card-add ${justAdded ? 'added' : ''}`}
              onClick={handleAddToCart}
              disabled={product.stock === 0}
              title={product.stock === 0 ? 'Out of Stock' : 'Add to Shopping Cart'}
            >
              {justAdded ? (
                <>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
                    <polyline points="20 6 9 17 4 12" />
                  </svg>
                  <span>Added!</span>
                </>
              ) : (
                <>
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                    <line x1="12" y1="5" x2="12" y2="19" />
                    <line x1="5" y1="12" x2="19" y2="12" />
                  </svg>
                  <span>Add</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ProductCard;
