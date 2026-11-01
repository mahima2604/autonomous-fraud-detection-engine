// Payment.jsx
// Frontend-only payment simulation. No real payment gateway is
// integrated and no card numbers are collected or stored.
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { getPendingCheckout, clearPendingCheckout, savePendingCheckout } from '../services/checkoutService';
import { createOrder, recoverCompletedOrder } from '../services/orderService';
import { useCart } from '../context/cart';
import OrderSummary from '../components/checkout/OrderSummary';
import EmptyState from '../components/common/EmptyState';
import { formatCurrency } from '../utils/formatters';
import { useAuth } from '../context/auth';
import { getOrderVerificationStatus, sendOrderOtp, verifyOrderOtp } from '../services/orderVerificationService';

function Payment() {
  const navigate = useNavigate();
  const { clearCart } = useCart();
  const { user } = useAuth();
  const pending = getPendingCheckout(user?.id);
  const transactionId = pending?.fraudResult?.transactionId;

  const [processing, setProcessing] = useState(false);
  const [paymentMethod, setPaymentMethod] = useState(() => pending?.paymentMethod || 'CARD');
  const [error, setError] = useState('');
  const [orderCode, setOrderCode] = useState('');
  const [orderOtpSent, setOrderOtpSent] = useState(false);
  const [orderOtpVerified, setOrderOtpVerified] = useState(false);
  const [addressReviewed, setAddressReviewed] = useState(false);
  const [verificationBusy, setVerificationBusy] = useState(false);
  const [verificationMessage, setVerificationMessage] = useState('');
  const [resendAfter, setResendAfter] = useState(0);
  const isMediumChallenge = pending?.fraudResult?.riskLevel === 'MEDIUM'
    && (pending?.fraudResult?.decision === 'VERIFY' || pending?.fraudResult?.modelDecision === 'VERIFY');
  const [mediumReleased, setMediumReleased] = useState(false);
  const [reviewRejected, setReviewRejected] = useState(false);

  const refreshOrderState = useCallback(async (isActive = () => true) => {
    if (!transactionId) return;
    const status = await getOrderVerificationStatus(transactionId);
    if (!isActive()) return;
    if (recoverCompletedOrder(status, navigate)) return;
    setOrderOtpSent(status.status === 'pending');
    setOrderOtpVerified(status.verified === true);
    setAddressReviewed(status.address_confirmed === true);
    setResendAfter(status.resend_after_seconds || 0);

    const adminApprovedMedium = isMediumChallenge
      && status.transaction_status === 'REVIEW_APPROVED'
      && status.review_decision === 'APPROVE';
    const adminRejectedMedium = isMediumChallenge
      && status.transaction_status === 'REJECTED'
      && status.review_decision === 'REJECT';
    if (adminApprovedMedium) {
      setMediumReleased(true);
      const latestPending = getPendingCheckout(user?.id);
      savePendingCheckout({
        ...latestPending,
        fraudResult: {
          ...latestPending?.fraudResult,
          decision: 'APPROVE',
          operationalDecision: 'ADMIN_APPROVE',
          transactionStatus: 'REVIEW_APPROVED',
          reviewDecision: 'APPROVE',
        },
      });
      setVerificationMessage('An administrator approved the reviewed transaction. Complete the order email check if it has expired, then continue.');
    } else if (adminRejectedMedium) {
      setReviewRejected(true);
      setVerificationMessage('An administrator rejected this transaction. Payment and order creation are unavailable.');
    } else if (isMediumChallenge && status.operational_decision === 'REVIEW') {
      setVerificationMessage('Your additional verification is complete. The transaction remains held for administrator review.');
    }
  }, [transactionId, user?.id, isMediumChallenge, navigate]);

  useEffect(() => {
    let active = true;
    refreshOrderState(() => active).catch(() => {});
    return () => { active = false; };
  }, [refreshOrderState]);

  useEffect(() => {
    if (resendAfter <= 0) return undefined;
    const timer = setTimeout(() => setResendAfter((seconds) => Math.max(0, seconds - 1)), 1000);
    return () => clearTimeout(timer);
  }, [resendAfter]);

  async function handleSendOrderCode() {
    if (!addressReviewed) {
      setVerificationMessage('Review the delivery address and confirm it before requesting an order code.');
      return;
    }
    setVerificationBusy(true);
    setVerificationMessage('');
    try {
      const result = await sendOrderOtp(pending.fraudResult.transactionId, pending.shippingAddress, addressReviewed);
      if (result.status === 'verified') {
        setOrderOtpVerified(true);
        setVerificationMessage('This checkout attempt is already verified.');
      } else if (result.status === 'complete') {
        recoverCompletedOrder(result, navigate);
        return;
      } else {
        setOrderOtpSent(true);
        setOrderCode('');
        setResendAfter(result.resend_after_seconds || 30);
        setVerificationMessage('A new order verification code was sent to your account email.');
      }
    } catch (verificationError) {
      setVerificationMessage(verificationError.message || 'Could not send an order verification code. Try again later.');
    } finally {
      setVerificationBusy(false);
    }
  }

  async function handleVerifyOrderCode() {
    setVerificationBusy(true);
    setVerificationMessage('');
    try {
      const result = await verifyOrderOtp(pending.fraudResult.transactionId, orderCode.trim());
      setOrderOtpVerified(true);
      const released = result.checkout_released === true || !isMediumChallenge;
      if (released) {
        setMediumReleased(true);
        savePendingCheckout({
          ...pending,
          fraudResult: {
            ...pending.fraudResult,
            modelDecision: pending.fraudResult.modelDecision || pending.fraudResult.decision,
            decision: 'APPROVE',
            operationalDecision: result.operational_decision || 'APPROVE',
            transactionStatus: result.transaction_status || 'APPROVED',
          },
        });
      }
      setVerificationMessage(released
        ? isMediumChallenge
          ? 'Additional verification is complete. The original risk score is unchanged; checkout is approved to continue.'
          : 'Order email verification complete.'
        : 'Order email verification is complete; the transaction remains held. Please contact support or wait for the required review.');
    } catch (verificationError) {
      setVerificationMessage(verificationError.message || 'Order verification failed. Check the code and try again.');
    } finally {
      setVerificationBusy(false);
    }
  }

  if (!pending || !pending.fraudResult) {
    return (
      <EmptyState
        title="Nothing to pay for"
        message="Please start checkout again."
        action={<Link to="/cart" className="btn btn-primary btn-sm">Go to cart</Link>}
      />
    );
  }

  if (reviewRejected) {
    return <EmptyState
      title="Transaction rejected"
      message="An administrator rejected this transaction. Payment and order creation are unavailable."
      action={<Link to="/orders" className="btn btn-primary btn-sm">View order history</Link>}
    />;
  }

  if (pending.fraudResult.decision !== 'APPROVE' && !isMediumChallenge) {
    return (
      <EmptyState
        title="Payment unavailable"
        message={pending.fraudResult.decision === 'REVIEW'
          ? 'This transaction is awaiting administrator review and cannot be paid until approved.'
          : pending.fraudResult.decision === 'REJECT'
            ? 'This transaction was rejected after administrator review and cannot be paid for.'
            : 'This transaction was blocked during verification and cannot be paid for.'}
        action={<Link to="/cart" className="btn btn-primary btn-sm">Return to cart</Link>}
      />
    );
  }

  async function handlePay() {
    setProcessing(true);
    setError('');
    try {
      const order = await createOrder({
        transactionId: pending.fraudResult.transactionId,
        items: pending.items.map((item) => ({ productId: item.id, quantity: item.quantity })),
        paymentMethod,
        shippingAddress: pending.shippingAddress,
        billingAddress: pending.billingAddress,
      });

      sessionStorage.setItem('last_order', JSON.stringify(order));
      clearPendingCheckout();
      clearCart();
      navigate('/order-success');
    } catch (err) {
      setError(err.message || 'Payment failed. Please try again.');
    } finally {
      setProcessing(false);
    }
  }

  return (
    <div className="fraud-verification-layout">
      <div>
        <h1>Payment</h1>
        <div className="card card-padded" style={{ marginBottom: 20 }}>
          <h3>Payment simulation</h3>
          {!isMediumChallenge || mediumReleased ? <p>
            {paymentMethod === 'COD'
              ? 'This records a simulated COD order only. No cash is collected and no payment is recorded now.'
              : 'This records a simulated payment only. No payment provider is connected and no real charge is made.'}
          </p> : <p role="status">This medium-risk transaction is on hold while we verify this checkout. The simulated payment controls will be available only after reassessment succeeds.</p>}
          {(!isMediumChallenge || mediumReleased) && <fieldset className="payment-method-options" style={{ border: 0, padding: 0, margin: '16px 0' }}>
            <legend style={{ fontWeight: 600, color: 'var(--color-text)', marginBottom: 8 }}>Choose a payment method</legend>
            {[
              ['CARD', 'Credit / Debit Card'],
              ['PAYPAL', 'PayPal'],
              ['BANK_TRANSFER', 'Bank Transfer'],
              ['COD', 'Cash on Delivery (COD)'],
            ].map(([method, label]) => (
              <label key={method} className="payment-method-option">
                <input
                  type="radio"
                  name="paymentMethod"
                  value={method}
                  checked={paymentMethod === method}
                  onChange={() => {
                    setPaymentMethod(method);
                    savePendingCheckout({ ...pending, paymentMethod: method });
                  }}
                />
                {label}
              </label>
            ))}
          </fieldset>}
          {(!isMediumChallenge || mediumReleased) && <p className="payment-simulation-note">
            {paymentMethod === 'COD'
              ? 'Cash is due on delivery. This simulated checkout does not collect cash or record payment before collection.'
              : 'Payment is simulated. No card, PayPal, or bank credentials are requested or sent.'}
          </p>}
          <section aria-labelledby="order-address-verification-heading" style={{ borderTop: '1px solid var(--color-border)', paddingTop: 16, marginTop: 16 }}>
            <h4 id="order-address-verification-heading">Confirm this order’s delivery address</h4>
            <p>{[pending.shippingAddress?.line1, pending.shippingAddress?.locality, pending.shippingAddress?.city, pending.shippingAddress?.state, pending.shippingAddress?.postalCode, pending.shippingAddress?.country].filter(Boolean).join(', ')}</p>
            <label className="address-confirm">
              <input type="checkbox" checked={addressReviewed} onChange={(event) => setAddressReviewed(event.target.checked)} disabled={orderOtpVerified} />
              I reviewed this delivery address for this order.
            </label>
            <button type="button" className="btn btn-secondary" onClick={handleSendOrderCode} disabled={verificationBusy || orderOtpVerified || !addressReviewed || resendAfter > 0}>
              {verificationBusy ? 'Please wait…' : orderOtpSent ? resendAfter > 0 ? `Resend order code in ${resendAfter}s` : 'Resend order code' : 'Confirm address and send order code'}
            </button>
            {orderOtpSent && !orderOtpVerified && <div className="field" style={{ marginTop: 14 }}>
              <label htmlFor="order-otp">Order verification code</label>
              <input id="order-otp" inputMode="numeric" autoComplete="one-time-code" value={orderCode} onChange={(event) => setOrderCode(event.target.value.replace(/\D/g, '').slice(0, 6))} />
              <button type="button" className="btn btn-primary" style={{ marginTop: 10 }} onClick={handleVerifyOrderCode} disabled={verificationBusy || orderCode.length !== 6}>
                {verificationBusy ? 'Verifying…' : 'Verify order code'}
              </button>
            </div>}
            {verificationMessage && <p role="status" style={{ marginTop: 10 }}>{verificationMessage}</p>}
          {isMediumChallenge && orderOtpVerified && !mediumReleased && !reviewRejected && <button
            type="button"
            className="btn btn-secondary"
            onClick={() => refreshOrderState().catch((refreshError) => setVerificationMessage(refreshError.message || 'Could not refresh the review status.'))}
          >Refresh review status</button>}
            <p className="address-hint">This confirms the address you selected for this order. It does not prove who lives there.</p>
          </section>
          {error && <div className="form-error-banner">{error}</div>}
          {(!isMediumChallenge || mediumReleased) && <button className="btn btn-primary btn-block" onClick={handlePay} disabled={processing || !orderOtpVerified || (isMediumChallenge && !mediumReleased)}>
              {processing ? 'Recording order...' : !orderOtpVerified ? 'Verify this order to continue' : paymentMethod === 'COD' ? `Place COD order: ${formatCurrency(pending.subtotal)}` : `Confirm simulated payment: ${formatCurrency(pending.subtotal)}`}
          </button>
          }
        </div>
      </div>

      <OrderSummary items={pending.items} subtotal={pending.subtotal} title="Order Summary" />
    </div>
  );
}

export default Payment;
