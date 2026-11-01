import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const vite = await createServer({
  configFile: false,
  root: fileURLToPath(new URL('..', import.meta.url)),
  logLevel: 'silent',
  server: { middlewareMode: true },
  appType: 'custom',
});
const { recoverCompletedOrder } = await vite.ssrLoadModule('/src/services/orderService.js');

after(async () => vite.close());

test('completed checkout attempts recover to order history without starting another order', () => {
  const navigations = [];
  const recovered = recoverCompletedOrder(
    { status: 'complete', transaction_id: 41, order_id: 92 },
    (...args) => navigations.push(args),
  );

  assert.equal(recovered, true);
  assert.deepEqual(navigations, [['/orders', { replace: true }]]);
});

test('unfinished checkout attempts do not trigger completed-order recovery', () => {
  const navigations = [];
  const recovered = recoverCompletedOrder(
    { status: 'verified' },
    (...args) => navigations.push(args),
  );

  assert.equal(recovered, false);
  assert.deepEqual(navigations, []);
});
