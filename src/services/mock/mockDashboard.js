// mockDashboard.js
// MOCK DATA — admin fraud dashboard metrics & recent transaction feed,
// shown until the backend exposes real fraud-monitoring endpoints.

export const mockDashboardSummary = {
  totalTransactions: 1284,
  approved: 1091,
  underReview: 132,
  blocked: 61,
  fraudRate: 4.75, // percent
};

export const mockRecentTransactions = [
  { id: 'MOCK-TXN-98213', riskLevel: 'HIGH', fraudScore: 91, decision: 'BLOCK', timestamp: '2026-08-09T08:12:00Z', amount: 940.0 },
  { id: 'MOCK-TXN-98207', riskLevel: 'MEDIUM', fraudScore: 54, decision: 'REVIEW', timestamp: '2026-08-09T07:58:00Z', amount: 362.5 },
  { id: 'MOCK-TXN-98199', riskLevel: 'LOW', fraudScore: 12, decision: 'APPROVE', timestamp: '2026-08-09T07:41:00Z', amount: 88.0 },
  { id: 'MOCK-TXN-98188', riskLevel: 'HIGH', fraudScore: 84, decision: 'BLOCK', timestamp: '2026-08-09T06:55:00Z', amount: 1210.0 },
  { id: 'MOCK-TXN-98175', riskLevel: 'MEDIUM', fraudScore: 61, decision: 'REVIEW', timestamp: '2026-08-09T06:20:00Z', amount: 415.0 },
  { id: 'MOCK-TXN-98160', riskLevel: 'LOW', fraudScore: 8, decision: 'APPROVE', timestamp: '2026-08-09T05:47:00Z', amount: 54.25 },
];
