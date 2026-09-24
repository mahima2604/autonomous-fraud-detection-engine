// mockFraud.js
// MOCK FRAUD SERVICE
// ------------------------------------------------------------------
// This file does NOT implement fraud detection. It does not score,
// weigh, or evaluate transactions in any way. It exists only so the
// frontend UI has something to render before the real backend
// (Spring Boot + GNN service) is available.
//
// The response shape mirrors the documented backend contract:
//   { transactionId, riskLevel, fraudScore, decision, reasonCodes }
//
// Selection here is a deliberately simple, clearly-labeled placeholder
// (cycles through outcomes / can be forced via amount thresholds for
// demoing the three UI states) — it must be deleted, not adapted, once
// POST /api/fraud/analyze is live.

let callCount = 0;

const REASON_CODES = {
  LOW: ['DEVICE_RECOGNIZED', 'BILLING_SHIPPING_MATCH'],
  MEDIUM: ['NEW_DEVICE', 'SHIPPING_BILLING_MISMATCH'],
  HIGH: ['VELOCITY_ANOMALY', 'HIGH_RISK_REGION', 'MULTIPLE_FAILED_ATTEMPTS'],
};

export function generateMockFraudResponse(transactionPayload) {
  callCount += 1;

  // Deliberately simple placeholder logic — NOT a fraud model.
  // Lets graders/testers exercise all three UI states predictably.
  let riskLevel = 'LOW';
  if (transactionPayload.amount > 800) {
    riskLevel = 'HIGH';
  } else if (transactionPayload.amount > 300 || callCount % 4 === 0) {
    riskLevel = 'MEDIUM';
  }

  const decisionMap = { LOW: 'APPROVE', MEDIUM: 'REVIEW', HIGH: 'BLOCK' };
  const scoreRangeMap = { LOW: [2, 25], MEDIUM: [40, 65], HIGH: [78, 97] };
  const [min, max] = scoreRangeMap[riskLevel];
  const fraudScore = Math.floor(min + Math.random() * (max - min));

  return {
    transactionId: `MOCK-TXN-${Date.now()}`,
    riskLevel,
    fraudScore,
    decision: decisionMap[riskLevel],
    reasonCodes: REASON_CODES[riskLevel],
    isMock: true,
  };
}
