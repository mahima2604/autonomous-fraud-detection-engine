import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const previousStorage = globalThis.localStorage;
globalThis.localStorage = { getItem: () => 'test-session-token' };

const vite = await createServer({
  configFile: false,
  root: fileURLToPath(new URL('..', import.meta.url)),
  logLevel: 'silent',
  server: { middlewareMode: true },
  appType: 'custom',
});
const { analyzeTransaction, getRecentFraudPredictions } = await vite.ssrLoadModule('/src/services/fraudService.js');
const { buildTransactionPayload, getClientDeviceInfo } = await vite.ssrLoadModule('/src/services/checkoutService.js');
const { getBenchmarkEvaluation } = await vite.ssrLoadModule('/src/services/adminBenchmarkService.js');

after(async () => {
  await vite.close();
  if (previousStorage === undefined) delete globalThis.localStorage;
  else globalThis.localStorage = previousStorage;
});

test('fraud service preserves the backend medium verification action and score outcome', async () => {
  const previousFetch = globalThis.fetch;
  let submittedPayload;
  globalThis.fetch = async (_url, options) => {
    submittedPayload = JSON.parse(options.body);
    return new Response(JSON.stringify({
      transaction_id: 72,
      fraud_probability: 0.46,
      risk_level: 'MEDIUM',
      decision: 'VERIFY',
      score_based_decision: 'REVIEW',
      model_used: 'GraphSAGE',
    }), { status: 200, headers: { 'content-type': 'application/json' } });
  };

  try {
    const result = await analyzeTransaction({ TransactionAmt: 25 }, 'checkout-attempt-test');
    assert.equal(result.decision, 'VERIFY');
    assert.equal(result.modelDecision, 'VERIFY');
    assert.equal(result.operationalDecision, 'VERIFY');
    assert.equal(result.scoreBasedDecision, 'REVIEW');
    assert.equal(result.riskLevel, 'MEDIUM');
    assert.equal(submittedPayload.checkout_attempt_id, 'checkout-attempt-test');
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test('recent fraud history preserves current score classification beside recorded operational fields', async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify([{
    transaction_id: 10000043,
    fraud_probability: 0.4476,
    risk_level: 'MEDIUM',
    score_based_decision: 'REVIEW',
    recorded_risk_level: 'HIGH',
    recorded_score_based_decision: 'BLOCK',
    decision: 'REVIEW',
    operational_decision: 'REVIEW',
    status: 'REVIEW',
    review_decision: null,
    classification_consistent: false,
  }]), { status: 200, headers: { 'content-type': 'application/json' } });

  try {
    const [transaction] = await getRecentFraudPredictions();
    assert.equal(transaction.riskLevel, 'MEDIUM');
    assert.equal(transaction.score_based_decision, 'REVIEW');
    assert.equal(transaction.recorded_risk_level, 'HIGH');
    assert.equal(transaction.operational_decision, 'REVIEW');
    assert.equal(transaction.status, 'REVIEW');
    assert.equal(transaction.classification_consistent, false);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test('checkout collects only an allowlisted coarse browser platform hint', () => {
  const previousNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: { userAgent: 'Mozilla/5.0 (Windows NT 10.0)', platform: 'Win32', userAgentData: { platform: 'Windows' } },
  });
  try {
    const device = getClientDeviceInfo();
    assert.equal(device.deviceType, 'desktop');
    assert.equal(device.deviceInfo, 'Windows');
    assert.equal(device.devicePlatformHint, 'Windows');
    const payload = buildTransactionPayload({ user: { email: 'buyer@example.test' }, amount: 25 });
    assert.equal(payload.DevicePlatformHint, 'Windows');
    assert.equal(payload.DeviceInfo, 'Windows');
  } finally {
    if (previousNavigator) Object.defineProperty(globalThis, 'navigator', previousNavigator);
    else delete globalThis.navigator;
  }
});

test('unsupported browser platform values remain UNKNOWN', () => {
  const previousNavigator = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', {
    configurable: true,
    value: { userAgent: 'Mozilla/5.0', platform: 'Unknown platform', userAgentData: { platform: 'Unknown platform' } },
  });
  try {
    assert.equal(getClientDeviceInfo().deviceInfo, 'UNKNOWN');
  } finally {
    if (previousNavigator) Object.defineProperty(globalThis, 'navigator', previousNavigator);
    else delete globalThis.navigator;
  }
});

test('benchmark re-run still requests a fresh evaluation from the existing API', async () => {
  const previousFetch = globalThis.fetch;
  let requestedUrl;
  globalThis.fetch = async (url) => {
    requestedUrl = url;
    return new Response(JSON.stringify({ status: 'success' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  };

  try {
    await getBenchmarkEvaluation(true);
    assert.match(requestedUrl, /\/admin\/benchmark\/evaluation\?force_refresh=true$/);
  } finally {
    globalThis.fetch = previousFetch;
  }
});
