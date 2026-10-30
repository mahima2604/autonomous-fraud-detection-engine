// PredictionExplanation.jsx
// Enterprise-grade Model Explainability & Feature Contribution Breakdown.

import { useEffect, useRef, useState } from 'react';
import {
  approveReview,
  getTransactionExplanation,
  rejectReview,
} from '../../services/adminTransactionService';
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
  const [reviewAction, setReviewAction] = useState(null);
  const [reviewFeedback, setReviewFeedback] = useState(null);
  const reviewActionLock = useRef(false);

  useEffect(() => {
    let active = true;
    getTransactionExplanation(transactionId)
      .then((data) => active && setExplanation(data))
      .catch((requestError) => active && setError(requestError.message || 'Unable to load model explanation.'));
    return () => {
      active = false;
    };
  }, [transactionId]);

  async function handleReviewDecision(decision) {
    if (reviewActionLock.current) return;
    reviewActionLock.current = true;
    setReviewAction(decision);
    setReviewFeedback(null);

    try {
      const result = decision === 'APPROVE'
        ? await approveReview(transactionId)
        : await rejectReview(transactionId);

      // Reflect the persisted action response immediately, even if the follow-up
      // explanation refresh is temporarily unavailable.
      setExplanation((current) => current && ({
        ...current,
        review: {
          ...current.review,
          transaction_status: result.status,
          decision: result.review_decision,
          reviewed_at: result.reviewed_at,
        },
      }));

      try {
        const refreshed = await getTransactionExplanation(transactionId);
        setExplanation(refreshed);
        setReviewFeedback({
          type: 'success',
          message: `Transaction ${decision === 'APPROVE' ? 'approved' : 'rejected'}; persisted review details refreshed.`,
        });
      } catch {
        setReviewFeedback({
          type: 'warning',
          message: `Decision saved by the backend, but the analysis details could not be refreshed. The saved decision is shown above.`,
        });
      }
    } catch (actionError) {
      setReviewFeedback({
        type: 'error',
        message: actionError.message || 'Unable to save the review decision. Please try again.',
      });
    } finally {
      reviewActionLock.current = false;
      setReviewAction(null);
    }
  }

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

  const isGnn =
    String(explanation.model_name || '').toLowerCase().includes('graphsage') ||
    String(explanation.model_name || '').toLowerCase().includes('gnn');

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
  const canDecideReview = review.transaction_status === 'REVIEW'
    && !review.decision
    && explanation.model_decision === 'REVIEW';

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
              <span className="data-label">Stored Model Score</span>
              <strong className="data-val font-tabular">
                {hasScore ? (
                  <span className="score-highlight">{score.toFixed(4)}</span>
                ) : (
                  'Unavailable'
                )}
              </strong>
            </div>

            <div className="data-item">
              <span className="data-label">Score-Based Outcome</span>
              <div className="data-val">
                {explanation.automated_score_decision ? (
                  <span className={`badge ${DECISION_CLASS[explanation.automated_score_decision] || 'badge-neutral'}`}>
                    {explanation.automated_score_decision}
                  </span>
                ) : (
                  'Not recorded'
                )}
              </div>
            </div>

            <div className="data-item">
              <span className="data-label">Operational Decision</span>
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
              <span className="data-label">Applicable Rule / Threshold</span>
              <strong className="data-val rule-tag font-tabular">
                {formatValue(thresholds.applicable_rule)}
              </strong>
            </div>

            <div className="data-item">
              <span className="data-label">Score Reproduction</span>
              <strong className="data-val">
                {explanation.score_reproduced ? (
                  <span className="badge badge-low" title={explanation.reproduction_note || 'Score successfully reproduced'}>
                    Verified Match (&plusmn;0.0001)
                  </span>
                ) : (
                  <span className="badge badge-neutral" title={explanation.reproduction_note || 'Score not reproduced'}>
                    {explanation.recomputed_risk_score !== null && explanation.recomputed_risk_score !== undefined
                      ? `Mismatch (${Number(explanation.recomputed_risk_score).toFixed(4)})`
                      : 'Unavailable'}
                  </span>
                )}
              </strong>
            </div>
          </div>
          {explanation.manual_review_reason && (
            <div className="prediction-workflow-notice" role="status">
              <p>
                <strong>Operational Review Safeguard Active:</strong> {explanation.manual_review_reason}{' '}
                Score-based outcome is {formatValue(explanation.automated_score_decision)}, but operational decision is held at {formatValue(explanation.model_decision)} pending administrator review.
              </p>
            </div>
          )}
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

          {canDecideReview && (
            <div className="prediction-review-actions" aria-label="Review decision actions">
              <p>This transaction is awaiting an administrator decision.</p>
              <div className="prediction-review-buttons">
                <button
                  type="button"
                  className="btn-review-approve"
                  onClick={() => handleReviewDecision('APPROVE')}
                  disabled={Boolean(reviewAction)}
                >
                  {reviewAction === 'APPROVE' ? 'Approving...' : 'Approve'}
                </button>
                <button
                  type="button"
                  className="btn-review-reject"
                  onClick={() => handleReviewDecision('REJECT')}
                  disabled={Boolean(reviewAction)}
                >
                  {reviewAction === 'REJECT' ? 'Rejecting...' : 'Reject'}
                </button>
              </div>
            </div>
          )}

          {reviewFeedback && (
            <div className={`prediction-review-feedback prediction-review-${reviewFeedback.type}`} role={reviewFeedback.type === 'error' ? 'alert' : 'status'}>
              {reviewFeedback.message}
            </div>
          )}

          <div className="prediction-workflow-notice">
            <p>
              Approval changes the review status and allows the existing checkout workflow to continue. Any resulting payment remains simulated; rejection prevents order creation. The fraud score and model decision are not changed by this administrative action.
            </p>
          </div>
        </div>
      </div>

      {/* Graph Neural Network Context (if GNN prediction) */}
      {(isGnn || explanation.graph_context) && (
        <div className="prediction-card">
          <div className="prediction-card-header">
            <div>
              <span className="prediction-card-kicker">GRAPH NEURAL NETWORK CONTEXT</span>
              <h4 className="prediction-card-title">Graph Topology & Relationships</h4>
            </div>
            <span className="card-header-note">Causal transaction graph evaluated by GraphSAGE</span>
          </div>

          <div className="prediction-data-grid">
            <div className="data-item">
              <span className="data-label">Live Graph Edges</span>
              <strong className="data-val">
                {formatValue(explanation.graph_context?.live_topology || explanation.graph_context?.edge_type || 'Unavailable')}
              </strong>
            </div>

            <div className="data-item">
              <span className="data-label">Training Graph Edges</span>
              <strong className="data-val">
                {formatValue(explanation.graph_context?.training_topology || 'Unavailable')}
              </strong>
            </div>

            <div className="data-item">
              <span className="data-label">Connected Historical Nodes</span>
              <strong className="data-val font-tabular">
                {explanation.graph_context?.connected_neighbors !== null && explanation.graph_context?.connected_neighbors !== undefined
                  ? `${explanation.graph_context.connected_neighbors} historical transaction(s)`
                  : 'Unavailable'}
              </strong>
            </div>

            <div className="data-item">
              <span className="data-label">Graph Topology Validation</span>
              <div className="data-val">
                <span className={`badge ${explanation.graph_context?.topology_validation_status === 'VALIDATED' ? 'badge-low' : 'badge-medium'}`}>
                  {explanation.graph_context?.topology_validation_status === 'VALIDATED'
                    ? 'Validated Topology'
                    : explanation.graph_context?.topology_validation_status === 'UNVALIDATED_INSUFFICIENT_DATA'
                      ? 'Unvalidated: Insufficient Data'
                      : explanation.graph_context?.topology_validation_status === 'UNVALIDATED_STORED_SCORE_MISMATCH'
                        ? 'Unvalidated: Score Mismatch'
                      : 'Unvalidated'}
                </span>
              </div>
            </div>
          </div>

          <div className="prediction-workflow-notice" role="status">
            <p>
              <strong>Graph validation:</strong> {explanation.graph_context?.topology_note || 'Graph context is unavailable.'} Linear log-odds feature attribution is mathematically inapplicable to GraphSAGE and is hidden.
            </p>
          </div>
        </div>
      )}

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

      {/* 4. Feature Contributions (Conditionally rendered for non-GNN models) */}
      {!isGnn && (
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
              {explanation.calibration_notice
                ? explanation.calibration_notice
                : "Feature contributions reflect linear log-odds shifts in the model's decision boundary. Stored score is uncalibrated for storefront transactions."}
            </span>
          </div>
        </div>
      )}
    </div>
  );
}

export default PredictionExplanation;
