// FraudStatusCard.jsx
// Renders the outcome of a fraud check the frontend received from the
// backend. This component does
// not decide anything — it only displays { riskLevel, decision,
// reasonCodes } and reacts to `decision` for navigation copy.
import RiskBadge from './RiskBadge';

const COPY = {
  APPROVE: {
    heading: 'Transaction approved',
    body: 'Your transaction passed our security review. You can continue to payment.',
    tone: 'success',
  },
  REVIEW: {
    heading: 'Additional verification required',
    body: 'This transaction is waiting for administrator review. Payment remains unavailable until the review is complete.',
    tone: 'warning',
  },
  REJECT: {
    heading: 'Transaction rejected',
    body: 'An administrator rejected this transaction. It cannot proceed to payment.',
    tone: 'danger',
  },
  BLOCK: {
    heading: 'Transaction blocked',
    body: 'This transaction was flagged for security reasons and cannot proceed. No payment has been taken.',
    tone: 'danger',
  },
};

function FraudStatusCard({ result }) {
  const copy = COPY[result.decision] || COPY.REVIEW;

  return (
    <div className={`card card-padded fraud-status fraud-status-${copy.tone}`}>
      <div className="fraud-status-header">
        <h3>{copy.heading}</h3>
        <RiskBadge riskLevel={result.riskLevel} />
      </div>
      <p>{result.adminApproved
        ? 'An administrator approved this transaction. You can continue with the saved checkout.'
        : result.decision === 'REVIEW' && result.reviewReason
          ? `${result.reviewReason} The model score and model name are retained; payment is held for administrator review.`
          : copy.body}</p>
      <div className="fraud-status-meta">
        <span>Reference: {result.transactionId}</span>
      </div>
    </div>
  );
}

export default FraudStatusCard;
