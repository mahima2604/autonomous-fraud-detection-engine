// Footer.jsx — shared site footer.
function Footer() {
  return (
    <footer style={{ borderTop: '1px solid var(--color-border)', background: 'var(--color-surface)', marginTop: 48 }}>
      <div className="container" style={{ padding: '28px 20px', display: 'flex', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <span style={{ fontSize: 13.5, color: 'var(--color-text-faint)' }}>
          © {new Date().getFullYear()} SecureCart. A college project demo — not a real store.
        </span>
        <span style={{ fontSize: 13.5, color: 'var(--color-text-faint)' }}>
          Checkout transactions are screened for fraud risk before payment.
        </span>
      </div>
    </footer>
  );
}

export default Footer;
