import { apiRequest } from './api';

export function sendEmailOtp() {
  return apiRequest('/email-verification/send', { method: 'POST' });
}

export function verifyEmailOtp(code) {
  return apiRequest('/email-verification/verify', { method: 'POST', body: { code } });
}

export function getEmailVerificationStatus() {
  return apiRequest('/email-verification/status');
}
