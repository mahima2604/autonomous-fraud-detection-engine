// Products.jsx — product listing with category filter + loading/empty/error states.
import { useEffect, useMemo, useState } from 'react';
import ProductCard from '../components/product/ProductCard';
import LoadingSpinner from '../components/common/LoadingSpinner';
import EmptyState from '../components/common/EmptyState';
import { getProducts } from '../services/productService';

function Products() {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [category, setCategory] = useState('All');

  useEffect(() => {
    let active = true;
    setLoading(true);
    getProducts()
      .then((data) => active && setProducts(data))
      .catch((err) => active && setError(err.message || 'Failed to load products.'))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  const categories = useMemo(() => ['All', ...new Set(products.map((p) => p.category))], [products]);
  const filtered = category === 'All' ? products : products.filter((p) => p.category === category);

  return (
    <div>
      <div className="section-heading">
        <h1>Products</h1>
      </div>

      {!loading && !error && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 20 }}>
          {categories.map((c) => (
            <button
              key={c}
              className={`btn btn-sm ${category === c ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => setCategory(c)}
            >
              {c}
            </button>
          ))}
        </div>
      )}

      {loading && <LoadingSpinner label="Loading products…" />}

      {!loading && error && (
        <EmptyState title="Something went wrong" message={error} />
      )}

      {!loading && !error && filtered.length === 0 && (
        <EmptyState title="No products found" message="Try a different category." />
      )}

      {!loading && !error && filtered.length > 0 && (
        <div className="product-grid">
          {filtered.map((product) => (
            <ProductCard key={product.id} product={product} />
          ))}
        </div>
      )}
    </div>
  );
}

export default Products;
