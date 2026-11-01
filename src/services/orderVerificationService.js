import { apiRequest } from './api';

function toShippingPayload(address = {}) {
  return {
    full_name: address.fullName,
    line1: address.line1,
    locality: address.locality || '',
    city: address.city,
    state: address.state || '',
    postal_code: address.postalCode,
    country: address.country,
  };
}

export function getOrderVerificationStatus(transactionId) {
  return apiRequest(`/orders/${encodeURIComponent(transactionId)}/verification`);
}

export function sendOrderOtp(transactionId, shippingAddress, addressConfirmed) {
  return apiRequest(`/orders/${encodeURIComponent(transactionId)}/verification/send`, {
    method: 'POST',
    body: {
      shipping_address: toShippingPayload(shippingAddress),
      address_confirmed: addressConfirmed === true,
    },
  });
}

export function verifyOrderOtp(transactionId, code) {
  return apiRequest(`/orders/${encodeURIComponent(transactionId)}/verification/verify`, {
    method: 'POST',
    body: { code },
  });
}
