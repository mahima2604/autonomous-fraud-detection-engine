// AdminBenchmarkPage.jsx
// Simplified IEEE-CIS Fraud Detection benchmark evaluation comparing GraphSAGE and Logistic Regression.

import { useState, useEffect } from 'react';
import { getBenchmarkEvaluation } from '../../services/adminBenchmarkService';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import './AdminBenchmarkPage.css';

function formatMetric(value) {
  return value !== null && value !== undefined && Number.isFinite(Number(value))
    ? Number(value).toFixed(4)
    : '—';
}

function metricLeader(graphsage, logisticRegression) {
  if (graphsage === null || graphsage === undefined || logisticRegression === null || logisticRegression === undefined) return null;
  const graphValue = Number(graphsage);
  const logisticValue = Number(logisticRegression);
  if (!Number.isFinite(graphValue) || !Number.isFinite(logisticValue) || graphValue === logisticValue) return null;
  return graphValue > logisticValue ? 'gs' : 'lr';
}

function formatConfusionCount(value) {
  return value !== null && value !== undefined && Number.isFinite(Number(value))
    ? Number(value).toLocaleString()
    : '—';
}

function AdminBenchmarkPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const fetchBenchmark = (force = false) => {
    if (force) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }
    setError(null);

    getBenchmarkEvaluation(force)
      .then((res) => {
        setData(res);
      })
      .catch((err) => {
        setError(err.message || 'Failed to load IEEE-CIS benchmark evaluation');
      })
      .finally(() => {
        setLoading(false);
        setRefreshing(false);
      });
  };

  useEffect(() => {
    fetchBenchmark(false);
  }, []);

  if (loading) {
    return (
      <div className="admin-benchmark-page">
        <LoadingSpinner label="Loading IEEE-CIS held-out benchmark evaluation..." />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="admin-benchmark-page">
        <div className="benchmark-error-card" role="alert">
          <div className="error-icon" aria-hidden="true">⚠️</div>
          <h3>Unable to Load Benchmark Evaluation</h3>
          <p>{error || 'An unexpected error occurred while loading the evaluation data.'}</p>
          <button className="btn btn-brand btn-sm" onClick={() => fetchBenchmark(false)}>
            Retry Loading
          </button>
        </div>
      </div>
    );
  }

  const {
    dataset_info: dataset = {},
    models = {},
    execution_metadata: meta = {},
  } = data;

  const gsMetrics = models.graphsage?.metrics || {};
  const lrMetrics = models.logistic_regression?.metrics || {};

  const gsCm = gsMetrics.confusion_matrix || {};
  const lrCm = lrMetrics.confusion_matrix || {};

  const comparisonRows = [
    {
      key: 'roc_auc',
      label: 'ROC-AUC',
      sublabel: 'Area under ROC curve',
      gsVal: formatMetric(gsMetrics.roc_auc),
      lrVal: formatMetric(lrMetrics.roc_auc),
      better: metricLeader(gsMetrics.roc_auc, lrMetrics.roc_auc),
    },
    {
      key: 'pr_auc',
      label: 'PR-AUC (Average Precision)',
      sublabel: 'Precision-recall area under curve',
      gsVal: formatMetric(gsMetrics.pr_auc),
      lrVal: formatMetric(lrMetrics.pr_auc),
      better: metricLeader(gsMetrics.pr_auc, lrMetrics.pr_auc),
    },
    {
      key: 'precision',
      label: 'Precision',
      sublabel: 'Positive predictive value',
      gsVal: `${formatMetric(gsMetrics.precision)}${gsMetrics.precision == null ? '' : ` (${(Number(gsMetrics.precision) * 100).toFixed(2)}%)`}`,
      lrVal: `${formatMetric(lrMetrics.precision)}${lrMetrics.precision == null ? '' : ` (${(Number(lrMetrics.precision) * 100).toFixed(2)}%)`}`,
      better: metricLeader(gsMetrics.precision, lrMetrics.precision),
    },
    {
      key: 'recall',
      label: 'Recall',
      sublabel: 'Sensitivity / True positive rate',
      gsVal: `${formatMetric(gsMetrics.recall)}${gsMetrics.recall == null ? '' : ` (${(Number(gsMetrics.recall) * 100).toFixed(2)}%)`}`,
      lrVal: `${formatMetric(lrMetrics.recall)}${lrMetrics.recall == null ? '' : ` (${(Number(lrMetrics.recall) * 100).toFixed(2)}%)`}`,
      better: metricLeader(gsMetrics.recall, lrMetrics.recall),
    },
    {
      key: 'f1',
      label: 'F1 Score',
      sublabel: 'Harmonic mean of precision & recall',
      gsVal: formatMetric(gsMetrics.f1),
      lrVal: formatMetric(lrMetrics.f1),
      better: metricLeader(gsMetrics.f1, lrMetrics.f1),
    },
  ];

  return (
    <div className="admin-benchmark-page">
      {/* 1. Page Heading */}
      <div className="admin-page-header">
        <div className="admin-header-title-group">
          <div className="admin-header-kicker">
            <span className="admin-kicker-dot" />
            <span>Benchmark Evaluation &middot; Offline Research Engine</span>
          </div>
          <h1 className="admin-page-title">Benchmark Evaluation</h1>
          <p className="admin-page-subtitle">
            GraphSAGE vs Logistic Regression on the IEEE-CIS Fraud Detection Dataset.
          </p>
          <p className="benchmark-header-note">
            Offline evaluation on a chronological held-out test set. These results do not establish live checkout accuracy.
          </p>
        </div>
        <div className="admin-header-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => fetchBenchmark(true)}
            disabled={refreshing}
            title="Re-run evaluation across all held-out test transactions"
          >
            {refreshing ? (
              <>
                <span className="spinner-mini" aria-hidden="true" />
                <span>Evaluating...</span>
              </>
            ) : (
              <>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <path d="M23 4v6h-6M1 20v-6h6" />
                  <path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
                </svg>
                <span>Re-run Evaluation</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* 2. Dataset Summary */}
      <section className="benchmark-section" aria-label="Dataset Summary">
        <div className="metrics-summary-grid dataset-summary-grid">
          <div className="metric-card">
            <span className="metric-label">Dataset Name</span>
            <span className="metric-value-text">IEEE-CIS Fraud Detection</span>
            <span className="metric-subtext">Canonical benchmark dataset</span>
          </div>

          <div className="metric-card">
            <span className="metric-label">Data Partition Split</span>
            <span className="metric-value-text">{dataset.split_strategy || 'Unavailable'}</span>
            <span className="metric-subtext">As reported by the evaluation API</span>
          </div>

          <div className="metric-card">
            <span className="metric-label">Held-Out Test Set</span>
            <span className="metric-value font-tabular">
              {formatConfusionCount(dataset.evaluated_test_rows)}
            </span>
            <span className="metric-subtext">Chronological transactions evaluated</span>
          </div>

          <div className="metric-card">
            <span className="metric-label">Test Fraud Cases</span>
            <span className="metric-value font-tabular text-red">
              {formatConfusionCount(dataset.fraud_count)}
            </span>
            <span className="metric-subtext">Ground-truth positive labels</span>
          </div>
        </div>
      </section>

      {/* 3. Model Performance Comparison */}
      <section className="benchmark-section" aria-label="Model Comparison">
        <div className="benchmark-section-header">
          <h2 className="section-title">Model Comparison</h2>
          <span className="section-meta">Decision Threshold = 0.50</span>
        </div>

        <div className="benchmark-comparison-card">
          <div className="table-responsive">
            <table className="benchmark-comparison-table">
              <thead>
                <tr>
                  <th className="th-metric">Metric</th>
                  <th className="th-model">GraphSAGE</th>
                  <th className="th-model">Logistic Regression</th>
                </tr>
              </thead>
              <tbody>
                {comparisonRows.map((row) => (
                  <tr key={row.key}>
                    <td className="metric-name-cell">
                      <span className="metric-name-title">{row.label}</span>
                      <span className="metric-sublabel">{row.sublabel}</span>
                    </td>
                    <td className={`metric-val-cell ${row.better === 'gs' ? 'winner-cell' : ''}`}>
                      <span className="metric-num font-tabular">{row.gsVal}</span>
                      {row.better === 'gs' && (
                        <span className="winner-badge" title="Higher value on test set">Better</span>
                      )}
                    </td>
                    <td className={`metric-val-cell ${row.better === 'lr' ? 'winner-cell' : ''}`}>
                      <span className="metric-num font-tabular">{row.lrVal}</span>
                      {row.better === 'lr' && (
                        <span className="winner-badge" title="Higher value on test set">Better</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* 4. Confusion Matrices */}
      <section className="benchmark-section" aria-label="Confusion Matrices">
        <div className="benchmark-section-header">
          <h2 className="section-title">Confusion Matrices</h2>
          <span className="section-meta">Actual vs Predicted at Threshold 0.50</span>
        </div>

        <div className="confusion-matrix-grid">
          {/* GraphSAGE Matrix */}
          <div className="matrix-panel">
            <div className="matrix-header">
              <h3 className="matrix-title">GraphSAGE</h3>
              <span className="matrix-subtitle">GNN Model</span>
            </div>
            <div className="matrix-table-wrapper">
              <table className="matrix-table">
                <thead>
                  <tr>
                    <th aria-label="Empty header corner"></th>
                    <th>Pred Legitimate (0)</th>
                    <th>Pred Fraud (1)</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="row-header">Actual Legitimate (0)</td>
                    <td className="cell-tn">
                      <strong>{formatConfusionCount(gsCm.tn)}</strong>
                      <span>True Negatives (TN)</span>
                    </td>
                    <td className="cell-fp">
                      <strong>{formatConfusionCount(gsCm.fp)}</strong>
                      <span>False Positives (FP)</span>
                    </td>
                  </tr>
                  <tr>
                    <td className="row-header">Actual Fraud (1)</td>
                    <td className="cell-fn">
                      <strong>{formatConfusionCount(gsCm.fn)}</strong>
                      <span>False Negatives (FN)</span>
                    </td>
                    <td className="cell-tp">
                      <strong>{formatConfusionCount(gsCm.tp)}</strong>
                      <span>True Positives (TP)</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>

          {/* Logistic Regression Matrix */}
          <div className="matrix-panel">
            <div className="matrix-header">
              <h3 className="matrix-title">Logistic Regression</h3>
              <span className="matrix-subtitle">Baseline Model</span>
            </div>
            <div className="matrix-table-wrapper">
              <table className="matrix-table">
                <thead>
                  <tr>
                    <th aria-label="Empty header corner"></th>
                    <th>Pred Legitimate (0)</th>
                    <th>Pred Fraud (1)</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="row-header">Actual Legitimate (0)</td>
                    <td className="cell-tn">
                      <strong>{formatConfusionCount(lrCm.tn)}</strong>
                      <span>True Negatives (TN)</span>
                    </td>
                    <td className="cell-fp">
                      <strong>{formatConfusionCount(lrCm.fp)}</strong>
                      <span>False Positives (FP)</span>
                    </td>
                  </tr>
                  <tr>
                    <td className="row-header">Actual Fraud (1)</td>
                    <td className="cell-fn">
                      <strong>{formatConfusionCount(lrCm.fn)}</strong>
                      <span>False Negatives (FN)</span>
                    </td>
                    <td className="cell-tp">
                      <strong>{formatConfusionCount(lrCm.tp)}</strong>
                      <span>True Positives (TP)</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </section>

      {/* 5. Short Limitations Note */}
      <div className="benchmark-limitations-notice" role="note">
        <div className="limitations-header">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" className="limitations-icon">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <strong>Evaluation Scope &amp; Operational Limitations</strong>
        </div>
        <ul className="limitations-list">
          <li>This is an offline historical benchmark, not a live checkout accuracy measurement.</li>
          <li>The live GraphSAGE topology is not fully validated because trustworthy DeviceInfo is unavailable.</li>
          <li>Historical benchmark performance must not override live checkout safeguards or admin REVIEW decisions.</li>
        </ul>
      </div>

      {/* Optional Collapsed Technical Details for College Review / Project Transparency */}
      <details className="benchmark-technical-details">
        <summary>Technical details &amp; execution metadata</summary>
        <div className="technical-details-content">
          <p>
            <strong>Partitioning:</strong> {dataset.split_strategy || 'Unavailable'}.
          </p>
          <p>
            <strong>Features:</strong> 1 Numeric (TransactionAmt) &middot; 4 Categorical (ProductCD, P_emaildomain, DeviceType, DeviceInfo) &middot; 2 Graph Edges (P_emaildomain, DeviceInfo).
          </p>
          <p>
            <strong>Execution:</strong> Evaluated on {meta.device || 'Unavailable'} &middot; Computation: {meta.evaluation_time_seconds == null ? 'Unavailable' : `${meta.evaluation_time_seconds}s`} &middot; Recorded: {meta.evaluated_at || 'Unavailable'}.
          </p>
        </div>
      </details>
    </div>
  );
}

export default AdminBenchmarkPage;
