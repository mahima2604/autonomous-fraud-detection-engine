// FraudDashboard.jsx
// Admin-facing fraud monitoring overview backed by the fraud API.
import { useEffect, useState } from 'react';
import { getRecentFraudPredictions, getFraudSummary } from '../../services/fraudService';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import RiskBadge from '../../components/fraud/RiskBadge';
import { formatCurrency, formatDateTime } from '../../utils/formatters';
import './FraudDashboard.css';

const DECISION_CLASS = { APPROVE: 'badge-low', REVIEW: 'badge-medium', BLOCK: 'badge-high' };

function FraudDashboard() {
  const [summary, setSummary] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const fetchData = () => {
    setLoading(true);
    setError('');
    Promise.all([getFraudSummary(), getRecentFraudPredictions()])
      .then(([summaryData, recentData]) => {
        setSummary(summaryData);
        setTransactions(recentData);
        setLoading(false);
      })
      .catch(() => {
        setError('Failed to load fraud metrics. Backend may be unavailable.');
        setLoading(false);
      });
  };

  useEffect(() => {
    fetchData();
  }, []);

  if (loading && !summary) return <LoadingSpinner label="Loading fraud metrics…" />;
  
  if (error && !summary) return <div style={{ color: 'var(--color-danger)', padding: 20 }}>{error}</div>;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1>Fraud Monitoring</h1>
        <button onClick={fetchData} className="btn btn-outline" disabled={loading}>
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      <div className="metric-grid">
        <div className="card card-padded metric-card">
          <span className="metric-label">Total predictions</span>
          <span className="metric-value">{summary.total_predictions.toLocaleString()}</span>
        </div>
        <div className="card card-padded metric-card">
          <span className="metric-label">Approved (LOW)</span>
          <span className="metric-value" style={{ color: 'var(--color-success)' }}>{summary.risk_breakdown?.LOW?.toLocaleString() || 0}</span>
        </div>
        <div className="card card-padded metric-card">
          <span className="metric-label">Under review (MEDIUM)</span>
          <span className="metric-value" style={{ color: 'var(--color-warning)' }}>{summary.risk_breakdown?.MEDIUM?.toLocaleString() || 0}</span>
        </div>
        <div className="card card-padded metric-card">
          <span className="metric-label">Blocked (HIGH)</span>
          <span className="metric-value" style={{ color: 'var(--color-danger)' }}>{summary.risk_breakdown?.HIGH?.toLocaleString() || 0}</span>
        </div>
      </div>

      <div className="section-heading" style={{ marginTop: 32 }}>
        <h2 id="fraud-predictions">Fraud predictions</h2>
      </div>

      <div id="transactions" className="card table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Transaction ID</th>
              <th>Amount</th>
              <th>Risk Level</th>
              <th>Fraud Score</th>
              <th>Decision</th>
              <th>Model Used</th>
              <th>Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {transactions.length === 0 ? (
              <tr>
                <td colSpan="7" style={{ textAlign: 'center', padding: '32px', color: 'var(--color-text-faint)' }}>
                  No recent predictions available.
                </td>
              </tr>
            ) : (
              transactions.map((t) => (
                <tr key={t.id || t.transactionId}>
                  <td>{t.transactionId}</td>
                  <td>{formatCurrency(t.amount || 0)}</td>
                  <td><RiskBadge riskLevel={t.riskLevel} /></td>
                  <td>{t.fraudScore}</td>
                  <td><span className={`badge ${DECISION_CLASS[t.decision] || 'badge-neutral'}`}>{t.decision}</span></td>
                  <td>{t.model_used || 'Unknown'}</td>
                  <td>{formatDateTime(t.created_at || t.timestamp)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

    </div>
  );
}

export default FraudDashboard;
