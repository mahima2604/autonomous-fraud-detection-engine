import { apiRequest } from './api';

export function getCustomers() {
  return apiRequest('/admin/customers');
}

export function getCustomerDetails(customerId) {
  return apiRequest(`/admin/customers/${encodeURIComponent(customerId)}`);
}
