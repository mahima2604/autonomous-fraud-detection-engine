// ProductDetails.jsx — Balanced, responsive product detail view with breadcrumbs and cart actions.
import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import LoadingSpinner from '../components/common/LoadingSpinner';
import EmptyState from '../components/common/EmptyState';
import { getProductById } from '../services/productService';
import { useCart } from '../context/cart';
import { formatCurrency } from '../utils/formatters';
import './ProductDetails.css';

function ProductDetails() {
  const { id } = useParams();
  const { addItem } = useCart();

  const [product, setProduct] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [quantity, setQuantity] = useState(1);
  const [added, setAdded] = useState(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setAdded(false);
    getProductById(id)
      .then((data) => active && setProduct(data))
      .catch((err) => active && setError(err.message || 'Product not found.'))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, [id]);

  if (loading) return <LoadingSpinner label="Loading product details..." />;
  if (error || !product) {
    return (
      <EmptyState
        title="Product not found"
        message={error || "We couldn't locate this product in our catalogue."}
        action={<Link to="/products" className="btn btn-primary btn-sm">Return to Products</Link>}
      />
    );
  }

  function handleAddToCart() {
    addItem(product, quantity);
    setAdded(true);
  }

  return (
    <div className="product-details-container">
      {/* Breadcrumb Navigation */}
      <nav className="details-breadcrumb" aria-label="Breadcrumb">
        <Link to="/">Home</Link>
        <span className="crumb-separator">/</span>
        <Link to="/products">Products</Link>
        <span className="crumb-separator">/</span>
        <Link to={`/products?category=${encodeURIComponent(product.category)}`}>{product.category}</Link>
        <span className="crumb-separator">/</span>
        <span className="crumb-current">{product.name}</span>
      </nav>

      {/* Main 2-Column Product Detail Layout */}
      <div className="product-details-card card">
        {/* Left: Product Image Showcase */}
        <div className="product-details-media">
          <img src={product.image} alt={product.name} className="product-main-image" />
          <div className="media-badge-strip">
            <span className="media-category-pill">{product.category}</span>
            <span className="media-verified-pill">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <polyline points="20 6 9 17 4 12" />
              </svg>
              Genuine Catalog Item
            </span>
          </div>
        </div>

        {/* Right: Product Info & Actions */}
        <div className="product-details-content">
          <div className="product-header-group">
            <span className="product-category-kicker">{product.category}</span>
            <h1 className="product-title">{product.name}</h1>
            <div className="product-price-row">
              <span className="product-price-large">{formatCurrency(product.price)}</span>
              <span className="product-shipping-badge">Free Tracked Delivery</span>
            </div>
          </div>

          <div className="product-description-block">
            <h3>Overview</h3>
            <p>{product.description}</p>
          </div>

          <div className="product-stock-indicator">
            <span className={`stock-dot ${product.stock > 0 ? 'in-stock' : 'out-of-stock'}`} />
            <span>
              {product.stock > 0 ? `${product.stock} units available in stock` : 'Currently out of stock'}
            </span>
          </div>

          {/* Quantity Selector & Add to Cart */}
          <div className="product-purchase-box">
            <div className="qty-selector-wrap">
              <label htmlFor="product-qty" className="qty-label">Quantity</label>
              <div className="qty-control">
                <button
                  type="button"
                  className="btn-qty-step"
                  onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                  disabled={quantity <= 1 || product.stock === 0}
                  aria-label="Decrease quantity"
                >
                  &minus;
                </button>
                <span id="product-qty" className="qty-number font-tabular">{quantity}</span>
                <button
                  type="button"
                  className="btn-qty-step"
                  onClick={() => setQuantity((q) => Math.min(product.stock || 99, q + 1))}
                  disabled={product.stock === 0 || quantity >= product.stock}
                  aria-label="Increase quantity"
                >
                  +
                </button>
              </div>
            </div>

            <button
              id="btn-product-add-cart"
              type="button"
              className="btn btn-primary btn-add-cart-large"
              onClick={handleAddToCart}
              disabled={product.stock === 0}
            >
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M6 2L3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4z" />
                <line x1="3" y1="6" x2="21" y2="6" />
                <path d="M16 10a4 4 0 0 1-8 0" />
              </svg>
              <span>Add to Cart &middot; {formatCurrency(product.price * quantity)}</span>
            </button>
          </div>

          {/* Feedback & View Cart Link */}
          {added && (
            <div className="product-added-alert" role="status">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
              <span>Added to your cart.</span>
              <Link to="/cart" className="alert-cart-link">View Cart &amp; Checkout &rarr;</Link>
            </div>
          )}

          {/* Security Assurance Feature Callout */}
          <div className="details-security-callout">
            <div className="callout-shield-icon" aria-hidden="true">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="M9 12l2 2 4-4" />
              </svg>
            </div>
            <div>
              <strong>SecureCart Fraud Protection Guarantee</strong>
              <p>Every checkout is scored by our baseline ML model to ensure genuine buyers enjoy instant auto-approval.</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default ProductDetails;
