// FraudVerification.jsx
// Sends the pending transaction to the fraud service and renders whatever
// { riskLevel, decision, reasonCodes } it gets back. This page contains
// no fraud-scoring logic of its own — see services/fraudService.js and
// services/mock/mockFraud.js for the clearly-isolated mock stand-in.
import { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { getPendingCheckout, savePendingCheckout } from '../services/checkoutService';
import { analyzeTransaction } from '../services/fraudService';
import OrderSummary from '../components/checkout/OrderSummary';
import FraudStatusCard from '../components/fraud/FraudStatusCard';
import LoadingSpinner from '../components/common/LoadingSpinner';
import EmptyState from '../components/common/EmptyState';

function FraudVerification() {
  const navigate = useNavigate();
  const pending = getPendingCheckout();

  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [confirming, setConfirming] = useState(false);

  useEffect(() => {
    if (!pending) return;
    let active = true;

    if (pending.fraudResult) {
      setResult(pending.fraudResult);
      setLoading(false);
      return () => {
        active = false;
      };
    }

    setLoading(true);
    analyzeTransaction(pending.transaction, pending.attemptId)
      .then((res) => {
        if (active) {
          savePendingCheckout({ ...pending, fraudResult: res });
          setResult(res);
        }
      })
      .catch((err) => active && setError(err.message || 'Fraud check failed. Please try again.'))
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
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

  function handleConfirmAndContinue() {
    // Simulates the user completing an additional verification step for
    // a REVIEW decision. A real implementation would call a dedicated
    // backend verification endpoint here.
    setConfirming(true);
    setTimeout(() => {
      savePendingCheckout({ ...pending, fraudResult: result });
      navigate('/payment');
    }, 600);
  }

  return (
    <div className="fraud-verification-layout">
      <div>
        <h1>Verifying your transaction</h1>
        <p>We check every transaction for fraud risk before payment is processed.</p>

        {loading && <LoadingSpinner label="Running fraud risk check…" />}

        {!loading && error && (
          <EmptyState
            title="Verification failed"
            message={error}
            action={<Link to="/checkout" className="btn btn-primary btn-sm">Back to checkout</Link>}
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
                <button className="btn btn-primary" onClick={handleConfirmAndContinue} disabled={confirming}>
                  {confirming ? 'Confirming…' : 'Confirm details & continue'}
                </button>
              )}

              {result.decision === 'BLOCK' && (
                <Link to="/cart" className="btn btn-secondary">Return to cart</Link>
              )}

              <Link to="/checkout" className="btn btn-secondary">Edit checkout details</Link>
            </div>
          </>
        )}
      </div>

      <OrderSummary items={pending.items} subtotal={pending.subtotal} title="Order Summary" />
    </div>
  );
}

export default FraudVerification;
