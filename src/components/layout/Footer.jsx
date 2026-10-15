// Footer.jsx — Customer-facing e-commerce footer with store navigation, security badges, and brand identity.
import { Link } from 'react-router-dom';
import './Footer.css';

function Footer() {
  return (
    <footer className="store-footer">
      {/* Trust reassurance banner above footer links */}
      <div className="footer-trust-strip">
        <div className="container trust-strip-inner">
          <div className="trust-strip-item">
            <div className="trust-icon" aria-hidden="true">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                <path d="M9 12l2 2 4-4" />
              </svg>
            </div>
            <div>
              <strong>Autonomous AI Security</strong>
              <p>Every checkout is scored in real time against ML baselines.</p>
            </div>
          </div>

          <div className="trust-strip-item">
            <div className="trust-icon" aria-hidden="true">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="1" y="3" width="15" height="13" />
                <polygon points="16 8 20 8 23 11 23 16 16 16 16 8" />
                <circle cx="5.5" cy="18.5" r="2.5" />
                <circle cx="18.5" cy="18.5" r="2.5" />
              </svg>
            </div>
            <div>
              <strong>Free Express Shipping</strong>
              <p>Complimentary tracked delivery on all catalogue items.</p>
            </div>
          </div>

          <div className="trust-strip-item">
            <div className="trust-icon" aria-hidden="true">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
            </div>
            <div>
              <strong>Simulated Safe Payments</strong>
              <p>Zero real credit card storage; protected test environment.</p>
            </div>
          </div>
        </div>
      </div>

      {/* Main Footer Links */}
      <div className="container footer-main-content">
        <div className="footer-columns-grid">
          {/* Brand Col */}
          <div className="footer-brand-col">
            <Link to="/" className="footer-brand">
              <div className="footer-brand-icon" aria-hidden="true">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                  <path d="M9 12l2 2 4-4" />
                </svg>
              </div>
              <span className="footer-brand-title">SecureCart</span>
            </Link>
            <p className="footer-tagline">
              An intelligent e-commerce storefront backed by autonomous machine learning fraud risk scoring and real-time transaction defense.
            </p>
            <div className="footer-cert-badges">
              <span className="cert-pill">
                <span className="cert-dot" /> Live ML Screening
              </span>
              <span className="cert-pill">TLS 256-Bit</span>
            </div>
          </div>

          {/* Catalogue Links */}
          <div className="footer-col">
            <h4 className="footer-heading">Catalog</h4>
            <ul className="footer-links-list">
              <li><Link to="/products">All Products</Link></li>
              <li><Link to="/products?category=Audio">Audio & Headphones</Link></li>
              <li><Link to="/products?category=Wearables">Wearables & Health</Link></li>
              <li><Link to="/products?category=Accessories">Accessories</Link></li>
              <li><Link to="/products?category=Home">Home & Office</Link></li>
            </ul>
          </div>

          {/* Shopper Links */}
          <div className="footer-col">
            <h4 className="footer-heading">Customer Account</h4>
            <ul className="footer-links-list">
              <li><Link to="/cart">Shopping Cart</Link></li>
              <li><Link to="/orders">Order History</Link></li>
              <li><Link to="/dashboard">Account Dashboard</Link></li>
              <li><Link to="/login">Sign In</Link></li>
              <li><Link to="/register">Create Account</Link></li>
            </ul>
          </div>

          {/* Security & Operator */}
          <div className="footer-col">
            <h4 className="footer-heading">Security Platform</h4>
            <ul className="footer-links-list">
              <li><span className="footer-note-text">Active Model: Logistic Regression Baseline</span></li>
              <li><span className="footer-note-text">Automated Threshold Decisions</span></li>
              <li><span className="footer-note-text">Feature Contribution Attributions</span></li>
              <li>
                <Link to="/admin/login" className="footer-admin-btn">
                  <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                  <span>Admin Console Sign In &rarr;</span>
                </Link>
              </li>
            </ul>
          </div>
        </div>

        {/* Bottom copyright & disclaimers */}
        <div className="footer-bottom-bar">
          <p className="copyright-text">
            &copy; {new Date().getFullYear()} SecureCart &middot; Autonomous Fraud Detection and Prevention Engine. All simulated rights reserved.
          </p>
          <p className="disclaimer-text">
            Simulated checkout environment. Fraud scores support automated risk evaluation and administrative review.
          </p>
        </div>
      </div>
    </footer>
  );
}

export default Footer;
