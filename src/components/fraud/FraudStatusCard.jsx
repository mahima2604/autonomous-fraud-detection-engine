// FraudStatusCard.jsx
// Renders the outcome of a fraud check the frontend received from the
// backend (or, currently, the mock fraud service). This component does
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
    body: 'We need a bit more confirmation before this transaction can proceed. Please review the details below.',
    tone: 'warning',
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
      <p>{copy.body}</p>
      <div className="fraud-status-meta">
        <span>Reference: {result.transactionId}</span>
      </div>
      {result.isMock && (
        <p className="mock-note">
          Mock fraud response for development — not a real fraud model output.
        </p>
      )}
    </div>
  );
}

export default FraudStatusCard;
