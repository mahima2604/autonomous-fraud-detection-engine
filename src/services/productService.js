// productService.js
// Product catalog access. Uses mockProducts until the backend exposes
// GET /api/products and GET /api/products/{id}.

import { mockDelay } from './api';
import { mockProducts } from './mock/mockProducts';

export async function getProducts() {
  await mockDelay(400);
  return mockProducts;
}

export async function getProductById(id) {
  await mockDelay(300);
  const product = mockProducts.find((p) => p.id === id);
  if (!product) throw new Error('Product not found.');
  return product;
}
