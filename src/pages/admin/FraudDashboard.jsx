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
  const [summaryLoaded, setSummaryLoaded] = useState(false);
  const [predictionsLoaded, setPredictionsLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState([]);

  const fetchData = async () => {
    setLoading(true);


    const results = await Promise.allSettled([
      getFraudSummary(),
      getRecentFraudPredictions(),
    ]);
    const nextErrors = [];

    if (results[0].status === 'fulfilled') {
      setSummary(results[0].value);
      setSummaryLoaded(true);
    } else {
      nextErrors.push({
        section: 'Fraud summary',
        stale: summaryLoaded,
      });
    }

    if (results[1].status === 'fulfilled') {
      setTransactions(results[1].value);
      setPredictionsLoaded(true);
    } else {
      nextErrors.push({
        section: 'Recent predictions',
        stale: predictionsLoaded,
      });
    }

    setErrors(nextErrors);
    setLoading(false);
  };

  useEffect(() => {
    fetchData();
  // Load once on mount; fetchData intentionally captures the initial loaded flags.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (loading && !summary && !predictionsLoaded) {
    return <LoadingSpinner label="Loading fraud metrics..." />;
  }

  const hasUsableData = summaryLoaded || predictionsLoaded;
  if (!loading && errors.length > 0 && !hasUsableData) {
    return (
      <div className="fraud-dashboard-error" role="alert">
        <p>Unable to load fraud dashboard data. Please try again.</p>
        <button onClick={fetchData} className="btn btn-outline" disabled={loading}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h1>Fraud Monitoring</h1>
        <button onClick={fetchData} className="btn btn-outline" disabled={loading}>
          {loading ? 'Refreshing...' : 'Refresh'}
        </button>
      </div>

      {errors.length > 0 && (
        <div className="fraud-dashboard-error" role="alert" aria-live="polite">
          <p>Some fraud dashboard data could not be refreshed:</p>
          <ul>
            {errors.map(({ section, stale }) => (
              <li key={section}>
                {section} failed to load{stale ? '; showing the last successful data, which may be stale' : ''}.
              </li>
            ))}
          </ul>
          <button onClick={fetchData} className="btn btn-outline" disabled={loading}>
            Retry
          </button>
        </div>
      )}

      {summary ? (
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
      ) : summaryLoaded ? null : (
        <div className="fraud-dashboard-unavailable" role="status">Fraud summary is unavailable.</div>
      )}

      <div className="section-heading" style={{ marginTop: 32 }}>
        <h2 id="fraud-predictions">Fraud predictions</h2>
      </div>

      <div id="transactions" className="card table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Transaction ID</th>
              <th>Customer</th>
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
                <td colSpan="8" style={{ textAlign: 'center', padding: '32px', color: 'var(--color-text-faint)' }}>
                  No recent predictions available.
                </td>
              </tr>
            ) : (
              transactions.map((t) => (
                <tr key={t.id || t.transactionId}>
                  <td>{t.transactionId}</td>
                  <td>
                    {t.customer_name || t.customer_email ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 150 }}>
                        <span>{t.customer_name || 'Name unavailable'}</span>
                        <span style={{ color: 'var(--color-text-faint)', fontSize: 12, overflowWrap: 'anywhere' }}>
                          {t.customer_email || 'Email unavailable'}
                        </span>
                      </div>
                    ) : 'Unassigned'}
                  </td>
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
