// checkoutService.js
// Assembles the transaction payload the fraud + order services expect
// from checkout-form data. Pure data shaping — no network calls here.

/**
 * Builds the transaction payload shared by fraud analysis and order
 * creation. Keeps a clear line between what the frontend can supply
 * and what only the backend can generate.
 */
export function buildTransactionPayload({ user, amount, items = [], paymentMethod, shippingAddress, billingAddress }) {
  return {
    TransactionAmt: amount,
    // Extract domain from user if possible
    P_emaildomain: user?.email ? user.email.split('@')[1] : 'UNKNOWN',
    
    // A browser platform string is not a reliable device identifier for the model.
    DeviceType: /Mobi|Android/i.test(navigator.userAgent) ? "mobile" : "desktop",
    DeviceInfo: 'UNKNOWN',
    checkout_snapshot: {
      items: items.map((item) => ({ product_id: item.id, quantity: item.quantity })),
      payment_method: paymentMethod,
      shipping_address: toBackendAddress(shippingAddress),
      billing_address: toBackendAddress(billingAddress),
    },
  };
}

function toBackendAddress(address = {}) {
  return {
    full_name: address.fullName,
    line1: address.line1,
    city: address.city,
    postal_code: address.postalCode,
    country: address.country,
  };
}

const PENDING_KEY = 'pending_checkout';

/** Persists the in-progress checkout state across Checkout → Fraud → Payment pages. */
function createCheckoutAttemptId() {
  return globalThis.crypto?.randomUUID?.() ?? `checkout-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function savePendingCheckout(data) {
  const pending = { ...data, attemptId: data.attemptId || createCheckoutAttemptId() };
  localStorage.setItem(PENDING_KEY, JSON.stringify(pending));
}

export function getPendingCheckout(currentUserId) {
  try {
    const pending = JSON.parse(localStorage.getItem(PENDING_KEY) || sessionStorage.getItem(PENDING_KEY));
    if (!pending) return null;

    if (currentUserId && String(pending.userId) !== String(currentUserId)) {
      localStorage.removeItem(PENDING_KEY);
      sessionStorage.removeItem(PENDING_KEY);
      return null;
    }

    if (!pending.attemptId) {
      pending.attemptId = createCheckoutAttemptId();
      localStorage.setItem(PENDING_KEY, JSON.stringify(pending));
    }
    return pending;
  } catch {
    return null;
  }
}

export function clearPendingCheckout() {
  localStorage.removeItem(PENDING_KEY);
  sessionStorage.removeItem(PENDING_KEY);
}
