// ProductDetails.jsx
import { useEffect, useState } from 'react';
import { useParams, Link } from 'react-router-dom';
import LoadingSpinner from '../components/common/LoadingSpinner';
import EmptyState from '../components/common/EmptyState';
import { getProductById } from '../services/productService';
import { useCart } from '../context/CartContext';
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

  if (loading) return <LoadingSpinner label="Loading product…" />;
  if (error || !product) {
    return (
      <EmptyState
        title="Product not found"
        message={error || "We couldn't find that product."}
        action={<Link to="/products" className="btn btn-primary btn-sm">Back to products</Link>}
      />
    );
  }

  function handleAddToCart() {
    addItem(product, quantity);
    setAdded(true);
  }

  return (
    <div className="product-details">
      <div className="product-details-image">
        <img src={product.image} alt={product.name} />
      </div>
      <div className="product-details-info">
        <span className="product-card-category">{product.category}</span>
        <h1>{product.name}</h1>
        <p className="product-details-price">{formatCurrency(product.price)}</p>
        <p>{product.description}</p>
        <p style={{ fontSize: 13, color: 'var(--color-text-faint)' }}>
          {product.stock > 0 ? `${product.stock} in stock` : 'Out of stock'}
        </p>

        <div className="product-details-actions">
          <div className="qty-input">
            <button className="btn btn-secondary btn-sm" onClick={() => setQuantity((q) => Math.max(1, q - 1))}>−</button>
            <span>{quantity}</span>
            <button className="btn btn-secondary btn-sm" onClick={() => setQuantity((q) => q + 1)}>+</button>
          </div>
          <button className="btn btn-primary" onClick={handleAddToCart} disabled={product.stock === 0}>
            Add to Cart
          </button>
        </div>

        {added && <p className="form-success-note">Added to cart. <Link to="/cart">View cart →</Link></p>}
      </div>
    </div>
  );
}

export default ProductDetails;
