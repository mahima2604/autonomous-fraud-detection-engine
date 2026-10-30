import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const previousStorage = globalThis.localStorage;
globalThis.localStorage = { getItem: () => null };

const vite = await createServer({
  configFile: false,
  root: fileURLToPath(new URL('..', import.meta.url)),
  logLevel: 'silent',
  server: { middlewareMode: true },
  appType: 'custom',
});
const { apiRequest, ApiError } = await vite.ssrLoadModule('/src/services/api.js');

after(async () => {
  await vite.close();
  if (previousStorage === undefined) delete globalThis.localStorage;
  else globalThis.localStorage = previousStorage;
});

test('apiRequest rejects a pending request when its timeout expires', async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => {
      const error = new Error('Aborted');
      error.name = 'AbortError';
      reject(error);
    }, { once: true });
  });

  try {
    await assert.rejects(
      apiRequest('/auth/login', {
        method: 'POST',
        body: { email: 'customer@example.test', password: 'not-logged' },
        timeoutMs: 10,
      }),
      (error) => error instanceof ApiError
        && error.status === 0
        && error.message.includes('did not respond in time'),
    );
  } finally {
    globalThis.fetch = previousFetch;
  }
});
