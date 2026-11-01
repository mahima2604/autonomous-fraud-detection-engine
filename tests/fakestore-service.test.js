import assert from 'node:assert/strict';
import { after, test } from 'node:test';
import { fileURLToPath } from 'node:url';
import { createServer } from 'vite';

const previousStorage = globalThis.localStorage;
globalThis.localStorage = { getItem: () => null };

const vite = await createServer({
  configFile: false,
  root: fileURLToPath(new URL('..', import.meta.url)),
  logLevel: 'silent',
  server: { middlewareMode: true },
  appType: 'custom',
});

const { getProducts, getProductById, normalizeProduct, mixProducts } = await vite.ssrLoadModule('/src/services/productService.js');

after(async () => {
  await vite.close();
  if (previousStorage === undefined) delete globalThis.localStorage;
  else globalThis.localStorage = previousStorage;
});

test('normalizeProduct standardizes product shapes and defaults missing properties', () => {
  const normalized = normalizeProduct({
    id: 1,
    title: 'Test Jacket',
    price: 49.99,
    description: 'A warm jacket',
    category: "men's clothing",
    image: 'https://example.com/jacket.jpg',
  });

  assert.equal(normalized.id, '1');
  assert.equal(normalized.name, 'Test Jacket');
  assert.equal(normalized.title, 'Test Jacket');
  assert.equal(normalized.price, 49.99);
  assert.equal(normalized.category, "men's clothing");
  assert.equal(normalized.image, 'https://example.com/jacket.jpg');
  assert.equal(normalized.stock, 20);
});

test('getProducts retrieves products from Fake Store API when available', async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    if (String(url).includes('fakestoreapi.com/products')) {
      return new Response(
        JSON.stringify([
          { id: 1, title: 'Item 1', price: 10.5, category: 'cat1', description: 'desc1', image: 'img1.png' },
          { id: 2, title: 'Item 2', price: 20.0, category: 'cat2', description: 'desc2', image: 'img2.png' },
        ]),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    }
    throw new Error('Unexpected URL');
  };

  try {
    const products = await getProducts();
    assert.equal(products.length, 2);
    assert.equal(products[0].id, '1');
    assert.equal(products[0].name, 'Item 1');
    assert.equal(products[0].price, 10.5);
    assert.equal(products[1].id, '2');
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test('getProducts falls back to local backend catalog when Fake Store API fails', async () => {
  const previousFetch = globalThis.fetch;
  let backendCalled = false;

  globalThis.fetch = async (url) => {
    if (String(url).includes('fakestoreapi.com')) {
      throw new Error('Network error reaching Fake Store');
    }
    if (String(url).includes('/api/products')) {
      backendCalled = true;
      return new Response(
        JSON.stringify([
          { id: 'p1', name: 'Fallback Product W', price: 129.0, category: 'Dataset Product W' },
        ]),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    }
    throw new Error(`Unexpected fetch to ${url}`);
  };

  try {
    const products = await getProducts();
    assert.equal(backendCalled, true);
    assert.equal(products.length, 1);
    assert.equal(products[0].id, 'p1');
    assert.equal(products[0].name, 'Fallback Product W');
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test('getProductById retrieves single product or falls back to local backend catalog', async () => {
  const previousFetch = globalThis.fetch;
  let backendProductCalled = false;

  globalThis.fetch = async (url) => {
    if (String(url).includes('fakestoreapi.com/products/99')) {
      return new Response(JSON.stringify({ error: 'Not found' }), { status: 404 });
    }
    if (String(url).includes('/api/products/99')) {
      backendProductCalled = true;
      return new Response(
        JSON.stringify({ id: '99', name: 'Backend Product 99', price: 77.0, category: 'Test' }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    }
    throw new Error(`Unexpected fetch to ${url}`);
  };

  try {
    const product = await getProductById('99');
    assert.equal(backendProductCalled, true);
    assert.equal(product.id, '99');
    assert.equal(product.name, 'Backend Product 99');
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test('mixProducts interleaves secondary items evenly into primary items', () => {
  const primary = [{ id: '1' }, { id: '2' }, { id: '3' }, { id: '4' }, { id: '5' }, { id: '6' }];
  const secondary = [{ id: 'p1' }, { id: 'p2' }];
  const mixed = mixProducts(primary, secondary);
  assert.equal(mixed.length, 8);
  // With step = 6 / 2 = 3: index 3 is p1, index 7 is p2
  assert.deepEqual(mixed.map((item) => item.id), ['1', '2', '3', 'p1', '4', '5', '6', 'p2']);
});

test('getProducts merges backend sample demonstration products alongside Fake Store API items', async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async (url) => {
    if (String(url).includes('fakestoreapi.com/products')) {
      return new Response(
        JSON.stringify([
          { id: 1, title: 'Item 1', price: 10.5, category: 'cat1', description: 'desc1', image: 'img1.png' },
        ]),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    }
    if (String(url).includes('/api/products')) {
      return new Response(
        JSON.stringify([
          { id: 1, name: 'Item 1', price: 10.5, category: 'cat1', ProductCD: 'UNKNOWN' },
          { id: 'p1', name: 'Aurora Wireless Headphones', price: 129.0, category: 'Audio', ProductCD: 'W' },
          { id: 'p2', name: 'Pulse Fitness Tracker', price: 79.5, category: 'Wearables', ProductCD: 'C' },
        ]),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    }
    throw new Error(`Unexpected URL: ${url}`);
  };

  try {
    const products = await getProducts();
    assert.equal(products.length, 3);
    assert.equal(products[0].id, '1');
    assert.equal(products[1].id, 'p1');
    assert.equal(products[1].name, 'Aurora Wireless Headphones');
    assert.equal(products[1].ProductCD, 'W');
    assert.equal(products[2].id, 'p2');
    assert.equal(products[2].ProductCD, 'C');
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test('getProductById retrieves backend sample product directly', async () => {
  const previousFetch = globalThis.fetch;
  let backendCalled = false;
  let fakeStoreCalled = false;

  globalThis.fetch = async (url) => {
    if (String(url).includes('fakestoreapi.com')) {
      fakeStoreCalled = true;
      throw new Error('Fake Store API should not be queried for sample products');
    }
    if (String(url).includes('/api/products/p1')) {
      backendCalled = true;
      return new Response(
        JSON.stringify({
          id: 'p1',
          name: 'Aurora Wireless Headphones',
          price: 129.0,
          category: 'Audio',
          ProductCD: 'W',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } }
      );
    }
    throw new Error(`Unexpected URL: ${url}`);
  };

  try {
    const product = await getProductById('p1');
    assert.equal(backendCalled, true);
    assert.equal(fakeStoreCalled, false);
    assert.equal(product.id, 'p1');
    assert.equal(product.name, 'Aurora Wireless Headphones');
    assert.equal(product.ProductCD, 'W');
  } finally {
    globalThis.fetch = previousFetch;
  }
});
