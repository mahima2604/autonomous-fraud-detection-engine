// fraudService.js
// Sends checkout transaction data for fraud analysis.
//
// The frontend never computes a risk score or decision — it only sends
// the payload and renders whatever { transactionId, riskLevel, fraudScore,
// decision, reasonCodes } comes back. Until POST /api/fraud/analyze is
// live, generateMockFraudResponse (clearly labeled, isolated in
// services/mock/mockFraud.js) stands in for it.

import { apiRequest, USE_MOCKS, mockDelay } from './api';
import { generateMockFraudResponse } from './mock/mockFraud';

export async function analyzeTransaction(transactionPayload) {
  if (
    transactionPayload.TransactionAmt === undefined ||
    transactionPayload.TransactionAmt === null ||
    Number.isNaN(transactionPayload.TransactionAmt)
  ) {
    throw new Error('Invalid transaction amount. Please check your cart.');
  }
  
  if (USE_MOCKS) {
    await mockDelay(1200); // simulate model inference latency
    return generateMockFraudResponse(transactionPayload);
  }
  const response = await apiRequest('/fraud/predict', { method: 'POST', body: transactionPayload });
  // Map snake_case from backend to camelCase for frontend
  return {
    ...response,
    transactionId: response.transaction_id,
    riskLevel: response.risk_level,
    fraudScore: response.fraud_probability,
    isMock: false
  };
}

export async function getRecentFraudPredictions() {
  const response = await apiRequest('/admin/fraud/recent');
  return response.map(r => ({
    ...r,
    riskLevel: r.risk_level,
    fraudScore: r.fraud_probability,
    transactionId: r.transaction_id,
  }));
}

export async function getFraudSummary() {
  return apiRequest('/admin/fraud/summary');
}
