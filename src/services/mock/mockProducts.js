// mockProducts.js
// MOCK DATA — isolated so it can be deleted the moment GET /api/products
// and GET /api/products/{id} are live. Nothing outside productService.js
// should import from this file directly.

export const mockProducts = [
  {
    id: 'p1',
    name: 'Aurora Wireless Headphones',
    category: 'Audio',
    price: 129.0,
    image: 'https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=600&q=80',
    description:
      'Over-ear wireless headphones with active noise cancellation and a 30-hour battery life. Built for daily commutes and long focus sessions.',
    stock: 24,
  },
  {
    id: 'p2',
    name: 'Pulse Fitness Tracker',
    category: 'Wearables',
    price: 79.5,
    image: 'https://images.unsplash.com/photo-1576243345690-4e4b79b63288?w=600&q=80',
    description:
      'Lightweight fitness band with heart-rate monitoring, sleep tracking, and 7-day battery life. Water resistant up to 50m.',
    stock: 41,
  },
  {
    id: 'p3',
    name: 'Cascade Mechanical Keyboard',
    category: 'Accessories',
    price: 149.0,
    image: 'https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=600&q=80',
    description:
      'Compact 75% mechanical keyboard with hot-swappable switches and per-key RGB lighting. USB-C detachable cable.',
    stock: 13,
  },
  {
    id: 'p4',
    name: 'Nimbus Backpack',
    category: 'Bags',
    price: 64.0,
    image: 'https://images.unsplash.com/photo-1547949003-9792a18a2601?w=600&q=80',
    description:
      'Weatherproof 22L daypack with a padded 15" laptop sleeve and a magnetic chest strap. Fits airline carry-on limits.',
    stock: 30,
  },
  {
    id: 'p5',
    name: 'Halo Desk Lamp',
    category: 'Home',
    price: 45.0,
    image: 'https://images.unsplash.com/photo-1507473885765-e6ed057f782c?w=600&q=80',
    description:
      'Dimmable LED desk lamp with adjustable color temperature and a built-in USB-C charging port.',
    stock: 52,
  },
  {
    id: 'p6',
    name: 'Orbit Travel Mug',
    category: 'Home',
    price: 22.0,
    image: 'https://images.unsplash.com/photo-1523362628745-0c100150b504?w=600&q=80',
    description:
      'Vacuum-insulated stainless steel mug that keeps drinks hot for 6 hours or cold for 12. Leak-proof lid.',
    stock: 88,
  },
  {
    id: 'p7',
    name: 'Vertex Running Shoes',
    category: 'Footwear',
    price: 98.0,
    image: 'https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600&q=80',
    description:
      'Breathable knit running shoes with responsive foam cushioning, designed for daily training miles.',
    stock: 19,
  },
  {
    id: 'p8',
    name: 'Drift Bluetooth Speaker',
    category: 'Audio',
    price: 59.0,
    image: 'https://images.unsplash.com/photo-1608043152269-423dbba4e7e1?w=600&q=80',
    description:
      'Portable speaker with 360° sound, IPX7 waterproofing, and 14-hour playback.',
    stock: 37,
  },
];
