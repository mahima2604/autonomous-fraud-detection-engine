// FraudDashboard.jsx
// Enterprise-grade Fraud Monitoring Overview & Decision Intelligence backed by the fraud API.

import { useEffect, useState, useMemo } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { getRecentFraudPredictions, getFraudSummary } from '../../services/fraudService';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import RiskBadge from '../../components/fraud/RiskBadge';
import { formatCurrency, formatDateTime } from '../../utils/formatters';
import './FraudDashboard.css';


const DECISION_CLASS = {
  APPROVE: 'badge-low',
  REVIEW: 'badge-medium',
  BLOCK: 'badge-high',
};

function FraudDashboard() {
  const location = useLocation();
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [transactions, setTransactions] = useState([]);
  const [summaryLoaded, setSummaryLoaded] = useState(false);
  const [predictionsLoaded, setPredictionsLoaded] = useState(false);
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [riskFilter, setRiskFilter] = useState('ALL');

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
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Handle anchor navigation if navigated to /admin/dashboard#fraud-predictions
  useEffect(() => {
    if (location.hash === '#fraud-predictions') {
      const element = document.getElementById('fraud-predictions');
      if (element) {
        setTimeout(() => {
          element.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 100);
      }
    }
  }, [location.hash, predictionsLoaded]);

  // Derived real data metrics
  const stats = useMemo(() => {
    if (!summary) return null;
    const total = summary.total_predictions || 0;
    const low = summary.risk_breakdown?.LOW || 0;
    const med = summary.risk_breakdown?.MEDIUM || 0;
    const high = summary.risk_breakdown?.HIGH || 0;

    const lowPct = total > 0 ? ((low / total) * 100).toFixed(1) : '0.0';
    const medPct = total > 0 ? ((med / total) * 100).toFixed(1) : '0.0';
    const highPct = total > 0 ? ((high / total) * 100).toFixed(1) : '0.0';

    return { total, low, med, high, lowPct, medPct, highPct };
  }, [summary]);

  // Client-side filtering on monitoring cases table
  const filteredCases = useMemo(() => {
    const query = searchQuery.trim().toLowerCase();
    return transactions.filter((t) => {
      const idMatch = String(t.transactionId ?? t.id ?? '').toLowerCase().includes(query);
      const nameMatch = String(t.customer_name ?? '').toLowerCase().includes(query);
      const emailMatch = String(t.customer_email ?? '').toLowerCase().includes(query);
      const modelMatch = String(t.model_used ?? '').toLowerCase().includes(query);
      const matchesSearch = !query || idMatch || nameMatch || emailMatch || modelMatch;

      const matchesRisk = riskFilter === 'ALL' || t.riskLevel === riskFilter;
      return matchesSearch && matchesRisk;
    });
  }, [transactions, searchQuery, riskFilter]);

  if (loading && !summary && !predictionsLoaded) {
    return <LoadingSpinner label="Loading fraud metrics and active cases..." />;
  }

  const hasUsableData = summaryLoaded || predictionsLoaded;
  if (!loading && errors.length > 0 && !hasUsableData) {
    return (
      <div className="fraud-dashboard-error" role="alert">
        <p>Unable to load fraud dashboard data. Please check connection and try again.</p>
        <button onClick={fetchData} className="btn btn-secondary" disabled={loading}>
          Retry
        </button>
      </div>
    );
  }

  return (
    <div className="fraud-dashboard">
      {/* Page Header */}
      <div className="admin-page-header">
        <div className="admin-header-title-group">
          <div className="admin-header-kicker">
            <span className="admin-kicker-dot" />
            <span>Fraud Risk Intelligence &middot; Active Baseline Model</span>
          </div>
          <h1 className="admin-page-title">Fraud Monitoring Dashboard</h1>
          <p className="admin-page-subtitle">
            Real-time transaction risk scoring, automated threshold decisions, and flagged review queue.
          </p>
        </div>
        <div className="admin-header-actions">
          <button
            id="fraud-dashboard-refresh-btn"
            onClick={fetchData}
            className="btn btn-secondary admin-refresh-btn"
            disabled={loading}
            title="Refresh dashboard metrics and recent cases"
          >
            <svg
              className={`admin-refresh-icon ${loading ? 'spinning' : ''}`}
              width="15"
              height="15"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2.2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21.5 2v6h-6M2.5 22v-6h6M2 11.5a10 10 0 0 1 18.8-4.3M22 12.5a10 10 0 0 1-18.8 4.2" />
            </svg>
            <span>{loading ? 'Refreshing...' : 'Refresh'}</span>
          </button>
        </div>
      </div>

      {/* Partial error notice if applicable */}
      {errors.length > 0 && (
        <div className="admin-alert-banner admin-alert-warning" role="alert" aria-live="polite">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <line x1="12" y1="9" x2="12" y2="13" />
            <line x1="12" y1="17" x2="12.01" y2="17" />
          </svg>
          <div className="admin-alert-content">
            <strong>Partial data refresh:</strong>
            {errors.map(({ section, stale }) => (
              <span key={section}>
                {' '}
                {section} could not be updated{stale ? ' (displaying cached data)' : ''}.
              </span>
            ))}
          </div>
        </div>
      )}

      {/* 4 Aligned KPI Cards */}
      {stats ? (
        <div className="admin-kpi-grid">
          <div className="admin-kpi-card kpi-total">
            <div className="kpi-header">
              <span className="kpi-label">Assessed Transactions</span>
              <span className="kpi-pill kpi-pill-neutral">100% evaluated</span>
            </div>
            <div className="kpi-value-row">
              <span className="kpi-value">{stats.total.toLocaleString()}</span>
              <div className="kpi-icon-wrap" aria-hidden="true">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
                </svg>
              </div>
            </div>
            <p className="kpi-footer">Total predictions recorded in pipeline</p>
          </div>

          <div className="admin-kpi-card kpi-approved">
            <div className="kpi-header">
              <span className="kpi-label">Approved (Low Risk)</span>
              <span className="kpi-pill kpi-pill-success">{stats.lowPct}%</span>
            </div>
            <div className="kpi-value-row">
              <span className="kpi-value text-success">{stats.low.toLocaleString()}</span>
              <div className="kpi-icon-wrap icon-success" aria-hidden="true">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
                  <polyline points="22 4 12 14.01 9 11.01" />
                </svg>
              </div>
            </div>
            <p className="kpi-footer">Threshold score &le; 0.30 &middot; Auto-approved</p>
          </div>

          <div className="admin-kpi-card kpi-review">
            <div className="kpi-header">
              <span className="kpi-label">Under Review (Medium)</span>
              <span className="kpi-pill kpi-pill-warning">{stats.medPct}%</span>
            </div>
            <div className="kpi-value-row">
              <span className="kpi-value text-warning">{stats.med.toLocaleString()}</span>
              <div className="kpi-icon-wrap icon-warning" aria-hidden="true">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="12" y1="8" x2="12" y2="12" />
                  <line x1="12" y1="16" x2="12.01" y2="16" />
                </svg>
              </div>
            </div>
            <p className="kpi-footer">0.30 &lt; score &le; 0.70 &middot; Requires admin action</p>
          </div>

          <div className="admin-kpi-card kpi-blocked">
            <div className="kpi-header">
              <span className="kpi-label">Blocked (High Risk)</span>
              <span className="kpi-pill kpi-pill-danger">{stats.highPct}%</span>
            </div>
            <div className="kpi-value-row">
              <span className="kpi-value text-danger">{stats.high.toLocaleString()}</span>
              <div className="kpi-icon-wrap icon-danger" aria-hidden="true">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10" />
                  <line x1="4.93" y1="4.93" x2="19.07" y2="19.07" />
                </svg>
              </div>
            </div>
            <p className="kpi-footer">Score &gt; 0.70 &middot; Auto-rejected at gateway</p>
          </div>
        </div>
      ) : summaryLoaded ? null : (
        <div className="fraud-dashboard-unavailable" role="status">
          Fraud summary statistics are currently unavailable.
        </div>
      )}

      {/* Risk Distribution Breakdown Panel */}
      {stats && (
        <div className="card admin-distribution-card">
          <div className="admin-distribution-header">
            <div>
              <h2 className="admin-card-title">Risk Distribution & Decision Breakdown</h2>
              <p className="admin-card-description">
                Overall classification balance derived from all assessed transactions.
              </p>
            </div>
            <div className="admin-distribution-legend">
              <span className="legend-item"><span className="legend-dot dot-low" /> Approved ({stats.low})</span>
              <span className="legend-item"><span className="legend-dot dot-medium" /> Under Review ({stats.med})</span>
              <span className="legend-item"><span className="legend-dot dot-high" /> Blocked ({stats.high})</span>
            </div>
          </div>

          <div className="admin-progress-track" title={`Approved: ${stats.lowPct}%, Review: ${stats.medPct}%, Blocked: ${stats.highPct}%`}>
            <div className="progress-seg seg-low" style={{ width: `${stats.lowPct}%` }} />
            <div className="progress-seg seg-medium" style={{ width: `${stats.medPct}%` }} />
            <div className="progress-seg seg-high" style={{ width: `${stats.highPct}%` }} />
          </div>

          <div className="admin-distribution-metrics">
            <div className="distribution-metric">
              <span className="dist-label">Auto-Approval Rate</span>
              <strong className="dist-value text-success">{stats.lowPct}%</strong>
            </div>
            <div className="distribution-metric">
              <span className="dist-label">Manual Review Queue Rate</span>
              <strong className="dist-value text-warning">{stats.medPct}%</strong>
            </div>
            <div className="distribution-metric">
              <span className="dist-label">Automated Prevention Rate</span>
              <strong className="dist-value text-danger">{stats.highPct}%</strong>
            </div>
            <div className="distribution-metric">
              <span className="dist-label">Active Serving Model</span>
              <strong className="dist-value text-muted" title={`Active runtime model: ${summary?.active_model || 'GraphSAGE'}`}>
                {summary?.active_model ? `${summary.active_model} (Active)` : 'GraphSAGE (Active)'}
              </strong>
            </div>
          </div>
        </div>
      )}

      {/* Monitoring Cases Section */}
      <div id="fraud-predictions" className="admin-section-anchor" />
      <div className="card admin-table-card">
        <div className="admin-table-toolbar">
          <div className="admin-toolbar-title-wrap">
            <h2 className="admin-card-title">Fraud Monitoring Cases</h2>
            <p className="admin-card-description">
              Transactions evaluated with REVIEW or BLOCK model outcomes, or with an administrative decision recorded.
            </p>
          </div>
          <div className="admin-toolbar-controls">
            <div className="admin-search-wrapper">
              <svg className="admin-search-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                <circle cx="11" cy="11" r="8" />
                <line x1="21" y1="21" x2="16.65" y2="16.65" />
              </svg>
              <input
                id="fraud-dashboard-search"
                type="text"
                className="admin-input admin-search-input"
                placeholder="Search transaction, customer, email..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
              />
              {searchQuery && (
                <button
                  type="button"
                  className="admin-search-clear"
                  onClick={() => setSearchQuery('')}
                  title="Clear search"
                >
                  &times;
                </button>
              )}
            </div>

            <select
              id="fraud-dashboard-risk-filter"
              className="admin-select"
              value={riskFilter}
              onChange={(e) => setRiskFilter(e.target.value)}
              aria-label="Filter cases by risk level"
            >
              <option value="ALL">All Risk Levels</option>
              <option value="HIGH">High Risk Only</option>
              <option value="MEDIUM">Medium Risk Only</option>
              <option value="LOW">Low Risk Only</option>
            </select>
          </div>
        </div>

        {/* Controlled Scroll Container */}
        <div className="admin-table-scroll-container">
          <table className="admin-table">
            <thead>
              <tr>
                <th className="col-id">Transaction ID</th>
                <th className="col-customer">Customer</th>
                <th className="col-amount">Amount</th>
                <th className="col-risk">Risk Level</th>
                <th className="col-score">Risk Score</th>
                <th className="col-decision">Model Decision</th>
                <th className="col-status">Checkout Status</th>
                <th className="col-review">Admin Review</th>
                <th className="col-model">Model Used</th>
                <th className="col-time">Timestamp</th>
                <th className="col-action">Explanation</th>
              </tr>
            </thead>
            <tbody>
              {filteredCases.length === 0 ? (
                <tr>
                  <td colSpan="11" className="admin-table-empty">
                    {transactions.length === 0
                      ? 'No transactions currently meet the fraud monitoring filters.'
                      : 'No monitoring cases match your current search or risk filter.'}
                  </td>
                </tr>
              ) : (
                filteredCases.map((t) => {
                  const txId = t.transactionId ?? t.id;

                  return (
                    <tr key={txId}>
                      <td className="col-id">
                        <span className="admin-txn-id">TXN-{txId}</span>
                      </td>
                      <td className="col-customer">
                        {t.customer_name || t.customer_email ? (
                          <div className="admin-customer-cell">
                            <span className="customer-name">{t.customer_name || 'Name unassigned'}</span>
                            <span className="customer-email">{t.customer_email || 'No email'}</span>
                          </div>
                        ) : (
                          <span className="text-muted">Unassigned</span>
                        )}
                      </td>
                      <td className="col-amount font-tabular">
                        <strong>{formatCurrency(t.amount || 0)}</strong>
                      </td>
                      <td className="col-risk">
                        <RiskBadge riskLevel={t.riskLevel} />
                      </td>
                      <td className="col-score font-tabular">
                        <span className="risk-score-value">{Number(t.fraudScore).toFixed(4)}</span>
                      </td>
                      <td className="col-decision">
                        <span className={`badge ${DECISION_CLASS[t.decision] || 'badge-neutral'}`}>
                          {t.decision}
                        </span>
                      </td>
                      <td className="col-status">
                        <span className="status-cell-text">{t.status === 'REVIEW_APPROVED' ? 'Review Approved' : t.status || '—'}</span>
                      </td>
                      <td className="col-review">
                        {t.review_decision === 'APPROVE' ? (
                          <span className="badge badge-low">Approved</span>
                        ) : t.review_decision === 'REJECT' ? (
                          <span className="badge badge-high">Rejected</span>
                        ) : t.status === 'REVIEW' ? (
                          <span className="badge badge-medium">Pending Review</span>
                        ) : (
                          <span className="text-muted">—</span>
                        )}
                      </td>
                      <td className="col-model">
                        <span className="model-tag" title={t.model_used || 'Unknown'}>
                          {t.model_used || 'Unknown'}
                        </span>
                      </td>
                      <td className="col-time font-tabular">
                        <span className="time-cell-text">{formatDateTime(t.created_at || t.timestamp)}</span>
                      </td>
                      <td className="col-action">
                        <button
                          id={`btn-explain-case-${txId}`}
                          type="button"
                          className="btn-action-explain"
                          onClick={() => navigate(`/admin/transactions/${txId}/explanation`)}
                          title="Open detailed prediction explanation page"
                        >
                          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                            <polyline points="9 18 15 12 9 6" />
                          </svg>
                          <span>Explain &rarr;</span>
                        </button>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default FraudDashboard;
