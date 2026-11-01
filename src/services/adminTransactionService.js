import { apiRequest } from './api';

export function getTransactions() {
  return apiRequest('/admin/transactions');
}

export function getTransactionExplanation(transactionId) {
  return apiRequest(`/admin/transactions/${encodeURIComponent(transactionId)}/explanation`);
}

export function getPendingReviews() {
  return apiRequest('/admin/reviews/pending');
}

export function reassessHighRisk(transactionId) {
  return apiRequest(`/admin/reviews/${encodeURIComponent(transactionId)}/reassess`, {
    method: 'POST',
    body: {},
  });
}

export function approveReview(transactionId, reason, acknowledgeIncompleteGraphEvidence = false) {
  return apiRequest(`/admin/reviews/${encodeURIComponent(transactionId)}/approve`, {
    method: 'POST',
    body: { ...(reason ? { reason } : {}), acknowledge_incomplete_graph_evidence: acknowledgeIncompleteGraphEvidence },
  });
}

export function rejectReview(transactionId, reason) {
  return apiRequest(`/admin/reviews/${encodeURIComponent(transactionId)}/reject`, {
    method: 'POST',
    body: reason ? { reason } : {},
  });
}
