// paymentService.js
// Simulated payment processing only. No real payment gateway is
// integrated, and no card numbers are collected or stored here.

import { apiRequest, USE_MOCKS, mockDelay } from './api';

export async function processPayment({ transactionId, amount, paymentMethod }) {
  if (USE_MOCKS) {
    await mockDelay(900);
    return {
      paymentId: `MOCK-PAY-${Date.now()}`,
      transactionId,
      amount,
      paymentMethod,
      status: 'SUCCESS',
      isMock: true,
    };
  }
  return apiRequest('/payment/process', { method: 'POST', body: { transactionId, amount, paymentMethod } });
}
