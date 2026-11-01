import React from 'react';

function CheckoutEmailVerification({
  email,
  checkingEmailStatus,
  otp,
  otpSent,
  otpBusy,
  otpVerified,
  otpMessage,
  otpError,
  resendAfter,
  onOtpChange,
  onSendOtp,
  onVerifyOtp,
}) {
  return (
    <section className="card card-padded" style={{ marginBottom: 20 }} aria-labelledby="email-verification-heading">
      <h3 id="email-verification-heading">Checkout email verification</h3>
      <p>Send a one-time password to your registered email and verify it to continue.</p>
      <div className="field">
        <label htmlFor="checkout-email">Registered email</label>
        <input id="checkout-email" type="email" value={email} readOnly />
      </div>
      {!otpVerified && <button
        className="btn btn-secondary"
        type="button"
        onClick={onSendOtp}
        disabled={otpBusy || checkingEmailStatus || resendAfter > 0 || !email}
      >
        {otpBusy && !otpSent
          ? 'Sending OTP...'
          : resendAfter > 0
            ? `${otpSent ? 'Resend' : 'Send'} OTP in ${resendAfter}s`
            : otpSent ? 'Resend OTP' : 'Send OTP to Email'}
      </button>}
      {otpSent && !otpVerified && <div className="field" style={{ marginTop: 14 }}>
        <label htmlFor="checkout-otp">One-time password</label>
        <input
          id="checkout-otp"
          inputMode="numeric"
          autoComplete="one-time-code"
          value={otp}
          onChange={(event) => onOtpChange(event.target.value.replace(/\D/g, '').slice(0, 6))}
        />
        <button className="btn btn-primary" type="button" style={{ marginTop: 10 }} onClick={onVerifyOtp} disabled={otpBusy || otp.length !== 6}>
          {otpBusy ? 'Verifying...' : 'Verify OTP'}
        </button>
      </div>}
      {otpMessage && <p role="status" style={{ marginBottom: 0 }}>{otpMessage}</p>}
      {otpError && <p role="alert" className="form-error-banner">{otpError}</p>}
    </section>
  );
}

export default CheckoutEmailVerification;
