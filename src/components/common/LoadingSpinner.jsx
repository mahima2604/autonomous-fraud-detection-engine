// LoadingSpinner.jsx — small reusable loading indicator.
function LoadingSpinner({ label = 'Loading…', dark = true }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '24px 0', color: 'var(--color-text-muted)' }}>
      <span className={`spinner ${dark ? 'spinner-dark' : ''}`} />
      <span>{label}</span>
    </div>
  );
}

export default LoadingSpinner;
