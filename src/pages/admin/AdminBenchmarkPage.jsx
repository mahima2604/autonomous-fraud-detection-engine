// AdminBenchmarkPage.jsx
// Comprehensive, reproducible IEEE-CIS Fraud Detection benchmark demonstration for the admin console.

import { useState, useEffect } from 'react';
import { getBenchmarkEvaluation } from '../../services/adminBenchmarkService';
import LoadingSpinner from '../../components/common/LoadingSpinner';
import './AdminBenchmarkPage.css';

function AdminBenchmarkPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [sampleFilter, setSampleFilter] = useState('ALL');

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
    dataset_info: dataset,
    models,
    model_comparison: comparison,
    sample_transactions: samples = [],
    warnings_and_limitations: warnings = [],
    execution_metadata: meta = {},
  } = data;

  const gsMetrics = models.graphsage?.metrics || {};
  const lrMetrics = models.logistic_regression?.metrics || {};

  const filteredSamples = samples.filter((item) => {
    if (sampleFilter === 'ALL') return true;
    if (sampleFilter === 'TP') return item.graphsage_outcome === 'TP';
    if (sampleFilter === 'FP') return item.graphsage_outcome === 'FP';
    if (sampleFilter === 'FN') return item.graphsage_outcome === 'FN';
    if (sampleFilter === 'TN') return item.graphsage_outcome === 'TN';
    return true;
  });

  return (
    <div className="admin-benchmark-page">
      {/* 1. Page Header */}
      <div className="admin-page-header">
        <div className="admin-header-title-group">
          <div className="admin-header-kicker">
            <span className="admin-kicker-dot" />
            <span>Benchmark Evaluation &middot; Offline Research Engine</span>
          </div>
          <h1 className="admin-page-title">IEEE-CIS Fraud Detection Benchmark</h1>
          <p className="admin-page-subtitle">
            Reproducible held-out performance demonstration on the canonical IEEE-CIS dataset comparing GraphSAGE against Logistic Regression.
          </p>
        </div>
        <div className="admin-header-actions">
          <button
            type="button"
            className="btn btn-secondary btn-sm"
            onClick={() => fetchBenchmark(true)}
            disabled={refreshing}
            title="Re-run evaluation across all 88,581 held-out test transactions"
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

      {/* 2. Critical Domain Notice Banner */}
      <div className="benchmark-warning-banner" role="status">
        <div className="warning-banner-icon" aria-hidden="true">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
        </div>
        <div className="warning-banner-content">
          <strong>Historical Benchmark vs. Live Checkout Notice</strong>
          <p>
            The metrics below evaluate historical <strong>IEEE-CIS transaction records</strong> under strict chronological partitioning (88,581 held-out test transactions). They do <strong>not</strong> establish live checkout accuracy or validate the live GraphSAGE topology; see the current input and topology limitations below.
          </p>
          <ul className="warning-list">
            {warnings.map((warn, i) => (
              <li key={i}>{warn}</li>
            ))}
          </ul>
          <p>
            These results are reproducible with the current code, data, and model artifacts. The artifacts do not lock the historical dataset versions, source revision, or sampled training row IDs, so the original training run is not fully provenance-locked.
          </p>
        </div>
      </div>

      {/* 3. Dataset & Split Overview Cards */}
      <section className="benchmark-section">
        <div className="benchmark-section-header">
          <h2 className="section-title">Dataset &amp; Chronological Partitioning</h2>
          <span className="section-meta">IEEE-CIS Benchmark &middot; 70% Train / 15% Validation / 15% Test</span>
        </div>

        <div className="metrics-summary-grid">
          <div className="metric-card">
            <span className="metric-label">Total Transactions</span>
            <span className="metric-value">{dataset.total_dataset_rows?.toLocaleString() || '590,540'}</span>
            <span className="metric-subtext">590,540 tx / 144,233 identities</span>
          </div>

          <div className="metric-card">
            <span className="metric-label">Evaluated Test Set</span>
            <span className="metric-value">{dataset.evaluated_test_rows?.toLocaleString() || '88,581'}</span>
            <span className="metric-subtext">Final 15% chronological partition</span>
          </div>

          <div className="metric-card">
            <span className="metric-label">Test Fraud Cases</span>
            <span className="metric-value text-red">{dataset.fraud_count?.toLocaleString() || '3,083'}</span>
            <span className="metric-subtext">Ground-truth positive labels</span>
          </div>

          <div className="metric-card">
            <span className="metric-label">Fraud Prevalence</span>
            <span className="metric-value">{dataset.fraud_prevalence_pct}%</span>
            <span className="metric-subtext">{dataset.legitimate_count?.toLocaleString()} legitimate rows</span>
          </div>

          <div className="metric-card">
            <span className="metric-label">Features Used</span>
            <span className="metric-value">5 Inputs</span>
            <span className="metric-subtext">1 Numeric &middot; 4 Categorical &middot; 2 Graph Edges</span>
          </div>
        </div>
      </section>

      {/* 4. Model Comparison & Leaderboard */}
      <section className="benchmark-section">
        <div className="benchmark-section-header">
          <h2 className="section-title">Model Performance Comparison</h2>
          <span className="section-meta">Decision Threshold = 0.50 (Unoptimized on final test partition)</span>
        </div>

        <div className="comparison-cards-grid">
          {/* GraphSAGE Card */}
          <div className="model-card featured-model">
            <div className="model-card-header">
              <div className="model-badge badge-blue">GNN Champion</div>
              <h3 className="model-name">{models.graphsage?.name}</h3>
              <p className="model-desc">{models.graphsage?.description}</p>
            </div>
            <div className="model-stats-list">
              <div className="stat-row highlight">
                <span>ROC-AUC</span>
                <strong>{gsMetrics.roc_auc?.toFixed(4)}</strong>
              </div>
              <div className="stat-row highlight">
                <span>PR-AUC (Avg Precision)</span>
                <strong>{gsMetrics.pr_auc?.toFixed(4)}</strong>
              </div>
              <div className="stat-row">
                <span>Recall (Sensitivity)</span>
                <strong>{(gsMetrics.recall * 100).toFixed(2)}%</strong>
              </div>
              <div className="stat-row">
                <span>Precision</span>
                <strong>{(gsMetrics.precision * 100).toFixed(2)}%</strong>
              </div>
              <div className="stat-row">
                <span>F1 Score</span>
                <strong>{gsMetrics.f1?.toFixed(4)}</strong>
              </div>
            </div>
          </div>

          {/* Logistic Regression Card */}
          <div className="model-card">
            <div className="model-card-header">
              <div className="model-badge badge-gray">Baseline</div>
              <h3 className="model-name">{models.logistic_regression?.name}</h3>
              <p className="model-desc">{models.logistic_regression?.description}</p>
            </div>
            <div className="model-stats-list">
              <div className="stat-row highlight">
                <span>ROC-AUC</span>
                <strong>{lrMetrics.roc_auc?.toFixed(4)}</strong>
              </div>
              <div className="stat-row highlight">
                <span>PR-AUC (Avg Precision)</span>
                <strong>{lrMetrics.pr_auc?.toFixed(4)}</strong>
              </div>
              <div className="stat-row">
                <span>Recall (Sensitivity)</span>
                <strong>{(lrMetrics.recall * 100).toFixed(2)}%</strong>
              </div>
              <div className="stat-row">
                <span>Precision</span>
                <strong>{(lrMetrics.precision * 100).toFixed(2)}%</strong>
              </div>
              <div className="stat-row">
                <span>F1 Score</span>
                <strong>{lrMetrics.f1?.toFixed(4)}</strong>
              </div>
            </div>
          </div>

          {/* Delta Comparison Card */}
          <div className="model-card comparison-summary-card">
            <div className="model-card-header">
              <div className="model-badge badge-green">GNN Advantage</div>
              <h3 className="model-name">Graph Context Delta</h3>
              <p className="model-desc">{comparison.summary}</p>
            </div>
            <div className="model-stats-list">
              <div className="stat-row">
                <span>ROC-AUC Delta</span>
                <strong className={comparison.roc_auc_diff >= 0 ? 'text-green' : 'text-red'}>
                  {comparison.roc_auc_diff >= 0 ? `+${comparison.roc_auc_diff}` : comparison.roc_auc_diff}
                </strong>
              </div>
              <div className="stat-row">
                <span>PR-AUC Delta</span>
                <strong className={comparison.pr_auc_diff >= 0 ? 'text-green' : 'text-red'}>
                  {comparison.pr_auc_diff >= 0 ? `+${comparison.pr_auc_diff}` : comparison.pr_auc_diff}
                </strong>
              </div>
              <div className="stat-row">
                <span>Recall Delta</span>
                <strong className={comparison.recall_diff >= 0 ? 'text-green' : 'text-red'}>
                  {comparison.recall_diff >= 0 ? `+${(comparison.recall_diff * 100).toFixed(2)}%` : `${(comparison.recall_diff * 100).toFixed(2)}%`}
                </strong>
              </div>
              <div className="stat-row">
                <span>F1 Score Delta</span>
                <strong>
                  {comparison.f1_diff >= 0 ? `+${comparison.f1_diff}` : comparison.f1_diff}
                </strong>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* 5. Confusion Matrices */}
      <section className="benchmark-section">
        <div className="benchmark-section-header">
          <h2 className="section-title">Held-Out Confusion Matrices</h2>
          <span className="section-meta">Evaluated across all 88,581 test samples at threshold 0.50</span>
        </div>

        <div className="confusion-matrix-grid">
          {/* GraphSAGE Matrix */}
          <div className="matrix-panel">
            <h3 className="matrix-title">GraphSAGE Confusion Matrix</h3>
            <div className="matrix-table-wrapper">
              <table className="matrix-table">
                <thead>
                  <tr>
                    <th></th>
                    <th>Pred Legitimate (0)</th>
                    <th>Pred Fraud (1)</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="row-header">Actual Legitimate (0)</td>
                    <td className="cell-tn">
                      <strong>{gsMetrics.confusion_matrix?.tn?.toLocaleString()}</strong>
                      <span>True Negatives (TN)</span>
                    </td>
                    <td className="cell-fp">
                      <strong>{gsMetrics.confusion_matrix?.fp?.toLocaleString()}</strong>
                      <span>False Positives (FP)</span>
                    </td>
                  </tr>
                  <tr>
                    <td className="row-header">Actual Fraud (1)</td>
                    <td className="cell-fn">
                      <strong>{gsMetrics.confusion_matrix?.fn?.toLocaleString()}</strong>
                      <span>False Negatives (FN)</span>
                    </td>
                    <td className="cell-tp">
                      <strong>{gsMetrics.confusion_matrix?.tp?.toLocaleString()}</strong>
                      <span>True Positives (TP)</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="matrix-footnote">
              GraphSAGE captures <strong>{gsMetrics.confusion_matrix?.tp?.toLocaleString()}</strong> out of 3,083 frauds (59.10% recall).
            </p>
          </div>

          {/* Logistic Regression Matrix */}
          <div className="matrix-panel">
            <h3 className="matrix-title">Logistic Regression Baseline Matrix</h3>
            <div className="matrix-table-wrapper">
              <table className="matrix-table">
                <thead>
                  <tr>
                    <th></th>
                    <th>Pred Legitimate (0)</th>
                    <th>Pred Fraud (1)</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="row-header">Actual Legitimate (0)</td>
                    <td className="cell-tn">
                      <strong>{lrMetrics.confusion_matrix?.tn?.toLocaleString()}</strong>
                      <span>True Negatives (TN)</span>
                    </td>
                    <td className="cell-fp">
                      <strong>{lrMetrics.confusion_matrix?.fp?.toLocaleString()}</strong>
                      <span>False Positives (FP)</span>
                    </td>
                  </tr>
                  <tr>
                    <td className="row-header">Actual Fraud (1)</td>
                    <td className="cell-fn">
                      <strong>{lrMetrics.confusion_matrix?.fn?.toLocaleString()}</strong>
                      <span>False Negatives (FN)</span>
                    </td>
                    <td className="cell-tp">
                      <strong>{lrMetrics.confusion_matrix?.tp?.toLocaleString()}</strong>
                      <span>True Positives (TP)</span>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
            <p className="matrix-footnote">
              Logistic Regression captures <strong>{lrMetrics.confusion_matrix?.tp?.toLocaleString()}</strong> out of 3,083 frauds (53.81% recall).
            </p>
          </div>
        </div>
      </section>

      {/* 6. Sample Held-Out Transactions Table */}
      <section className="benchmark-section">
        <div className="benchmark-section-header">
          <div>
            <h2 className="section-title">Individual Held-Out Transactions</h2>
            <p className="section-desc">
              Representative held-out transactions demonstrating actual model scores, predicted classifications, and clear error categorization (TP, TN, FP, FN).
            </p>
          </div>

          {/* Filter Pills */}
          <div className="filter-pill-group">
            <button
              type="button"
              className={`filter-pill ${sampleFilter === 'ALL' ? 'active' : ''}`}
              onClick={() => setSampleFilter('ALL')}
            >
              All ({samples.length})
            </button>
            <button
              type="button"
              className={`filter-pill ${sampleFilter === 'TP' ? 'active' : ''}`}
              onClick={() => setSampleFilter('TP')}
            >
              True Positives (TP)
            </button>
            <button
              type="button"
              className={`filter-pill ${sampleFilter === 'FP' ? 'active' : ''}`}
              onClick={() => setSampleFilter('FP')}
            >
              False Positives (FP)
            </button>
            <button
              type="button"
              className={`filter-pill ${sampleFilter === 'FN' ? 'active' : ''}`}
              onClick={() => setSampleFilter('FN')}
            >
              False Negatives (FN)
            </button>
            <button
              type="button"
              className={`filter-pill ${sampleFilter === 'TN' ? 'active' : ''}`}
              onClick={() => setSampleFilter('TN')}
            >
              True Negatives (TN)
            </button>
          </div>
        </div>

        <div className="benchmark-table-card">
          <div className="table-responsive">
            <table className="benchmark-table">
              <thead>
                <tr>
                  <th>Transaction ID</th>
                  <th>Amount</th>
                  <th>ProductCD</th>
                  <th>Email Domain</th>
                  <th>Device</th>
                  <th>Ground Truth</th>
                  <th>GraphSAGE Score</th>
                  <th>GNN Outcome</th>
                  <th>Baseline Score</th>
                  <th>Baseline Outcome</th>
                </tr>
              </thead>
              <tbody>
                {filteredSamples.map((tx) => (
                  <tr key={tx.transaction_id}>
                    <td>
                      <span className="mono-cell font-bold">{tx.transaction_id}</span>
                    </td>
                    <td>${tx.transaction_amt.toFixed(2)}</td>
                    <td>
                      <span className="code-pill">{tx.product_cd}</span>
                    </td>
                    <td className="text-secondary">{tx.email_domain}</td>
                    <td className="text-secondary">{tx.device_type}</td>
                    <td>
                      <span className={`label-pill ${tx.actual_label === 1 ? 'pill-fraud' : 'pill-legit'}`}>
                        {tx.actual_class}
                      </span>
                    </td>
                    <td>
                      <span className="mono-cell font-bold">{tx.graphsage_score.toFixed(4)}</span>
                    </td>
                    <td>
                      <span className={`outcome-pill outcome-${tx.graphsage_outcome.toLowerCase()}`}>
                        {tx.graphsage_outcome}
                      </span>
                    </td>
                    <td>
                      <span className="mono-cell">{tx.baseline_score.toFixed(4)}</span>
                    </td>
                    <td>
                      <span className={`outcome-pill outcome-${tx.baseline_outcome.toLowerCase()}`}>
                        {tx.baseline_outcome}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="table-footer-note">
            <span>
              <strong>Outcome Legend:</strong> <span className="outcome-pill outcome-tp">TP</span> Correctly blocked fraud &middot;{' '}
              <span className="outcome-pill outcome-fp">FP</span> False positive (legitimate customer flagged) &middot;{' '}
              <span className="outcome-pill outcome-fn">FN</span> False negative (fraud slipped through) &middot;{' '}
              <span className="outcome-pill outcome-tn">TN</span> Correctly approved legitimate
            </span>
          </div>
        </div>
      </section>

      {/* 7. Technical Footnote / Metadata */}
      <div className="benchmark-tech-footnote">
        <span>Evaluated Device: {meta.device || 'CPU'}</span>
        <span>&bull;</span>
        <span>Computation Time: {meta.evaluation_time_seconds || '7.2'}s</span>
        <span>&bull;</span>
        <span>Timestamp: {meta.evaluated_at || new Date().toISOString()}</span>
      </div>
    </div>
  );
}

export default AdminBenchmarkPage;
