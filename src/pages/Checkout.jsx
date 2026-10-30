// Checkout.jsx
// Collects shipping/billing info and payment method choice, then hands
// off to Fraud Verification before any payment is attempted.
import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCart } from '../context/cart';
import { useAuth } from '../context/auth';
import AddressForm from '../components/checkout/AddressForm';
import OrderSummary from '../components/checkout/OrderSummary';
import { buildTransactionPayload, clearPendingCheckout, getPendingCheckout, savePendingCheckout } from '../services/checkoutService';
import { getTransactionStatus } from '../services/fraudService';
import EmptyState from '../components/common/EmptyState';
import { getEmailVerificationStatus, sendEmailOtp, verifyEmailOtp } from '../services/emailVerificationService';

const EMPTY_ADDRESS = { fullName: '', line1: '', city: '', postalCode: '', country: '' };

function Checkout() {
  const { items: cartItems, subtotal: cartSubtotal } = useCart();
  const { user } = useAuth();
  const navigate = useNavigate();
  const [savedCheckout, setSavedCheckout] = useState(() => getPendingCheckout(user?.id));

  // Cart state can change or be cleared while checkout is awaiting review.
  // The pending checkout is the source for resuming that same attempt.
  const items = savedCheckout?.items?.length ? savedCheckout.items : cartItems;
  const subtotal = savedCheckout?.items?.length ? savedCheckout.subtotal : cartSubtotal;

  const [shipping, setShipping] = useState(() => savedCheckout?.shippingAddress || EMPTY_ADDRESS);
  const [billing, setBilling] = useState(() => savedCheckout?.billingAddress || EMPTY_ADDRESS);
  const [sameAsShipping, setSameAsShipping] = useState(() =>
    !savedCheckout?.billingAddress || JSON.stringify(savedCheckout.billingAddress) === JSON.stringify(savedCheckout.shippingAddress));
  const [paymentMethod, setPaymentMethod] = useState(() => savedCheckout?.paymentMethod || 'CARD');
  const [otp, setOtp] = useState('');
  const [verifiedEmail, setVerifiedEmail] = useState('');
  const [targetEmail, setTargetEmail] = useState(user?.email || '');
  const [checkingEmailStatus, setCheckingEmailStatus] = useState(true);
  const [otpSent, setOtpSent] = useState(false);
  const [otpBusy, setOtpBusy] = useState(false);
  const [otpMessage, setOtpMessage] = useState('');
  const [otpError, setOtpError] = useState('');
  const [resendAfter, setResendAfter] = useState(0);
  const otpRequestLock = useRef(false);
  const [error, setError] = useState('');
  const [checkingSavedStatus, setCheckingSavedStatus] = useState(() => Boolean(
    savedCheckout?.transactionId || savedCheckout?.fraudResult?.transactionId
  ));

  useEffect(() => {
    let active = true;
    setCheckingEmailStatus(true);
    setVerifiedEmail('');
    getEmailVerificationStatus().then((status) => {
      if (!active) return;
      setTargetEmail(status.email_address || user?.email || '');
      setVerifiedEmail(status.verified ? status.email_address : '');
    }).catch(() => {}).finally(() => active && setCheckingEmailStatus(false));
    return () => { active = false; };
  }, [user?.id, user?.email]);

  useEffect(() => {
    if (resendAfter <= 0) return undefined;
    const timer = setTimeout(() => setResendAfter((remaining) => Math.max(0, remaining - 1)), 1000);
    return () => clearTimeout(timer);
  }, [resendAfter]);

  async function handleSendOtp() {
    if (otpRequestLock.current) return;
    otpRequestLock.current = true;
    setOtpBusy(true);
    setOtpError('');
    setOtpMessage('');
    try {
      const response = await sendEmailOtp();
      setTargetEmail(response.email_address || targetEmail);
      setVerifiedEmail('');
      setOtpSent(true);
      setOtp('');
      setResendAfter(response.resend_after_seconds || 30);
      setOtpMessage(`Email sent to ${response.email_address || targetEmail}. Enter the verification code from that message.`);
    } catch (requestError) {
      setOtpError(requestError.message || 'Could not send OTP. Please try again.');
    } finally {
      otpRequestLock.current = false;
      setOtpBusy(false);
    }
  }

  async function handleVerifyOtp() {
    if (otpRequestLock.current) return;
    otpRequestLock.current = true;
    setOtpBusy(true);
    setOtpError('');
    setOtpMessage('');
    try {
      await verifyEmailOtp(otp.trim());
      setVerifiedEmail(targetEmail);
      setOtpMessage('Email verified ✓');
      setOtpError('');
    } catch (verifyError) {
      setOtpError(verifyError.message || 'OTP verification failed. Please try again.');
    } finally {
      otpRequestLock.current = false;
      setOtpBusy(false);
    }
  }

  useEffect(() => {
    const transactionId = savedCheckout?.transactionId || savedCheckout?.fraudResult?.transactionId;
    if (!transactionId) return;

    let active = true;
    getTransactionStatus(transactionId)
      .then((current) => {
        if (!active) return;
        const modelDecision = current.fraud_prediction?.decision || savedCheckout.fraudResult?.modelDecision;
        const approved = (
          ['APPROVED', 'ORDERED'].includes(current.status) && modelDecision === 'APPROVE'
        ) || (
          ['REVIEW_APPROVED', 'ORDERED'].includes(current.status)
          && current.review_decision === 'APPROVE'
          && modelDecision === 'REVIEW'
        );
        const result = {
          ...savedCheckout.fraudResult,
          transactionId: current.transaction_id,
          modelDecision,
          decision: approved ? 'APPROVE' : current.status === 'REJECTED' ? 'REJECT' : modelDecision,
          transactionStatus: current.status,
          reviewDecision: current.review_decision,
          reviewedAt: current.reviewed_at,
          adminApproved: current.review_decision === 'APPROVE',
        };
        const resumedCheckout = { ...savedCheckout, transactionId: current.transaction_id, fraudResult: result };
        savePendingCheckout(resumedCheckout);
        setSavedCheckout(resumedCheckout);
        if (approved) navigate('/payment', { replace: true });
      })
      .catch(() => {
        // Keep the saved checkout visible; payment remains guarded by backend approval.
      })
      .finally(() => active && setCheckingSavedStatus(false));

    return () => {
      active = false;
    };
  // Resume a saved transaction once when checkout opens.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (checkingSavedStatus) {
    return <p role="status">Checking your saved checkout status...</p>;
  }

  if (savedCheckout?.transactionId || savedCheckout?.fraudResult) {
    const rejected = savedCheckout.fraudResult?.decision === 'REJECT'
      || savedCheckout.fraudResult?.transactionStatus === 'REJECTED';

    return (
      <div>
        <h1>Resume checkout</h1>
        <p>{rejected
          ? 'This saved transaction was rejected and cannot continue to payment.'
          : 'Your checkout details and transaction are saved. Continue with this same checkout attempt.'}</p>
        <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
          {!rejected && <button className="btn btn-primary" onClick={() => navigate('/fraud-verification')}>
            Resume saved checkout
          </button>}
          <button className="btn btn-secondary" onClick={() => {
            clearPendingCheckout();
            setSavedCheckout(null);
            setShipping(EMPTY_ADDRESS);
            setBilling(EMPTY_ADDRESS);
            setSameAsShipping(true);
            setPaymentMethod('CARD');
          }}>
            Start a new checkout
          </button>
        </div>
        <OrderSummary items={items} subtotal={subtotal} title="Saved Order Summary" />
      </div>
    );
  }

  if (items.length === 0) {
    return <EmptyState title="Your cart is empty" message="Add products before checking out." />;
  }

  function validate() {
    const requiredFilled = (addr) => Object.values(addr).every((v) => v.trim().length > 0);
    if (!requiredFilled(shipping)) return 'Please complete the shipping address.';
    if (!sameAsShipping && !requiredFilled(billing)) return 'Please complete the billing address.';
    if (!targetEmail || verifiedEmail !== targetEmail) return 'Verify your account email before continuing.';
    return '';
  }

  function handleSubmit(e) {
    e.preventDefault();
    if (savedCheckout?.fraudResult) {
      navigate('/fraud-verification');
      return;
    }
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setError('');

    const billingAddress = sameAsShipping ? shipping : billing;
    const payload = buildTransactionPayload({
      user,
      items,
      amount: subtotal,
      paymentMethod,
      billingAddress,
      shippingAddress: shipping,
    });

    savePendingCheckout({
      ...savedCheckout,
      userId: user?.id,
      transaction: payload,
      items,
      subtotal,
      paymentMethod,
      shippingAddress: shipping,
      billingAddress,
    });
    navigate('/fraud-verification');
  }

  return (
    <div>
      <h1>Checkout</h1>
      <div className="checkout-layout">
        <form className="checkout-form" onSubmit={handleSubmit} noValidate>
          {error && <div className="form-error-banner">{error}</div>}

          <div className="card card-padded" style={{ marginBottom: 20 }}>
            <h3>Shipping address</h3>
            <AddressForm values={shipping} onChange={setShipping} prefix="ship" />
          </div>

          <section className="card card-padded" style={{ marginBottom: 20 }} aria-labelledby="email-verification-heading">
            <h3 id="email-verification-heading">Email Verification</h3>
            <p>Verify the email address on your signed-in account before continuing to fraud verification.</p>
            <div className="field">
              <label htmlFor="checkout-email">Account email</label>
              <input id="checkout-email" type="email" value={targetEmail} readOnly />
            </div>
            {!verifiedEmail && <button className="btn btn-secondary" type="button" onClick={handleSendOtp} disabled={otpBusy || checkingEmailStatus || resendAfter > 0 || !targetEmail}>
              {otpBusy && !otpSent ? 'Sending...' : resendAfter > 0 && otpSent ? `Resend OTP in ${resendAfter}s` : otpSent ? 'Resend OTP' : 'Send OTP'}
            </button>}
            {otpSent && !verifiedEmail && <div className="field" style={{ marginTop: 14 }}>
              <label htmlFor="checkout-otp">One-time password</label>
              <input id="checkout-otp" inputMode="numeric" autoComplete="one-time-code" value={otp} onChange={(event) => setOtp(event.target.value.replace(/\D/g, '').slice(0, 6))} />
              <button className="btn btn-primary" type="button" style={{ marginTop: 10 }} onClick={handleVerifyOtp} disabled={otpBusy || otp.length !== 6}>
                {otpBusy ? 'Verifying...' : 'Verify OTP'}
              </button>
            </div>}
            {otpMessage && <p role="status" style={{ marginBottom: 0 }}>{otpMessage}</p>}
            {otpError && <p role="alert" className="form-error-banner">{otpError}</p>}
            {verifiedEmail && <p role="status" style={{ fontWeight: 600 }}>Email verified ✓</p>}
          </section>

          <div className="card card-padded" style={{ marginBottom: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <h3>Billing address</h3>
              <label style={{ fontSize: 13.5, display: 'flex', alignItems: 'center', gap: 6, fontWeight: 500 }}>
                <input
                  type="checkbox"
                  checked={sameAsShipping}
                  onChange={(e) => setSameAsShipping(e.target.checked)}
                />
                Same as shipping
              </label>
            </div>
            {!sameAsShipping && <AddressForm values={billing} onChange={setBilling} prefix="bill" />}
          </div>

          <div className="card card-padded" style={{ marginBottom: 20 }}>
            <h3>Payment method</h3>
            <div className="payment-method-options">
              {['CARD', 'PAYPAL', 'BANK_TRANSFER'].map((method) => (
                <label key={method} className="payment-method-option">
                  <input
                    type="radio"
                    name="paymentMethod"
                    value={method}
                    checked={paymentMethod === method}
                    onChange={() => setPaymentMethod(method)}
                  />
                  {method === 'CARD' ? 'Credit / Debit Card' : method === 'PAYPAL' ? 'PayPal' : 'Bank Transfer'}
                </label>
              ))}
            </div>
            <p className="payment-simulation-note">
              Payments are simulated. No card details are collected or sent to a payment provider.
            </p>
          </div>

          <button className="btn btn-primary btn-block" type="submit" disabled={verifiedEmail !== targetEmail || otpBusy || checkingEmailStatus}>
            Continue to Fraud Verification
          </button>
        </form>

        <OrderSummary items={items} subtotal={subtotal} />
      </div>
    </div>
  );
}

export default Checkout;
