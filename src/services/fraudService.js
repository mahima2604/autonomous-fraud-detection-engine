// Sends checkout transaction data to the authenticated backend fraud endpoint.
import { apiRequest } from './api';

const predictionRequests = new Map();

export function analyzeTransaction(transactionPayload, attemptId) {
  const amount = Number(transactionPayload?.TransactionAmt);
  if (!Number.isFinite(amount) || amount <= 0) {
    throw new Error('Invalid transaction amount. Please check your cart.');
  }

  if (attemptId && predictionRequests.has(attemptId)) {
    return predictionRequests.get(attemptId);
  }

  const request = apiRequest('/fraud/predict', {
    method: 'POST',
    body: { ...transactionPayload, checkout_attempt_id: attemptId },
  }).then((response) => ({
    ...response,
    transactionId: response.transaction_id,
    riskLevel: response.risk_level,
    fraudScore: response.fraud_probability,
    modelUsed: response.model_used,
    isMock: false,
  }));

  if (!attemptId) return request;

  let trackedRequest;
  trackedRequest = request.catch((error) => {
    if (predictionRequests.get(attemptId) === trackedRequest) {
      predictionRequests.delete(attemptId);
    }
    throw error;
  });
  predictionRequests.clear();
  predictionRequests.set(attemptId, trackedRequest);
  return trackedRequest;
}

export async function getRecentFraudPredictions(limit = 10000) {
  const response = await apiRequest(`/admin/fraud/recent?limit=${encodeURIComponent(limit)}`);
  return response.map((prediction) => ({
    ...prediction,
    riskLevel: prediction.risk_level,
    fraudScore: prediction.fraud_probability,
    transactionId: prediction.transaction_id,
  }));
}

export function getFraudSummary() {
  return apiRequest('/admin/fraud/summary');
}

export function getTransactionStatus(transactionId) {
  return apiRequest(`/transactions/${encodeURIComponent(transactionId)}/status`);
}
