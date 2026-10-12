import { apiRequest } from './api';

export function getTransactions() {
  return apiRequest('/admin/transactions');
}

export function getPendingReviews() {
  return apiRequest('/admin/reviews/pending');
}

export function approveReview(transactionId) {
  return apiRequest(`/admin/reviews/${encodeURIComponent(transactionId)}/approve`, {
    method: 'POST',
    body: {},
  });
}

export function rejectReview(transactionId) {
  return apiRequest(`/admin/reviews/${encodeURIComponent(transactionId)}/reject`, {
    method: 'POST',
    body: {},
  });
}
