// checkoutService.js
// Assembles the transaction payload the fraud + order services expect
// from checkout-form data. Pure data shaping — no network calls here.

/**
 * Builds the transaction payload shared by fraud analysis and order
 * creation. Keeps a clear line between what the frontend can supply
 * and what only the backend can generate.
 */
export function buildTransactionPayload({ user, cartItems, amount, paymentMethod, billingAddress, shippingAddress }) {
  return {
    TransactionAmt: amount,
    ProductCD: paymentMethod === 'CARD' ? 'W' : 'C',
    
    // Extract domain from user if possible
    P_emaildomain: user?.email ? user.email.split('@')[1] : "gmail.com",
    
    // Device info can be legitimately collected from navigator
    DeviceType: /Mobi|Android/i.test(navigator.userAgent) ? "mobile" : "desktop",
    DeviceInfo: navigator.platform
  };
}

const PENDING_KEY = 'pending_checkout';

/** Persists the in-progress checkout state across Checkout → Fraud → Payment pages. */
export function savePendingCheckout(data) {
  sessionStorage.setItem(PENDING_KEY, JSON.stringify(data));
}

export function getPendingCheckout() {
  try {
    return JSON.parse(sessionStorage.getItem(PENDING_KEY));
  } catch {
    return null;
  }
}

export function clearPendingCheckout() {
  sessionStorage.removeItem(PENDING_KEY);
}

function getOrCreateSessionId() {
  let sessionId = sessionStorage.getItem('checkout_session_id');
  if (!sessionId) {
    sessionId = `sess-${Math.random().toString(36).slice(2)}-${Date.now()}`;
    sessionStorage.setItem('checkout_session_id', sessionId);
  }
  return sessionId;
}
