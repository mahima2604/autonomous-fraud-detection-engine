// Home.jsx — Modern, customer-centric e-commerce storefront landing page.
import { Link } from 'react-router-dom';
import { useEffect, useState } from 'react';
import ProductCard from '../components/product/ProductCard';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { getProducts } from '../services/productService';
import './Home.css';

const CATEGORIES = [
  { name: 'Audio', label: 'Audio & Sound', icon: '🎧', count: 'Headphones & Speakers' },
  { name: 'Wearables', label: 'Wearable Tech', icon: '⌚', count: 'Trackers & Smartbands' },
  { name: 'Accessories', label: 'Accessories', icon: '⌨️', count: 'Keyboards & Peripherals' },
  { name: 'Bags', label: 'Bags & Packs', icon: '🎒', count: 'Daypacks & Sleeves' },
  { name: 'Home', label: 'Home & Living', icon: '💡', count: 'Lamps & Essentials' },
  { name: 'Footwear', label: 'Footwear', icon: '👟', count: 'Running & Lifestyle' },
];

function Home() {
  const [featured, setFeatured] = useState([]);
  const [totalCount, setTotalCount] = useState(0);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getProducts()
      .then((products) => {
        if (active) {
          setTotalCount(products.length);
          setFeatured(products.slice(0, 4));
        }
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="home-storefront">
      {/* 1. High-Impact Commerce Hero */}
      <section className="store-hero">
        <div className="hero-content">
          <div className="hero-kicker">
            <span className="hero-kicker-dot" />
            <span>Curated Lifestyle &middot; Premium Gear</span>
          </div>
          <h1 className="hero-heading">
            Premium Gear &amp; Tech for Modern Living.
          </h1>
          <p className="hero-description">
            Discover carefully crafted everyday essentials, high-fidelity audio, wearables, and workspace accessories. Designed for performance, style, and everyday reliability.
          </p>
          <div className="hero-cta-group">
            <Link to="/products" className="btn btn-brand hero-primary-btn">
              <span>Shop All Products</span>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                <line x1="5" y1="12" x2="19" y2="12" />
                <polyline points="12 5 19 12 12 19" />
              </svg>
            </Link>
            <Link to="/register" className="btn btn-secondary hero-secondary-btn">
              Create Free Account
            </Link>
          </div>

          <div className="hero-trust-metrics">
            <div className="metric-item">
              <strong>100%</strong>
              <span>Authentic Gear</span>
            </div>
            <div className="metric-divider" />
            <div className="metric-item">
              <strong>Free</strong>
              <span>Express Delivery</span>
            </div>
            <div className="metric-divider" />
            <div className="metric-item">
              <strong>30-Day</strong>
              <span>Easy Returns</span>
            </div>
          </div>
        </div>

        {/* Hero Visual Card */}
        <div className="hero-showcase-panel">
          <div className="showcase-card">
            <div className="showcase-badge">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="M9 12l2 2 4-4" />
              </svg>
              <span>The SecureCart Promise</span>
            </div>
            <h3 className="showcase-title">Why Shop With Us</h3>
            <div className="showcase-steps-list">
              <div className="showcase-step">
                <span className="step-badge">1</span>
                <div>
                  <strong>Curated Selection</strong>
                  <p>Handpicked products tested for superior durability, design, and performance.</p>
                </div>
              </div>
              <div className="showcase-step">
                <span className="step-badge">2</span>
                <div>
                  <strong>Fast &amp; Tracked Dispatch</strong>
                  <p>Same-day order processing with instant tracking straight to your door.</p>
                </div>
              </div>
              <div className="showcase-step">
                <span className="step-badge">3</span>
                <div>
                  <strong>Secure &amp; Encrypted Checkout</strong>
                  <p>Safe payment processing with full buyer protection and zero data sharing.</p>
                </div>
              </div>
            </div>
            <div className="showcase-footer">
              <span className="showcase-note">&bull; Free shipping over $50 &bull; Dedicated 24/7 customer care</span>
            </div>
          </div>
        </div>
      </section>

      {/* 2. Explore by Category */}
      <section className="store-section">
        <div className="section-header-row">
          <div>
            <span className="section-eyebrow">Product Collections</span>
            <h2 className="section-title">Explore by Category</h2>
          </div>
          <Link to="/products" className="section-action-link">
            <span>All Categories ({totalCount || 8})</span>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <path d="M5 12h14M12 5l7 7-7 7" />
            </svg>
          </Link>
        </div>

        <div className="categories-grid">
          {CATEGORIES.map((cat) => (
            <Link
              key={cat.name}
              to={`/products?category=${encodeURIComponent(cat.name)}`}
              className="category-tile"
            >
              <span className="cat-icon" aria-hidden="true">{cat.icon}</span>
              <div className="cat-info">
                <strong>{cat.label}</strong>
                <span>{cat.count}</span>
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* 3. Featured Products */}
      <section className="store-section">
        <div className="section-header-row">
          <div>
            <span className="section-eyebrow">Top Rated Essentials</span>
            <h2 className="section-title">Featured Products</h2>
          </div>
          <Link to="/products" className="section-action-link">
            <span>View Full Catalog &rarr;</span>
          </Link>
        </div>

        {loading ? (
          <LoadingSpinner label="Loading featured products..." />
        ) : (
          <div className="product-grid">
            {featured.map((product) => (
              <ProductCard key={product.id} product={product} />
            ))}
          </div>
        )}
      </section>

      {/* 4. Storefront Assurance Grid */}
      <section className="store-section assurance-section">
        <div className="assurance-header">
          <h2>Why Shop With SecureCart</h2>
          <p>Premium quality gear, fast fulfillment, and complete peace of mind on every order.</p>
        </div>

        <div className="assurance-cards-grid">
          <div className="assurance-card">
            <div className="assurance-icon-box icon-blue">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="M9 12l2 2 4-4" />
              </svg>
            </div>
            <h3>Safe &amp; Secure Checkout</h3>
            <p>End-to-end 256-bit encryption and advanced order protection ensure your transactions remain completely private.</p>
          </div>

          <div className="assurance-card">
            <div className="assurance-icon-box icon-green">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                <polyline points="22 4 12 14.01 9 11.01" />
              </svg>
            </div>
            <h3>100% Genuine Quality</h3>
            <p>Every product is sourced directly from certified brands and backed by our full money-back guarantee.</p>
          </div>

          <div className="assurance-card">
            <div className="assurance-icon-box icon-purple">
              <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="1" y="3" width="15" height="13" />
                <polygon points="16 8 20 8 23 11 23 16 16 16 16 8" />
                <circle cx="5.5" cy="18.5" r="2.5" />
                <circle cx="18.5" cy="18.5" r="2.5" />
              </svg>
            </div>
            <h3>Fast Tracked Delivery</h3>
            <p>Complimentary tracked express shipping with instant tracking updates from our warehouse to your door.</p>
          </div>
        </div>
      </section>
    </div>
  );
}

export default Home;
