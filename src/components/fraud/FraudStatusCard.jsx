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
  VERIFY: {
    heading: 'Additional verification required',
    body: 'Complete one fresh email verification for this checkout. We will recheck the existing assessment and available evidence before releasing payment.',
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
  const copy = result.decision === 'REVIEW' && result.riskLevel === 'HIGH'
    ? { ...COPY.REVIEW, heading: 'High risk transaction held for review', body: 'The score exceeded the high-risk threshold. Payment remains unavailable until an administrator reviews this transaction.' }
    : result.decision === 'VERIFY' && result.riskLevel === 'MEDIUM'
      ? COPY.VERIFY
      : result.decision === 'REVIEW' && result.riskLevel === 'MEDIUM'
        ? { ...COPY.REVIEW, body: 'This transaction remains held for review. No payment has been processed.' }
      : COPY[result.decision] || COPY.REVIEW;

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
