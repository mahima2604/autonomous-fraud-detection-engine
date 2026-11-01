import test from 'node:test';
import assert from 'node:assert/strict';

import { formatDateTime } from '../src/utils/formatters.js';

test('formatDateTime renders UTC timestamps in Indian Standard Time', () => {
  assert.equal(formatDateTime('2026-11-01T03:42:00'), '1 Nov 2026, 09:12 am');
  assert.equal(formatDateTime('2026-11-01T03:42:00Z'), '1 Nov 2026, 09:12 am');
});
