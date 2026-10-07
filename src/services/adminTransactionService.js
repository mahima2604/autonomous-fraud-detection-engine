import { apiRequest } from './api';

export function getTransactions() {
  return apiRequest('/admin/transactions');
}
