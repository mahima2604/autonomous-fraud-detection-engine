// Home.jsx — landing page: hero, security messaging, product highlights.
import { Link } from 'react-router-dom';
import { useEffect, useState } from 'react';
import ProductCard from '../components/product/ProductCard';
import LoadingSpinner from '../components/common/LoadingSpinner';
import { getProducts } from '../services/productService';
import './Home.css';

function Home() {
  const [featured, setFeatured] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getProducts()
      .then((products) => {
        if (active) setFeatured(products.slice(0, 4));
      })
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  return (
    <div className="home">
      <section className="hero">
        <div className="hero-text">
          <span className="hero-eyebrow">Checkout, screened</span>
          <h1>Shop confidently. Every checkout is reviewed for fraud risk.</h1>
          <p>
            SecureCart pairs an ordinary online store with a fraud-risk check that runs before
            payment is confirmed — flagging unusual transactions so more of your genuine orders
            go through smoothly.
          </p>
          <div className="hero-actions">
            <Link to="/products" className="btn btn-primary">Browse products</Link>
            <Link to="/register" className="btn btn-secondary">Create an account</Link>
          </div>
        </div>
        <div className="hero-panel card card-padded">
          <h3>How checkout protection works</h3>
          <ol className="hero-steps">
            <li>You add items to your cart and check out as usual.</li>
            <li>We send the transaction details for a fraud risk review.</li>
            <li>Low-risk orders continue straight to payment.</li>
            <li>Unusual orders get a quick extra verification step.</li>
          </ol>
          <p className="mock-note" style={{ marginTop: 12 }}>
            This review reduces — it does not eliminate — fraudulent transactions.
          </p>
        </div>
      </section>

      <section>
        <div className="section-heading">
          <h2>Featured products</h2>
          <Link to="/products" className="btn-link">View all →</Link>
        </div>
        {loading ? (
          <LoadingSpinner label="Loading products…" />
        ) : (
          <div className="product-grid">
            {featured.map((product) => (
              <ProductCard key={product.id} product={product} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

export default Home;
