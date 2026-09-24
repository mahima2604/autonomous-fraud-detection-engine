// orderService.js
// Order creation + history. Uses mockOrders until POST /api/orders and
// GET /api/orders are available.

import { apiRequest, USE_MOCKS, mockDelay } from './api';
import { mockOrders } from './mock/mockOrders';

export async function createOrder(orderData) {
  if (USE_MOCKS) {
    await mockDelay(500);
    return {
      id: `ORD-${Math.floor(10000 + Math.random() * 89999)}`,
      date: new Date().toISOString(),
      status: 'PROCESSING',
      paymentStatus: 'PAID',
      ...orderData,
    };
  }
  return apiRequest('/orders', { method: 'POST', body: orderData });
}

export async function getOrders() {
  if (USE_MOCKS) {
    await mockDelay(500);
    return mockOrders;
  }
  return apiRequest('/orders');
}
