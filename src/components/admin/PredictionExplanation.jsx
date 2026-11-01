// PredictionExplanation.jsx
// Fraud Investigation & Administrative Decision Interface.

import { useEffect, useRef, useState } from 'react';
import {
  approveReview,
  getTransactionExplanation,
  reassessHighRisk,
  rejectReview,
} from '../../services/adminTransactionService';
import RiskBadge from '../fraud/RiskBadge';
import { formatCurrency, formatDateTime } from '../../utils/formatters';
import './PredictionExplanation.css';

const DECISION_CLASS = {
  APPROVE: 'badge-low',
  REVIEW: 'badge-medium',
  BLOCK: 'badge-high',
  VERIFY: 'badge-medium',
};

const STATUS_CLASS = {
  COMPLETED: 'badge-low',
  PAID: 'badge-low',
  REVIEW_APPROVED: 'badge-low',
  REVIEW: 'badge-medium',
  BLOCKED: 'badge-high',
  REJECTED: 'badge-high',
};

const STATUS_LABELS = {
  COMPLETED: 'Completed',
  PAID: 'Paid',
  REVIEW_APPROVED: 'Approved',
  REVIEW: 'Review Hold',
  BLOCKED: 'Blocked',
  REJECTED: 'Rejected',
};

const GRAPH_STATUS_LABELS = {
  VALIDATED: 'Validated',
  UNVALIDATED_INSUFFICIENT_DATA: 'Unvalidated: Insufficient Data',
  UNVALIDATED_TOPOLOGY_MISMATCH: 'Unvalidated: Topology Mismatch',
  UNVALIDATED_STORED_SCORE_MISMATCH: 'Unvalidated: Score Mismatch',
  UNVALIDATED_VALIDATION_ERROR: 'Unvalidated: Validation Error',
  UNVALIDATED: 'Unvalidated',
};

