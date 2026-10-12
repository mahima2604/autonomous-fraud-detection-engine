import { apiRequest } from './api';

export function getProducts() {
  return apiRequest('/products');
}

export function getProductById(id) {
  return apiRequest(`/products/${encodeURIComponent(id)}`);
}
