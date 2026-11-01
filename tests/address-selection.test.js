import assert from 'node:assert/strict';
import { test } from 'node:test';
import { getCurrentLocation, validateAddress } from '../src/services/addressValidation.js';
import { reverseGeocode, searchAddresses } from '../src/services/geocodingService.js';

test('current location reports unsupported, denied, unavailable, and timeout errors clearly', async () => {
  await assert.rejects(getCurrentLocation(undefined), /does not support location/);
  const expected = [[1, /permission was denied/], [2, /unavailable/], [3, /timed out/]];
  for (const [code, message] of expected) {
    await assert.rejects(getCurrentLocation({
      getCurrentPosition: (_success, failure) => failure({ code }),
    }), message);
  }
});

test('current location returns browser coordinates after the customer requests them', async () => {
  let requestOptions;
  const point = await getCurrentLocation({
    getCurrentPosition: (success, _failure, options) => {
      requestOptions = options;
      success({ coords: { latitude: 12.9, longitude: 77.6 } });
    },
  });
  assert.deepEqual(point, { latitude: 12.9, longitude: 77.6 });
  assert.equal(requestOptions.timeout, 12000);
});

test('address validation requires six-digit PIN and explicit delivery confirmation', () => {
  const address = { fullName: 'Buyer', line1: '1 Road', city: 'City', postalCode: '560001', country: 'India' };
  assert.match(validateAddress({ ...address, postalCode: '56001' }), /six-digit/);
  assert.match(validateAddress(address, { requireConfirmation: true }), /confirm/);
  assert.equal(validateAddress({ ...address, addressConfirmed: true }, { requireConfirmation: true }), '');
});

test('geocoding service reports failed external responses without fabricating a result', async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false });
  try {
    await assert.rejects(searchAddresses('Example Street'), /temporarily unavailable/);
    await assert.rejects(reverseGeocode(12.9, 77.6), /temporarily unavailable/);
  } finally {
    globalThis.fetch = previousFetch;
  }
});
