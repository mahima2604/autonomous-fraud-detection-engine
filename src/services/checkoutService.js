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
    TransactionID: Math.floor(Math.random() * 1000000) + 3000000, // Generate random ID for test
    TransactionAmt: amount,
    ProductCD: paymentMethod === 'CARD' ? 'W' : 'C',
    
    // IEEE-CIS card defaults for testing
    card1: 13926,
    card3: 150.0,
    card4: "discover",
    card5: 142.0,
    card6: "credit",
    
    // Address defaults for testing
    addr1: 315.0,
    addr2: 87.0,
    dist1: 19.0,
    
    // Counts defaults
    C1: 1.0, C2: 1.0, C3: 0.0, C4: 0.0, C5: 0.0, C6: 1.0, C7: 0.0, 
    C8: 0.0, C9: 1.0, C10: 0.0, C11: 2.0, C12: 0.0, C13: 1.0, C14: 1.0,
    
    // Extract domain from user if possible
    P_emaildomain: user?.email ? user.email.split('@')[1] : "gmail.com",
    
    // Device defaults
    DeviceType: "desktop",
    DeviceInfo: "Windows"
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
