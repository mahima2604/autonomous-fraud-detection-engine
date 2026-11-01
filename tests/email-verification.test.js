import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const priorStorage = globalThis.localStorage;
globalThis.localStorage = { getItem: () => 'checkout-test-token' };
const vite = await createServer({
  configFile: false,
  root: fileURLToPath(new URL('..', import.meta.url)),
  logLevel: 'silent',
  server: { middlewareMode: true },
  appType: 'custom',
});
const { default: CheckoutEmailVerification } = await vite.ssrLoadModule('/src/components/checkout/CheckoutEmailVerification.jsx');
const { sendEmailOtp, verifyEmailOtp } = await vite.ssrLoadModule('/src/services/emailVerificationService.js');

after(async () => {
  await vite.close();
  if (priorStorage === undefined) delete globalThis.localStorage;
  else globalThis.localStorage = priorStorage;
});

function renderVerification(props = {}) {
  return renderToStaticMarkup(createElement(CheckoutEmailVerification, {
    email: 'buyer@example.test',
    checkingEmailStatus: false,
    otp: '',
    otpSent: false,
    otpBusy: false,
    otpVerified: false,
    otpMessage: '',
    otpError: '',
    resendAfter: 0,
    onOtpChange() {},
    onSendOtp() {},
    onVerifyOtp() {},
    ...props,
  }));
}

test('checkout verification always offers deliberate OTP generation, including for a previously verified account', () => {
  const markup = renderVerification();
  assert.match(markup, /Send OTP to Email/);
  assert.match(markup, /Registered email/);
  assert.doesNotMatch(markup, /Account email verified\. A separate checkout OTP will still be required/);
  assert.doesNotMatch(markup, /id="checkout-otp"/);
});

test('successful OTP request displays the sent message, input, and verification action', () => {
  const markup = renderVerification({
    otpSent: true,
    otpMessage: 'OTP sent to your registered email. Enter the code to continue this checkout.',
  });
  assert.match(markup, /OTP sent to your registered email/);
  assert.match(markup, /id="checkout-otp"/);
  assert.match(markup, /Verify OTP/);
});

test('OTP controls show loading, server errors, and resend cooldown', () => {
  assert.match(renderVerification({ otpBusy: true }), /Sending OTP\.\.\./);
  assert.match(renderVerification({ otpSent: true, otpBusy: true, otp: '123456' }), /Verifying\.\.\./);
  assert.match(renderVerification({ otpError: 'OTP expired. Request a new OTP' }), /role="alert"[^>]*>OTP expired/);
  assert.match(renderVerification({ resendAfter: 17 }), /Send OTP in 17s/);
});

test('email OTP service sends authenticated generate and verify requests', async () => {
  const previousFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return {
      ok: true,
      text: async () => requests.length === 1
        ? '{"status":"pending","email_address":"buyer@example.test","resend_after_seconds":30}'
        : '{"status":"verified"}',
    };
  };
  try {
    const sent = await sendEmailOtp();
    const verified = await verifyEmailOtp('123456');
    assert.equal(sent.status, 'pending');
    assert.equal(verified.status, 'verified');
    assert.match(requests[0].url, /\/email-verification\/send$/);
    assert.equal(requests[0].options.method, 'POST');
    assert.equal(requests[0].options.headers.Authorization, 'Bearer checkout-test-token');
    assert.match(requests[1].url, /\/email-verification\/verify$/);
    assert.deepEqual(JSON.parse(requests[1].options.body), { code: '123456' });
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test('email OTP service preserves delivery, cooldown, invalid, and expired errors from the backend', async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    status: 429,
    text: async () => '{"detail":"Please wait 19 seconds before requesting another OTP"}',
  });
  try {
    await assert.rejects(sendEmailOtp(), /Please wait 19 seconds/);
    globalThis.fetch = async () => ({
      ok: false,
      status: 410,
      text: async () => '{"detail":"OTP expired. Request a new OTP"}',
    });
    await assert.rejects(verifyEmailOtp('123456'), /OTP expired/);
    globalThis.fetch = async () => ({
      ok: false,
      status: 503,
      text: async () => '{"detail":"Email delivery failed. Check SMTP settings and try again later."}',
    });
    await assert.rejects(sendEmailOtp(), /Email delivery failed/);
  } finally {
    globalThis.fetch = previousFetch;
  }
});
