import { apiRequest } from './api';

function normalizeOrder(order) {
  return {
    ...order,
    id: `ORD-${order.id}`,
    date: order.created_at || order.date,
    paymentStatus: order.payment_status || order.paymentStatus,
    transactionId: order.transaction_id || order.transactionId,
    items: (order.items || []).map((item) => item.name || item.product_id),
  };
}

export async function createOrder({ transactionId, items, paymentMethod, shippingAddress, billingAddress }) {
  const order = await apiRequest('/orders', {
    method: 'POST',
    body: {
      transaction_id: transactionId,
      items: items.map((item) => ({ product_id: item.productId, quantity: item.quantity })),
      payment_method: paymentMethod,
      shipping_address: {
        full_name: shippingAddress.fullName,
        line1: shippingAddress.line1,
        city: shippingAddress.city,
        postal_code: shippingAddress.postalCode,
        country: shippingAddress.country,
      },
      billing_address: {
        full_name: billingAddress.fullName,
        line1: billingAddress.line1,
        city: billingAddress.city,
        postal_code: billingAddress.postalCode,
        country: billingAddress.country,
      },
    },
  });
  return normalizeOrder(order);
}

export async function getOrders() {
  const orders = await apiRequest('/orders');
  return orders.map(normalizeOrder);
}
