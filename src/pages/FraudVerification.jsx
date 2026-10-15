// FraudVerification.jsx
// Sends the pending transaction to the authenticated backend fraud service.
// This page renders the returned assessment and contains no scoring logic.
import { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getPendingCheckout, savePendingCheckout } from '../services/checkoutService';
import { analyzeTransaction, getTransactionStatus } from '../services/fraudService';
import OrderSummary from '../components/checkout/OrderSummary';
import FraudStatusCard from '../components/fraud/FraudStatusCard';
import LoadingSpinner from '../components/common/LoadingSpinner';
import EmptyState from '../components/common/EmptyState';

function FraudVerification() {
  const navigate = useNavigate();
  const { logout, user } = useAuth();
  const pending = getPendingCheckout(user?.id);

  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshingStatus, setRefreshingStatus] = useState(false);
  const [statusError, setStatusError] = useState('');
  const [statusNotice, setStatusNotice] = useState('');

  async function refreshStatus(quiet = false, isActive = () => true) {
    const transactionId = pending?.transactionId || pending?.fraudResult?.transactionId;
    if (!transactionId) {
      if (!quiet && isActive()) setStatusError('Transaction reference is missing. Return to checkout to start again.');
      return;
    }

    setRefreshingStatus(true);
    setStatusError('');
    setStatusNotice('');
    try {
      const current = await getTransactionStatus(transactionId);
      if (!isActive()) return;
      const modelPrediction = current.fraud_prediction;
      const savedResult = pending.fraudResult || {};
      const modelDecision = modelPrediction?.decision || savedResult.modelDecision || savedResult.decision;
      const isApprovedReview = ['REVIEW_APPROVED', 'ORDERED'].includes(current.status)
        && current.review_decision === 'APPROVE';
      const isRejectedReview = current.status === 'REJECTED' && current.review_decision === 'REJECT';
      const updatedResult = {
        ...savedResult,
        transactionId: current.transaction_id,
        riskLevel: modelPrediction?.risk_level || savedResult.riskLevel,
        fraudScore: modelPrediction?.fraud_probability ?? savedResult.fraudScore,
        modelDecision,
        decision: isApprovedReview ? 'APPROVE' : isRejectedReview ? 'REJECT' : modelDecision,
        transactionStatus: current.status,
        reviewDecision: current.review_decision,
        reviewedAt: current.reviewed_at,
        adminApproved: isApprovedReview,
      };
      savePendingCheckout({ ...pending, transactionId: current.transaction_id, fraudResult: updatedResult });
      setResult(updatedResult);
      setStatusNotice(isApprovedReview
        ? 'An administrator approved this transaction. Your saved checkout is ready to continue.'
        : isRejectedReview
          ? 'An administrator rejected this transaction. Payment is unavailable.'
        : isRejectedReview || current.status === 'BLOCKED'
          ? 'This transaction was rejected or blocked. Payment is unavailable.'
          : current.status === 'APPROVED'
            ? 'This transaction is approved. Your saved checkout is ready to continue.'
            : 'This transaction is still awaiting administrator review.');
      if (isApprovedReview) navigate('/payment', { replace: true });
    } catch (statusRequestError) {
      if (!isActive()) return;
      setStatusError(statusRequestError.status === 401
        ? 'Your sign-in session expired. Sign in again to check this transaction.'
        : statusRequestError.status === 404
          ? 'This transaction could not be found for your account.'
          : 'Unable to refresh the review status right now. Your transaction remains blocked from payment until its status is confirmed.');
    } finally {
      if (isActive()) setRefreshingStatus(false);
    }
  }

  function runFraudCheck(isActive = () => true) {
    setLoading(true);
    setError('');
    if (!pending?.transaction) {
      setLoading(false);
      setError('Saved checkout transaction details are missing. Return to checkout to start again.');
      return;
    }
    analyzeTransaction(pending.transaction, pending.attemptId)
      .then((res) => {
        if (isActive()) {
          savePendingCheckout({ ...pending, transactionId: res.transactionId, fraudResult: res });
          setResult(res);
          if (res.decision === 'REVIEW') refreshStatus(true, isActive);
        }
      })
      .catch((err) => isActive() && setError(err.message || 'Fraud check failed. Please try again.'))
      .finally(() => isActive() && setLoading(false));
  }

  useEffect(() => {
    if (!pending) return;
    let active = true;

    if (pending.transactionId || pending.fraudResult?.transactionId) {
      refreshStatus(false, () => active);
      return () => {
        active = false;
      };
    }

    if (pending.fraudResult && !pending.fraudResult.isMock) {
      setResult(pending.fraudResult);
      setLoading(false);
      return () => {
        active = false;
      };
    }

    runFraudCheck(() => active);
    return () => {
      active = false;
    };
    // Load once on mount; retry is handled by runFraudCheck.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!pending) {
    return (
      <EmptyState
        title="Nothing to verify"
        message="Start a checkout first."
        action={<Link to="/cart" className="btn btn-primary btn-sm">Go to cart</Link>}
      />
    );
  }

  function handleContinueToPayment() {
    savePendingCheckout({ ...pending, fraudResult: result });
    navigate('/payment');
  }

  function handleSignInAgain() {
    logout();
    navigate('/login', { state: { from: { pathname: '/fraud-verification' } } });
  }

  return (
    <div className="fraud-verification-layout">
      <div>
        <h1>Fraud verification</h1>
        <p>We check every transaction for fraud risk before payment is processed.</p>

        {loading && <LoadingSpinner label="Running fraud risk check…" />}

        {!loading && error && (
          <EmptyState
            title="Verification failed"
            message={error}
            action={(
              <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
                <button className="btn btn-primary btn-sm" onClick={() => runFraudCheck()} disabled={loading}>Retry</button>
                <Link to="/checkout" className="btn btn-secondary btn-sm">Back to checkout</Link>
              </div>
            )}
          />
        )}

        {!loading && !error && result && (
          <>
            <FraudStatusCard result={result} />

            <div style={{ marginTop: 20, display: 'flex', gap: 12 }}>
              {result.decision === 'APPROVE' && (
                <button className="btn btn-primary" onClick={handleContinueToPayment}>
                  Continue to Payment
                </button>
              )}

              {result.decision === 'REVIEW' && (
                <div>
                  <p className="form-error-banner" role="status">
                    Payment is pending administrator review. You can refresh this page to check for a decision.
                  </p>
                  {statusNotice && <p role="status">{statusNotice}</p>}
                  {statusError && <div className="form-error-banner" role="alert">
                    <p>{statusError}</p>
                    {statusError.includes('session expired') && <button className="btn btn-secondary btn-sm" onClick={handleSignInAgain}>Sign in again</button>}
                  </div>}
                  <button className="btn btn-secondary" onClick={() => refreshStatus()} disabled={refreshingStatus}>
                    {refreshingStatus ? 'Checking status...' : 'Refresh review status'}
                  </button>
                </div>
              )}

              {result.decision === 'REJECT' && (
                <div>
                  <p className="form-error-banner" role="alert">This transaction was rejected after administrator review. Payment is unavailable.</p>
                  <Link to="/cart" className="btn btn-secondary">Return to cart</Link>
                </div>
              )}

              {result.decision === 'BLOCK' && (
                <Link to="/cart" className="btn btn-secondary">Return to cart</Link>
              )}

              {result.decision !== 'REJECT' && result.decision !== 'BLOCK' && (
                <Link to="/checkout" className="btn btn-secondary">Edit checkout details</Link>
              )}
            </div>
          </>
        )}
      </div>

      <OrderSummary items={pending.items} subtotal={pending.subtotal} title="Order Summary" />
    </div>
  );
}

export default FraudVerification;
