// orderService.js
// Order creation + history. Uses mockOrders until POST /api/orders and
// GET /api/orders are available.

import { apiRequest, USE_MOCKS, mockDelay } from './api';
import { mockOrders } from './mock/mockOrders';

export async function createOrder(orderData) {
  await mockDelay(500);
  return {
    id: `ORD-${Math.floor(10000 + Math.random() * 89999)}`,
    date: new Date().toISOString(),
    status: 'PROCESSING',
    paymentStatus: 'PAID',
    ...orderData,
  };
}

export async function getOrders() {
  await mockDelay(500);
  return mockOrders;
}
