// validators.js — lightweight client-side form validation helpers.
// These improve UX only; the backend must always re-validate.

export function isValidEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(value || '');
}

export function isNotEmpty(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

export function isValidPostalCode(value) {
  return /^[A-Za-z0-9\- ]{3,10}$/.test(value || '');
}
