// Products.jsx — Enhanced product catalogue with category filters, search, and responsive grid.
import { useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import ProductCard from '../components/product/ProductCard';
import LoadingSpinner from '../components/common/LoadingSpinner';
import EmptyState from '../components/common/EmptyState';
import { getProducts } from '../services/productService';
import './Products.css';

function Products() {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [searchParams, setSearchParams] = useSearchParams();

  // Sync category and search query from URL or state
  const activeCategory = searchParams.get('category') || 'All';
  const activeSearch = searchParams.get('search') || '';
  const [searchTerm, setSearchTerm] = useState(activeSearch);

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

  useEffect(() => {
    setSearchTerm(activeSearch);
  }, [activeSearch]);

  const categories = useMemo(() => {
    const unique = ['All', ...new Set(products.map((p) => p.category))];
    return unique;
  }, [products]);

  function handleCategorySelect(cat) {
    const next = new URLSearchParams(searchParams);
    if (cat === 'All') {
      next.delete('category');
    } else {
      next.set('category', cat);
    }
    setSearchParams(next);
  }

  function handleSearchSubmit(e) {
    e.preventDefault();
    const next = new URLSearchParams(searchParams);
    if (searchTerm.trim()) {
      next.set('search', searchTerm.trim());
    } else {
      next.delete('search');
    }
    setSearchParams(next);
  }

  function handleClearFilters() {
    setSearchTerm('');
    setSearchParams({});
  }

  const filtered = useMemo(() => {
    const q = activeSearch.trim().toLowerCase();
    return products.filter((p) => {
      const matchesCategory = activeCategory === 'All' || p.category === activeCategory;
      const matchesQuery =
        !q ||
        p.name.toLowerCase().includes(q) ||
        p.category.toLowerCase().includes(q) ||
        (p.description && p.description.toLowerCase().includes(q));
      return matchesCategory && matchesQuery;
    });
  }, [products, activeCategory, activeSearch]);

  return (
    <div className="products-page">
      {/* Page Header */}
      <div className="products-header">
        <div className="products-header-text">
          <span className="products-kicker">Store Catalogue</span>
          <h1 className="products-title">All Products &amp; Gear</h1>
          <p className="products-subtitle">
            Browse our curated collection of premium tech, everyday carry, and lifestyle essentials.
          </p>
        </div>

        {/* Search Toolbar */}
        <form className="products-search-bar" onSubmit={handleSearchSubmit}>
          <svg className="search-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
          <input
            id="products-search-input"
            type="text"
            placeholder="Search by title, category, or features..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
          {searchTerm && (
            <button
              type="button"
              className="btn-clear-search"
              onClick={() => {
                setSearchTerm('');
                const next = new URLSearchParams(searchParams);
                next.delete('search');
                setSearchParams(next);
              }}
              aria-label="Clear search"
            >
              &times;
            </button>
          )}
          <button type="submit" className="btn btn-primary btn-sm search-submit-btn">
            Search
          </button>
        </form>
      </div>

      {/* Category Pills & Count Bar */}
      {!loading && !error && (
        <div className="products-filter-bar">
          <div className="category-pills-list" role="tablist" aria-label="Product Categories">
            {categories.map((c) => (
              <button
                key={c}
                type="button"
                role="tab"
                aria-selected={activeCategory === c}
                className={`category-pill ${activeCategory === c ? 'active' : ''}`}
                onClick={() => handleCategorySelect(c)}
              >
                {c}
              </button>
            ))}
          </div>

          <div className="products-result-meta">
            <span>Showing <strong>{filtered.length}</strong> of {products.length} products</span>
            {(activeCategory !== 'All' || activeSearch) && (
              <button type="button" className="btn-reset-filters" onClick={handleClearFilters}>
                Clear filters
              </button>
            )}
          </div>
        </div>
      )}

      {/* States */}
      {loading && <LoadingSpinner label="Loading catalogue products..." />}

      {!loading && error && (
        <EmptyState
          title="Unable to load catalog"
          message={error}
          action={<button className="btn btn-primary btn-sm" onClick={() => window.location.reload()}>Retry</button>}
        />
      )}

      {!loading && !error && filtered.length === 0 && (
        <EmptyState
          title="No products matched your criteria"
          message={activeSearch ? `No matches found for "${activeSearch}". Try broadening your query.` : 'No products available in this category.'}
          action={
            <button className="btn btn-secondary btn-sm" onClick={handleClearFilters}>
              View all products
            </button>
          }
        />
      )}

      {!loading && !error && filtered.length > 0 && (
        <div className="product-grid catalogue-grid">
          {filtered.map((product) => (
            <ProductCard key={product.id} product={product} />
          ))}
        </div>
      )}
    </div>
  );
}

export default Products;
