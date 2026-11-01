// productService.js
// Service layer for fetching storefront products from Fake Store API with
// graceful fallback to the backend catalogue, and standardizing product shapes.

import { apiRequest } from './api';

const FAKESTORE_BASE_URL = 'https://fakestoreapi.com';
const FETCH_TIMEOUT_MS = 5000;

/**
 * Normalizes external Fake Store or internal catalog product representations
 * to ensure uniform field presence and data types across UI components.
 */
export function normalizeProduct(item) {
  if (!item || typeof item !== 'object') return null;
  const name = item.title || item.name || 'Untitled Product';
  return {
    id: String(item.id),
    name,
    title: name,
    price: typeof item.price === 'number' ? item.price : Number(item.price) || 0,
    description: item.description || '',
    category: item.category || 'General',
    image: item.image || '',
    stock: typeof item.stock === 'number' ? item.stock : 20,
    ProductCD: item.ProductCD || undefined,
  };
}

async function fetchWithTimeout(url, timeoutMs = FETCH_TIMEOUT_MS) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) {
      throw new Error(`External API responded with status ${response.status}`);
    }
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Evenly interleaves secondary products throughout the primary catalogue
 * so all products appear naturally mixed in the storefront.
 */
export function mixProducts(primaryList = [], secondaryList = []) {
  if (!Array.isArray(secondaryList) || secondaryList.length === 0) return primaryList || [];
  if (!Array.isArray(primaryList) || primaryList.length === 0) return secondaryList || [];
  const result = [];
  const step = Math.max(1, Math.floor(primaryList.length / secondaryList.length));
  let secIdx = 0;
  for (let i = 0; i < primaryList.length; i++) {
    result.push(primaryList[i]);
    if ((i + 1) % step === 0 && secIdx < secondaryList.length) {
      result.push(secondaryList[secIdx++]);
    }
  }
  while (secIdx < secondaryList.length) {
    result.push(secondaryList[secIdx++]);
  }
  return result;
}

/**
 * Fetch product catalog from Fake Store API, falling back to local backend catalog.
 * Display prices from Fake Store API are informative; backend recalculates trusted totals.
 * Exposes backend sample demonstration products (p1..p5) alongside Fake Store products.
 */
export async function getProducts() {
  let fakeStoreProducts = [];
  try {
    const items = await fetchWithTimeout(`${FAKESTORE_BASE_URL}/products`);
    if (Array.isArray(items) && items.length > 0) {
      fakeStoreProducts = items.map(normalizeProduct);
    } else {
      throw new Error('Fake Store API returned an empty product array');
    }
  } catch {
    // Graceful fallback to backend catalogue (contains both Fake Store and sample products)
    const fallbackItems = await apiRequest('/products').catch(() => []);
    if (!Array.isArray(fallbackItems)) return [];
    const normalized = fallbackItems.map(normalizeProduct);
    const sampleItems = normalized.filter((item) => String(item.id).startsWith('p'));
    const regularItems = normalized.filter((item) => !String(item.id).startsWith('p'));
    return sampleItems.length > 0 ? mixProducts(regularItems, sampleItems) : normalized;
  }

  // Fetch backend sample demonstration products (p1..p5) from backend catalogue
  try {
    const backendItems = await apiRequest('/products');
    if (Array.isArray(backendItems) && backendItems.length > 0) {
      const existingIds = new Set(fakeStoreProducts.map((p) => p.id));
      const sampleProducts = backendItems
        .filter((item) => item && (String(item.id).startsWith('p') || !existingIds.has(String(item.id))))
        .map(normalizeProduct);
      return mixProducts(fakeStoreProducts, sampleProducts);
    }
  } catch {
    // In test or offline environments where backend API is unreachable, return Fake Store products
  }

  return fakeStoreProducts;
}

/**
 * Fetch single product by ID from Fake Store API, falling back to local backend catalog.
 * Sample demonstration products (p1..p5) are resolved directly from backend catalogue.
 */
export async function getProductById(id) {
  if (id === undefined || id === null || id === '') {
    throw new Error('Product ID is required');
  }
  const cleanId = String(id).trim();

  // Backend sample demonstration products (p1..p5) resolve directly from backend catalogue
  if (cleanId.startsWith('p')) {
    const item = await apiRequest(`/products/${encodeURIComponent(cleanId)}`);
    return normalizeProduct(item);
  }

  try {
    const item = await fetchWithTimeout(`${FAKESTORE_BASE_URL}/products/${encodeURIComponent(cleanId)}`);
    if (item && item.id !== undefined) {
      return normalizeProduct(item);
    }
    throw new Error(`Product ${cleanId} not found in Fake Store API`);
  } catch {
    // Graceful fallback to backend catalogue item
    const fallbackItem = await apiRequest(`/products/${encodeURIComponent(cleanId)}`);
    return normalizeProduct(fallbackItem);
  }
}
