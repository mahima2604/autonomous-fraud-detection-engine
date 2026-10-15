// PredictionExplanation.jsx
// Enterprise-grade Model Explainability & Feature Contribution Breakdown.

import { useEffect, useState } from 'react';
import { getTransactionExplanation } from '../../services/adminTransactionService';
import RiskBadge from '../fraud/RiskBadge';
import { formatDateTime } from '../../utils/formatters';
import './PredictionExplanation.css';

const DECISION_CLASS = {
  APPROVE: 'badge-low',
  REVIEW: 'badge-medium',
  BLOCK: 'badge-high',
};

function PredictionExplanation({ transactionId }) {
  const [explanation, setExplanation] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    getTransactionExplanation(transactionId)
      .then((data) => active && setExplanation(data))
      .catch((requestError) => active && setError(requestError.message || 'Unable to load model explanation.'));
    return () => {
      active = false;
    };
  }, [transactionId]);

  if (error) {
    return (
      <div className="prediction-explanation-state prediction-state-error" role="alert">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="8" x2="12" y2="12" />
          <line x1="12" y1="16" x2="12.01" y2="16" />
        </svg>
        <p>{error}</p>
      </div>
    );
  }

  if (!explanation) {
    return (
      <div className="prediction-explanation-state" role="status">
        <div className="spinner spinner-dark" />
        <p>Loading model weights, stored features, and attribution data...</p>
      </div>
    );
  }

  const features = Array.isArray(explanation.features) ? explanation.features : [];
  const contributions = Array.isArray(explanation.feature_contributions)
    ? explanation.feature_contributions
    : [];

  const formatValue = (value) => {
    if (value === null || value === undefined || value === '') return 'Not recorded';
    return typeof value === 'object' ? JSON.stringify(value) : String(value);
  };

  const score =
    explanation.risk_score === null || explanation.risk_score === undefined || explanation.risk_score === ''
      ? Number.NaN
      : Number(explanation.risk_score);
  const hasScore = Number.isFinite(score);
  const thresholds = explanation.thresholds || {};
  const review = explanation.review || {};

  return (
    <div className="prediction-explanation" aria-label={`Prediction explanation for transaction ${transactionId}`}>
      {/* 1. Prediction Overview & 2. Workflow State Grid */}
      <div className="prediction-top-grid">
        {/* Prediction Overview */}
        <div className="prediction-card">
          <div className="prediction-card-header">
            <span className="prediction-card-kicker">MODEL EVALUATION</span>
            <h4 className="prediction-card-title">Prediction Overview</h4>
          </div>

          <div className="prediction-data-grid">
            <div className="data-item">
              <span className="data-label">Transaction Reference</span>
              <strong className="data-val admin-txn-id">
                {explanation.transaction_id ? `TXN-${explanation.transaction_id}` : 'Not recorded'}
              </strong>
            </div>

            <div className="data-item">
              <span className="data-label">Model Architecture</span>
              <strong className="data-val">
                {formatValue(explanation.model_name)}
                <span className="data-subval">
                  {explanation.model_version ? `v${explanation.model_version}` : 'Version not recorded'}
                </span>
              </strong>
            </div>

            <div className="data-item">
              <span className="data-label">Evaluated Risk Score</span>
              <strong className="data-val font-tabular">
                {hasScore ? (
                  <span className="score-highlight">{score.toFixed(4)}</span>
                ) : (
                  'Unavailable'
                )}
              </strong>
            </div>

            <div className="data-item">
              <span className="data-label">Risk Category</span>
              <div className="data-val">
                {explanation.risk_category ? (
                  <RiskBadge riskLevel={explanation.risk_category} />
                ) : (
                  'Not recorded'
                )}
              </div>
            </div>

            <div className="data-item">
              <span className="data-label">Engine Decision</span>
              <div className="data-val">
                {explanation.model_decision ? (
                  <span className={`badge ${DECISION_CLASS[explanation.model_decision] || 'badge-neutral'}`}>
                    {explanation.model_decision}
                  </span>
                ) : (
                  'Not recorded'
                )}
              </div>
            </div>

            <div className="data-item">
              <span className="data-label">Applicable Rule / Threshold</span>
              <strong className="data-val rule-tag font-tabular">
                {formatValue(thresholds.applicable_rule)}
              </strong>
            </div>
          </div>
        </div>

        {/* Workflow & Administrative Review State */}
        <div className="prediction-card">
          <div className="prediction-card-header">
            <span className="prediction-card-kicker">WORKFLOW LIFECYCLE</span>
            <h4 className="prediction-card-title">Administrative Review State</h4>
          </div>

          <div className="prediction-data-grid">
            <div className="data-item">
              <span className="data-label">Checkout Status</span>
              <strong className="data-val">
                <span className="badge badge-neutral">{formatValue(review.transaction_status)}</span>
              </strong>
            </div>

            <div className="data-item">
              <span className="data-label">Review Decision</span>
              <strong className="data-val">
                {review.decision === 'APPROVE' ? (
                  <span className="badge badge-low">Approved by Admin</span>
                ) : review.decision === 'REJECT' ? (
                  <span className="badge badge-high">Rejected by Admin</span>
                ) : (
                  <span className="text-muted">{formatValue(review.decision || 'No manual decision recorded')}</span>
                )}
              </strong>
            </div>

            <div className="data-item">
              <span className="data-label">Decision Timestamp</span>
              <strong className="data-val font-tabular">
                {review.reviewed_at ? formatDateTime(review.reviewed_at) : 'Not reviewed'}
              </strong>
            </div>
          </div>

          <div className="prediction-workflow-notice">
            <p>
              Administrative approvals override automated review holds and allow the customer to proceed directly to payment.
            </p>
          </div>
        </div>
      </div>

      {/* 3. Model Input Features */}
      <div className="prediction-card">
        <div className="prediction-card-header">
          <div>
            <span className="prediction-card-kicker">PERSISTED REQUEST VALUES</span>
            <h4 className="prediction-card-title">Model Input Features ({features.length} Features)</h4>
          </div>
          <span className="card-header-note">Raw values ingested during checkout scoring</span>
        </div>

        {features.length ? (
          <div className="prediction-features-dense-grid">
            {features.map(({ name, value }) => {
              const isMissing = value === null || value === undefined || value === '';

              return (
                <div key={name} className="feature-cell">
                  <span className="feature-name" title={name}>
                    {name}
                  </span>
                  <span className={`feature-value ${isMissing ? 'feature-missing' : ''}`}>
                    {isMissing ? 'Missing / Null' : formatValue(value)}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="prediction-unavailable">
            Input feature values are not recorded or were pruned for this transaction.
          </div>
        )}
      </div>

      {/* 4. Feature Contributions */}
      <div className="prediction-card">
        <div className="prediction-card-header">
          <div>
            <span className="prediction-card-kicker">INTERPRETABILITY & ATTRIBUTION</span>
            <h4 className="prediction-card-title">Feature Contributions to Fraud Score</h4>
          </div>
          <span className="card-header-note">Linear log-odds contribution per active feature</span>
        </div>

        {explanation.attribution_available && contributions.length ? (
          <>
            <div className="attribution-table-wrap">
              <table className="attribution-table">
                <thead>
                  <tr>
                    <th>Feature Name</th>
                    <th>Contribution (Log-Odds)</th>
                    <th>Effect on Fraud Risk</th>
                  </tr>
                </thead>
                <tbody>
                  {contributions.map(({ name, contribution_log_odds, direction }) => {
                    const contribution =
                      contribution_log_odds === null || contribution_log_odds === undefined || contribution_log_odds === ''
                        ? Number.NaN
                        : Number(contribution_log_odds);
                    const isFiniteNum = Number.isFinite(contribution);
                    const isPositive = isFiniteNum && contribution > 0;
                    const isNegative = isFiniteNum && contribution < 0;

                    const dirText = String(direction || '').toLowerCase();
                    const isIncreasing = dirText.includes('increase') || isPositive;
                    const isDecreasing = dirText.includes('decrease') || isNegative;

                    return (
                      <tr key={name}>
                        <td className="attr-feat-name">
                          <strong>{name}</strong>
                        </td>
                        <td className="attr-feat-val font-tabular">
                          <span
                            className={`contribution-num ${
                              isPositive ? 'num-positive' : isNegative ? 'num-negative' : 'num-neutral'
                            }`}
                          >
                            {isFiniteNum ? `${contribution > 0 ? '+' : ''}${contribution.toFixed(6)}` : 'Unavailable'}
                          </span>
                        </td>
                        <td className="attr-feat-dir">
                          <span
                            className={`badge ${
                              isIncreasing ? 'badge-high' : isDecreasing ? 'badge-low' : 'badge-neutral'
                            }`}
                          >
                            {isIncreasing
                              ? 'Increases Risk'
                              : isDecreasing
                              ? 'Decreases Risk'
                              : formatValue(direction)}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {explanation.baseline_log_odds !== null &&
              explanation.baseline_log_odds !== undefined &&
              explanation.model_log_odds !== null &&
              explanation.model_log_odds !== undefined &&
              Number.isFinite(Number(explanation.baseline_log_odds)) &&
              Number.isFinite(Number(explanation.model_log_odds)) && (
                <div className="prediction-model-totals font-tabular">
                  <span>
                    Baseline Prior (Intercept):{' '}
                    <strong>{Number(explanation.baseline_log_odds).toFixed(6)}</strong>
                  </span>
                  <span className="dot-divider">&middot;</span>
                  <span>
                    Final Model Log-Odds:{' '}
                    <strong>{Number(explanation.model_log_odds).toFixed(6)}</strong>
                  </span>
                </div>
              )}
          </>
        ) : (
          <div className="prediction-unavailable">
            {explanation.attribution_note || 'Feature attribution data is unavailable for this stored prediction.'}
          </div>
        )}

        <div className="prediction-disclaimer">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="16" x2="12" y2="12" />
            <line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
          <span>
            Feature contributions reflect linear log-odds shifts in the model's decision boundary and represent model association rather than causal proof.
          </span>
        </div>
      </div>
    </div>
  );
}

export default PredictionExplanation;