function PredictionExplanation({ transactionId, transactionSummary }) {
  const [explanation, setExplanation] = useState(null);
  const [error, setError] = useState('');
  const [reviewAction, setReviewAction] = useState(null);
  const [confirmAction, setConfirmAction] = useState(null);
  const [reviewFeedback, setReviewFeedback] = useState(null);
  const [reviewReason, setReviewReason] = useState('');
  const [acknowledgedIncompleteGraph, setAcknowledgedIncompleteGraph] = useState(false);
  const reviewActionLock = useRef(false);

  useEffect(() => {
    let active = true;
    getTransactionExplanation(transactionId)
      .then((data) => active && setExplanation(data))
      .catch((requestError) => active && setError(requestError.message || 'Unable to load transaction investigation details.'));
    return () => {
      active = false;
    };
  }, [transactionId]);

  async function handleReviewDecision(decision) {
    if (reviewActionLock.current) return;
    reviewActionLock.current = true;
    setReviewAction(decision);
    setConfirmAction(null);
    setReviewFeedback(null);

    try {
      const result = decision === 'APPROVE'
        ? await approveReview(transactionId, reviewReason, acknowledgedIncompleteGraph)
        : await rejectReview(transactionId, reviewReason);

      setExplanation((current) => current && ({
        ...current,
        operational_decision: decision === 'APPROVE' ? 'APPROVE' : 'REJECT',
        review: {
          ...current.review,
          transaction_status: result.status,
          decision: result.review_decision,
          reviewed_at: result.reviewed_at,
          reason: reviewReason,
        },
      }));

      try {
        const refreshed = await getTransactionExplanation(transactionId);
        setExplanation(refreshed);
        setReviewFeedback({
          type: 'success',
          message: `Transaction TXN-${transactionId} was successfully ${decision === 'APPROVE' ? 'approved' : 'rejected'}. Customer status updated.`,
        });
      } catch {
        setReviewFeedback({
          type: 'warning',
          message: `Decision saved by the backend. Persisted decision is shown above.`,
        });
      }
    } catch (actionError) {
      setReviewFeedback({
        type: 'error',
        message: actionError.message || 'Unable to save review decision. Please try again.',
      });
    } finally {
      reviewActionLock.current = false;
      setReviewAction(null);
    }
  }

  async function handleHighRiskReassessment() {
    if (reviewActionLock.current) return;
    reviewActionLock.current = true;
    setReviewAction('REASSESS');
    setReviewFeedback(null);
    try {
      const result = await reassessHighRisk(transactionId);
      setExplanation((current) => current && ({ ...current, risk_reassessment: result.risk_reassessment }));
      const refreshed = await getTransactionExplanation(transactionId);
      setExplanation(refreshed);
      setReviewFeedback({
        type: 'success',
        message: `Required checks recorded. Graph evidence: ${result.risk_reassessment?.graph_relationship_check?.status || 'recorded'}; score outcome remains ${result.risk_reassessment?.score_based_decision || 'BLOCK'}.`,
      });
    } catch (actionError) {
      setReviewFeedback({
        type: 'error',
        message: actionError.message || 'Unable to complete reassessment checks. The transaction remains on hold.',
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
        <p>Loading transaction investigation details...</p>
      </div>
    );
  }

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
  const assessment = explanation.risk_reassessment || review.risk_reassessment;
  const checkoutEvidence = explanation.checkout_evidence || {};
  const mediumEvidenceReview = assessment?.medium_verification?.status === 'HELD_FOR_ADMIN_REVIEW';
  const currentHighRisk = explanation.risk_category === 'HIGH' || explanation.automated_score_decision === 'BLOCK';
  const highRisk = currentHighRisk || explanation.recorded_risk_category === 'HIGH' || explanation.recorded_score_based_decision === 'BLOCK';
  const evidenceReview = highRisk || mediumEvidenceReview;

  const canDecideReview =
    review.transaction_status === 'REVIEW' &&
    !review.decision &&
    (explanation.model_decision === 'REVIEW' || mediumEvidenceReview);

  const assessmentReady = assessment?.ready_for_admin_decision === true;
  const assessmentHistory = assessment?.address_account_checks?.account_history;
  const graphCheck = assessment?.graph_relationship_check;
  const graphEvidenceIncomplete = graphCheck?.status === 'INCOMPLETE_EVIDENCE';

  // 5 Canonical features
  const featureMap = new Map((explanation.features || []).map((f) => [f.name, f.value]));
  const canonicalFeatures = [
    { name: 'TransactionAmt', label: 'TransactionAmt', value: featureMap.get('TransactionAmt') ?? transactionSummary?.amount },
    { name: 'ProductCD', label: 'ProductCD', value: featureMap.get('ProductCD') ?? 'UNKNOWN' },
    { name: 'P_emaildomain', label: 'P_emaildomain', value: featureMap.get('P_emaildomain') ?? 'UNKNOWN' },
    { name: 'DeviceType', label: 'DeviceType', value: featureMap.get('DeviceType') ?? 'UNKNOWN' },
    { name: 'DeviceInfo', label: 'DeviceInfo', value: featureMap.get('DeviceInfo') ?? 'UNKNOWN' },
  ];

  // Derive compact header items
  const customerName = transactionSummary?.customer?.name || (transactionSummary?.customer?.email ?? null);
  const transactionAmount =
    transactionSummary?.amount ?? featureMap.get('TransactionAmt') ?? 0;
  const effectiveStatus = review.decision === 'APPROVE' ? 'REVIEW_APPROVED' : review.decision === 'REJECT' ? 'REJECTED' : (review.transaction_status || transactionSummary?.status || 'REVIEW');

  // Applicable reasons for "Why this transaction needs attention"
  const attentionReasons = [];
  const scoreDecision = explanation.automated_score_decision || explanation.score_based_decision;
  if (explanation.historical_classification_notice) {
    attentionReasons.push(explanation.historical_classification_notice);
  } else if (scoreDecision === 'BLOCK') {
    attentionReasons.push(
      `Administrator review is required because the score-based outcome is BLOCK (${hasScore ? score.toFixed(4) : 'score unavailable'} exceeds the ${Number(thresholds.block ?? 0.7).toFixed(2)} block threshold). The operational decision remains held in REVIEW until an administrator records a decision.`
    );
  } else if (scoreDecision === 'REVIEW') {
    attentionReasons.push(
      `Administrator review is required because the score-based outcome is REVIEW (${hasScore ? score.toFixed(4) : 'score unavailable'} is in the medium-risk band). The operational decision remains held in REVIEW until an administrator records a decision.`
    );
  } else if (scoreDecision === 'APPROVE') {
    attentionReasons.push(
      `Administrator review is required for all new checkout transactions before order release (score-based outcome is APPROVE with score ${hasScore ? score.toFixed(4) : 'low'}).`
    );
  } else if (explanation.operational_decision === 'REVIEW') {
    attentionReasons.push(
      explanation.manual_review_reason || 'Transaction is held for administrator review by an operational safeguard.'
    );
  }

  if (featureMap.get('ProductCD') === 'UNKNOWN') {
    attentionReasons.push(
      'ProductCD is UNKNOWN because the checkout does not have a single backend-validated ProductCD code.'
    );
  }

  if (featureMap.get('DeviceInfo') === 'UNKNOWN') {
    attentionReasons.push(
      'DeviceInfo is unavailable, so the expected device relationship edge cannot be validated.'
    );
  }

  if (mediumEvidenceReview) {
    attentionReasons.push(
      'Contextual matching-address delivery outcome history was recorded, requiring administrator review.'
    );
  }

  const canSubmitApprove =
    !reviewAction &&
    reviewReason.trim().length > 0 &&
    (!evidenceReview || (assessmentReady && (!graphEvidenceIncomplete || acknowledgedIncompleteGraph)));

  const canSubmitReject =
    !reviewAction &&
    reviewReason.trim().length > 0 &&
    (!evidenceReview || assessmentReady);

  return (
    <div className="prediction-explanation">
      {/* A. Compact Transaction Header */}
      <div className="investigation-header">
        <div className="header-meta-group">
          <div className="header-kicker-row">
            <span className="investigation-kicker">Fraud Investigation</span>
            <span className="dot-divider">&middot;</span>
            <span className="investigation-ref font-tabular">TXN-{transactionId}</span>
          </div>
          <h1 className="investigation-title">
            TXN-{transactionId}
            {customerName && <span className="header-customer-name"> &middot; {customerName}</span>}
          </h1>
        </div>

        <div className="header-right-meta">
          <div className="header-amount-box font-tabular">
            <span className="amount-label">Amount:</span>
            <strong className="header-amount-val">{formatCurrency(transactionAmount)}</strong>
          </div>
          <div className="header-status-box">
            <span className={`badge ${STATUS_CLASS[effectiveStatus] || 'badge-neutral'}`}>
              {STATUS_LABELS[effectiveStatus] || effectiveStatus}
            </span>
          </div>
        </div>
      </div>

      {/* B. Risk Overview (4 Items) */}
      <div className="fraud-risk-overview-grid">
        {/* 1. Risk Score */}
        <div className="risk-overview-card">
          <span className="risk-overview-label">Risk Score</span>
          <div className="risk-overview-val font-tabular">
            {hasScore ? score.toFixed(4) : 'Unavailable'}
          </div>
          <span className="risk-overview-subtext">
            LOW &le; {thresholds.review == null ? 'Unavailable' : Number(thresholds.review).toFixed(2)}
            {' '}&middot; MEDIUM &gt; {thresholds.review == null ? 'Unavailable' : Number(thresholds.review).toFixed(2)}
            {' '}and &le; {thresholds.block == null ? 'Unavailable' : Number(thresholds.block).toFixed(2)}
            {' '}&middot; HIGH &gt; {thresholds.block == null ? 'Unavailable' : Number(thresholds.block).toFixed(2)}
          </span>
        </div>

        {/* 2. Risk Category */}
        <div className="risk-overview-card">
          <span className="risk-overview-label">Risk Category</span>
          <div className="risk-overview-val">
            {explanation.risk_category ? (
              <RiskBadge riskLevel={explanation.risk_category} />
            ) : (
              <span className="text-muted">Not recorded</span>
            )}
          </div>
          <span className="risk-overview-subtext">Evaluated risk category</span>
        </div>

        {/* 3. Model Used */}
        <div className="risk-overview-card">
          <span className="risk-overview-label">Scoring Model</span>
          <div className="risk-overview-val model-val-text">
            {explanation.model_name || 'GraphSAGE'}
            {explanation.model_version && <span className="model-version-tag">v{explanation.model_version}</span>}
          </div>
          <span className="risk-overview-subtext">
            {isGnn ? 'Graph Neural Network' : 'Linear Baseline'}
          </span>
        </div>

        {/* 4. Operational vs Score Outcome */}
        <div className="risk-overview-card">
          <span className="risk-overview-label">Operational &amp; Score Status</span>
          <div className="risk-decisions-wrap">
            <div className="decision-pill-item">
              <span className="decision-micro-label">Operational:</span>
              <span className={`badge ${DECISION_CLASS[explanation.operational_decision] || 'badge-neutral'}`}>
                {explanation.operational_decision || 'REVIEW'}
              </span>
            </div>
            <div className="decision-pill-item">
              <span className="decision-micro-label">Score Outcome:</span>
              <span className={`badge ${DECISION_CLASS[explanation.automated_score_decision || explanation.score_based_decision] || 'badge-neutral'}`}>
                {explanation.automated_score_decision || explanation.score_based_decision || 'BLOCK'}
              </span>
            </div>
          </div>
          <span className="risk-overview-subtext">
            {explanation.operational_decision === 'REVIEW' ? 'Operationally held for administrator review.' : 'Operational decision follows the recorded checkout workflow.'}
          </span>
        </div>
      </div>

      {/* C. Why This Transaction Needs Attention */}
      {attentionReasons.length > 0 && (
        <div className="attention-panel" role="alert">
          <div className="attention-panel-header">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="12" />
              <line x1="12" y1="16" x2="12.01" y2="16" />
            </svg>
            <strong>Why This Transaction Needs Attention</strong>
          </div>
          <ul className="attention-list">
            {attentionReasons.map((reason, idx) => (
              <li key={idx}>{reason}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Main Investigation Split: Features & Graph (Left) vs Administrative Review (Right) */}
      <div className="investigation-main-grid">
        {/* Left Column: Model Features & Graph Context */}
        <div className="investigation-col">
          {/* D. Transaction Features */}
          <div className="investigation-card">
            <div className="investigation-card-header">
              <h3 className="investigation-card-title">Model Input Features</h3>
              <span className="investigation-card-meta">5 core features evaluated</span>
            </div>

            <div className="table-responsive">
              <table className="investigation-table">
                <thead>
                  <tr>
                    <th style={{ width: '42%' }}>Feature</th>
                    <th style={{ width: '58%' }}>Value</th>
                  </tr>
                </thead>
                <tbody>
                  {canonicalFeatures.map(({ name, label, value }) => {
                    const isUnknown = value === 'UNKNOWN' || value === null || value === undefined || value === '';
                    let displayVal = value;
                    if (name === 'TransactionAmt') {
                      displayVal = typeof value === 'number' ? formatCurrency(value) : (value ? `$${value}` : 'UNKNOWN');
                    } else if (isUnknown) {
                      displayVal = 'UNKNOWN';
                    }

                    return (
                      <tr key={name}>
                        <td className="feat-name-cell font-mono">{label}</td>
                        <td className="feat-val-cell">
                          {isUnknown ? (
                            <span className="unknown-pill">UNKNOWN</span>
                          ) : (
                            <span className="feat-val-text font-tabular">{String(displayVal)}</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="table-footnote">
              <strong>Note:</strong> <code>UNKNOWN</code> indicates the value is unavailable or untrusted for the relevant feature; it must not be treated as a verified identity.
            </p>
          </div>

          <div className="investigation-card">
            <div className="investigation-card-header">
              <h3 className="investigation-card-title">Checkout Evidence &amp; Safeguards</h3>
              <span className="investigation-card-meta">Stored validation evidence</span>
            </div>
            <div className="graph-context-grid">
              <div className="graph-context-item">
                <span className="graph-item-label">Products</span>
                <strong className="graph-item-val">
                  {checkoutEvidence.products?.length
                    ? checkoutEvidence.products.map((item) => `${item.name || item.product_id} × ${item.quantity}`).join(', ')
                    : 'Unavailable'}
                </strong>
              </div>
              <div className="graph-context-item">
                <span className="graph-item-label">ProductCD Validation</span>
                <strong className="graph-item-val">
                  {checkoutEvidence.product_cd || 'UNKNOWN'} · {checkoutEvidence.product_cd_validated ? 'Validated' : 'Unavailable or unverified'}
                </strong>
              </div>
              <div className="graph-context-item">
                <span className="graph-item-label">Account Email OTP</span>
                <strong className="graph-item-val">{checkoutEvidence.account_email_otp_verified ? 'Verified' : 'Not verified'}</strong>
              </div>
              <div className="graph-context-item">
                <span className="graph-item-label">Delivery Address</span>
                <strong className="graph-item-val">
                  {checkoutEvidence.address_confirmed ? 'Customer confirmed' : 'Not confirmed'} · {checkoutEvidence.address_validated ? 'Format validated' : 'Format unavailable or invalid'}
                </strong>
              </div>
              <div className="graph-context-item">
                <span className="graph-item-label">Order OTP</span>
                <strong className="graph-item-val">
                  {checkoutEvidence.order_otp_status || 'NOT_STARTED'}
                  {checkoutEvidence.order_otp_verified_at ? ` · ${formatDateTime(checkoutEvidence.order_otp_verified_at)}` : ''}
                </strong>
              </div>
              <div className="graph-context-item">
                <span className="graph-item-label">Device Evidence</span>
                <strong className="graph-item-val">
                  Type: {checkoutEvidence.device_type || 'UNKNOWN'} · Info: {checkoutEvidence.device_info || 'UNKNOWN'}
                </strong>
              </div>
            </div>
            {checkoutEvidence.product_cd_warning && (
              <p className="graph-neutral-notice">{checkoutEvidence.product_cd_warning}</p>
            )}
          </div>

          {/* E. Graph Context */}
          {isGnn && (
            <div className="investigation-card">
              <div className="investigation-card-header">
                <h3 className="investigation-card-title">Graph Context</h3>
                <span className="investigation-card-meta">Reconstructed from saved features and earlier transactions</span>
              </div>

              <div className="graph-context-grid">
                <div className="graph-context-item">
                  <span className="graph-item-label">Training Edge Types</span>
                  <strong className="graph-item-val font-mono">
                    {explanation.graph_context?.training_topology || 'Unavailable'}
                  </strong>
                </div>

                <div className="graph-context-item">
                  <span className="graph-item-label">Live Edge Types</span>
                  <strong className="graph-item-val font-mono">
                    {explanation.graph_context?.live_topology || explanation.graph_context?.edge_type || 'Unavailable'}
                  </strong>
                </div>

                <div className="graph-context-item">
                  <span className="graph-item-label">Connected Historical Nodes</span>
                  <strong className="graph-item-val font-tabular">
                    {explanation.graph_context?.connected_neighbors !== null && explanation.graph_context?.connected_neighbors !== undefined
                      ? `${explanation.graph_context.connected_neighbors} historical transaction(s)`
                      : 'Unavailable'}
                  </strong>
                </div>

                <div className="graph-context-item">
                  <span className="graph-item-label">Topology Validation Status</span>
                  <div className="graph-item-val">
                    <span className={`badge ${explanation.graph_context?.topology_validation_status === 'VALIDATED' ? 'badge-low' : 'badge-neutral'}`}>
                      {GRAPH_STATUS_LABELS[explanation.graph_context?.topology_validation_status]
                        || explanation.graph_context?.topology_validation_status
                        || 'Unvalidated'}
                    </span>
                  </div>
                </div>
              </div>

              {explanation.graph_context?.topology_validation_status !== 'VALIDATED' && (
                <div className="graph-neutral-notice">
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="12" cy="12" r="10" />
                    <line x1="12" y1="8" x2="12" y2="12" />
                    <line x1="12" y1="16" x2="12.01" y2="16" />
                  </svg>
                  <span>{explanation.graph_context?.topology_note || 'Graph validation details are unavailable.'}</span>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Right Column: F. Administrative Review */}
        <div className="investigation-col">
          <div className="investigation-card review-card">
            <div className="investigation-card-header">
              <h3 className="investigation-card-title">Administrative Review</h3>
              <span className={`badge ${STATUS_CLASS[effectiveStatus] || 'badge-neutral'}`}>
                {STATUS_LABELS[effectiveStatus] || effectiveStatus}
              </span>
            </div>

            {/* Review Status & Audit Details */}
            <div className="review-meta-grid">
              <div className="review-meta-item">
                <span className="review-meta-label">Review Status</span>
                <strong className="review-meta-val">
                  {review.decision === 'APPROVE' ? (
                    <span className="text-green">Approved by Admin</span>
                  ) : review.decision === 'REJECT' ? (
                    <span className="text-red">Rejected by Admin</span>
                  ) : canDecideReview ? (
                    <span className="text-amber">Awaiting Admin Decision</span>
                  ) : (
                    formatValue(review.decision || review.transaction_status)
                  )}
                </strong>
              </div>

              <div className="review-meta-item">
                <span className="review-meta-label">Reviewer</span>
                <strong className="review-meta-val">
                  {review.reviewed_by_admin_id ? `Administrator #${review.reviewed_by_admin_id}` : 'No manual reviewer'}
                </strong>
              </div>

              <div className="review-meta-item">
                <span className="review-meta-label">Decision Timestamp</span>
                <strong className="review-meta-val font-tabular">
                  {review.reviewed_at ? formatDateTime(review.reviewed_at) : 'Not reviewed'}
                </strong>
              </div>

              {review.reason && (
                <div className="review-meta-item full-width">
                  <span className="review-meta-label">Recorded Decision Reason</span>
                  <p className="review-reason-text">{review.reason}</p>
                </div>
              )}
            </div>

            {/* Controls for Pending Review */}
            {canDecideReview ? (
              <div className="review-action-section">
                {highRisk && (
                  <div className="high-risk-checks-block">
                    <p className="checks-instruction">
                      High-risk score is held on review. Complete required address and graph checks before recording a decision.
                    </p>
                    <button
                      type="button"
                      className="btn btn-secondary btn-sm"
                      onClick={handleHighRiskReassessment}
                      disabled={Boolean(reviewAction)}
                    >
                      {reviewAction === 'REASSESS'
                        ? 'Running checks...'
                        : assessmentReady
                        ? 'Re-run address and graph checks'
                        : 'Run required address and graph checks'}
                    </button>

                    {assessmentReady && (
                      <div className="assessment-summary-callout">
                        <div>&bull; <strong>Orders in 24h:</strong> {assessmentHistory?.customer_orders_last_24_hours ?? 'Unavailable'}</div>
                        <div>&bull; <strong>Accounts at address in 30d:</strong> {assessmentHistory?.other_accounts_with_matching_checkout_address_last_30_days ?? 'Unavailable'}</div>
                        <div>&bull; <strong>Graph check:</strong> {graphCheck?.topology_validation_status || graphCheck?.status || 'Unavailable'}</div>
                      </div>
                    )}

                    {assessmentReady && graphEvidenceIncomplete && (
                      <label className="ack-checkbox-label" htmlFor="ack-incomplete-graph">
                        <input
                          id="ack-incomplete-graph"
                          type="checkbox"
                          checked={acknowledgedIncompleteGraph}
                          onChange={(e) => setAcknowledgedIncompleteGraph(e.target.checked)}
                        />
                        <span>I acknowledge that required graph topology evidence is incomplete.</span>
                      </label>
                    )}
                  </div>
                )}

                {mediumEvidenceReview && (
                  <div className="high-risk-checks-block">
                    <p className="checks-instruction">
                      {assessment?.medium_verification?.decision_reason || 'Contextual address delivery history recorded.'}
                    </p>
                    {graphEvidenceIncomplete && (
                      <label className="ack-checkbox-label" htmlFor="ack-incomplete-graph-medium">
                        <input
                          id="ack-incomplete-graph-medium"
                          type="checkbox"
                          checked={acknowledgedIncompleteGraph}
                          onChange={(e) => setAcknowledgedIncompleteGraph(e.target.checked)}
                        />
                        <span>I acknowledge that graph evidence is incomplete.</span>
                      </label>
                    )}
                  </div>
                )}

                <div className="review-input-group">
                  <label htmlFor="admin-review-reason" className="review-label">
                    Administrator decision reason (required):
                  </label>
                  <textarea
                    id="admin-review-reason"
                    rows="3"
                    maxLength="1000"
                    className="admin-textarea"
                    value={reviewReason}
                    onChange={(e) => setReviewReason(e.target.value)}
                    placeholder="Record the evidence and rationale for this decision..."
                  />
                </div>

                {confirmAction ? (
                  <div className="review-confirm-box">
                    <p>
                      Are you sure you want to <strong>{confirmAction === 'APPROVE' ? 'APPROVE' : 'REJECT'}</strong> this transaction?
                    </p>
                    <div className="confirm-btn-row">
                      <button
                        type="button"
                        className={confirmAction === 'APPROVE' ? 'btn-confirm-approve' : 'btn-confirm-reject'}
                        onClick={() => handleReviewDecision(confirmAction)}
                        disabled={Boolean(reviewAction)}
                      >
                        {reviewAction ? 'Submitting...' : `Confirm ${confirmAction === 'APPROVE' ? 'Approval' : 'Rejection'}`}
                      </button>
                      <button
                        type="button"
                        className="btn btn-secondary btn-sm"
                        onClick={() => setConfirmAction(null)}
                        disabled={Boolean(reviewAction)}
                      >
                        Cancel
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="review-button-row">
                    <button
                      type="button"
                      className="btn-review-approve"
                      onClick={() => setConfirmAction('APPROVE')}
                      disabled={!canSubmitApprove}
                      title={
                        evidenceReview && !assessmentReady
                          ? 'Run required checks before approving'
                          : evidenceReview && !reviewReason.trim()
                          ? 'Enter a decision reason before approving'
                          : evidenceReview && graphEvidenceIncomplete && !acknowledgedIncompleteGraph
                          ? 'Acknowledge incomplete graph evidence before approving'
                          : 'Approve transaction and allow payment'
                      }
                    >
                      Approve Transaction
                    </button>
                    <button
                      type="button"
                      className="btn-review-reject"
                      onClick={() => setConfirmAction('REJECT')}
                      disabled={!canSubmitReject}
                      title={
                        evidenceReview && !assessmentReady
                          ? 'Run required checks before rejecting'
                          : evidenceReview && !reviewReason.trim()
                          ? 'Enter a decision reason before rejecting'
                          : 'Reject transaction due to fraud suspicion'
                      }
                    >
                      Reject Transaction
                    </button>
                  </div>
                )}
              </div>
            ) : null}

            {reviewFeedback && (
              <div
                className={`prediction-review-feedback prediction-review-${reviewFeedback.type}`}
                role={reviewFeedback.type === 'error' ? 'alert' : 'status'}
              >
                {reviewFeedback.message}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* G. Expandable Technical Details & Audit Traceability */}
      <details className="investigation-tech-details">
        <summary>Technical Details &amp; Audit Traceability</summary>
        <div className="tech-details-content">
          <div className="tech-detail-row">
            <span>Score Reproduction:</span>
            <strong>
              {explanation.score_reproduced ? 'Verified Match (±0.0001)' : 'Score reproduction check unavailable'}
            </strong>
          </div>
          <div className="tech-detail-row">
            <span>Applicable Rule / Threshold:</span>
            <span className="font-mono">{thresholds.applicable_rule || 'Standard review threshold'}</span>
          </div>
          <div className="tech-detail-row">
            <span>Original Operational Decision:</span>
            <span>{explanation.original_operational_decision || explanation.model_decision || 'Not recorded'}</span>
          </div>
          {explanation.reviewed_at && (
            <div className="tech-detail-row">
              <span>Audit Review Timestamp:</span>
              <span>{formatDateTime(explanation.reviewed_at)}</span>
            </div>
          )}
        </div>
      </details>
    </div>
  );
}

export default PredictionExplanation;
