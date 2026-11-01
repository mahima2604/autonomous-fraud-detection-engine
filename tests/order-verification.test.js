import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const priorStorage = globalThis.localStorage;
globalThis.localStorage = { getItem: () => 'test-auth-token' };
const vite = await createServer({
  configFile: false,
  root: fileURLToPath(new URL('..', import.meta.url)),
  logLevel: 'silent',
  server: { middlewareMode: true },
  appType: 'custom',
});
const { getOrderVerificationStatus, sendOrderOtp, verifyOrderOtp } = await vite.ssrLoadModule('/src/services/orderVerificationService.js');

after(async () => {
  await vite.close();
  if (priorStorage === undefined) delete globalThis.localStorage;
  else globalThis.localStorage = priorStorage;
});

test('order verification service sends the selected address and explicit confirmation to authenticated endpoints', async () => {
  const previousFetch = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, text: async () => '{"status":"verified"}' };
  };
  try {
    await getOrderVerificationStatus(17);
    await sendOrderOtp(17, {
      fullName: 'Buyer', line1: '1 Road', locality: 'Area', city: 'City', state: 'Karnataka',
      postalCode: '560001', country: 'India', addressConfirmed: true,
    }, true);
    await verifyOrderOtp(17, '123456');
    assert.match(requests[0].url, /\/orders\/17\/verification$/);
    assert.equal(requests[0].options.method, undefined);
    assert.match(requests[1].url, /\/orders\/17\/verification\/send$/);
    assert.equal(requests[1].options.method, 'POST');
    assert.equal(requests[1].options.headers.Authorization, 'Bearer test-auth-token');
    const addressPayload = JSON.parse(requests[1].options.body).shipping_address;
    assert.equal(addressPayload.postal_code, '560001');
    assert.equal('address_confirmed' in addressPayload, false);
    assert.equal(JSON.parse(requests[1].options.body).address_confirmed, true);
    assert.match(requests[2].url, /\/orders\/17\/verification\/verify$/);
    assert.deepEqual(JSON.parse(requests[2].options.body), { code: '123456' });
  } finally {
    globalThis.fetch = previousFetch;
  }
});
