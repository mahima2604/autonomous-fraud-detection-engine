// RiskBadge.jsx — small colored badge for LOW / MEDIUM / HIGH risk levels.
// Purely presentational — never computes risk, only displays a value it
// is given.
function RiskBadge({ riskLevel }) {
  const level = (riskLevel || '').toLowerCase();
  const className = ['low', 'medium', 'high'].includes(level) ? `badge-${level}` : 'badge-neutral';
  return <span className={`badge ${className}`}>{riskLevel || 'Unknown'} risk</span>;
}

export default RiskBadge;
