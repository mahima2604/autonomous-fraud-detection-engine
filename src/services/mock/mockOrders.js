// mockOrders.js
// MOCK DATA — order history shown until GET /api/orders is available.

export const mockOrders = [
  {
    id: 'ORD-10234',
    date: '2026-07-28T14:32:00Z',
    amount: 208.5,
    status: 'DELIVERED',
    paymentStatus: 'PAID',
    items: ['Aurora Wireless Headphones', 'Orbit Travel Mug'],
  },
  {
    id: 'ORD-10221',
    date: '2026-07-14T09:05:00Z',
    amount: 79.5,
    status: 'SHIPPED',
    paymentStatus: 'PAID',
    items: ['Pulse Fitness Tracker'],
  },
  {
    id: 'ORD-10188',
    date: '2026-06-30T18:47:00Z',
    amount: 149.0,
    status: 'CANCELLED',
    paymentStatus: 'REFUNDED',
    items: ['Cascade Mechanical Keyboard'],
  },
];
