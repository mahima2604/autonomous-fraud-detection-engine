"""Small synthetic sample catalog exposed by the real backend API."""

SAMPLE_CATALOG = [
    {
        "id": "p1", "name": "Aurora Wireless Headphones", "category": "Audio",
        "price": 129.0, "image": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=600&q=80",
        "description": "Over-ear wireless headphones with active noise cancellation and a 30-hour battery life.", "stock": 24,
    },
    {
        "id": "p2", "name": "Pulse Fitness Tracker", "category": "Wearables",
        "price": 79.5, "image": "https://images.unsplash.com/photo-1576243345690-4e4b79b63288?w=600&q=80",
        "description": "A lightweight fitness band with heart-rate monitoring and sleep tracking.", "stock": 41,
    },
    {
        "id": "p3", "name": "Cascade Mechanical Keyboard", "category": "Accessories",
        "price": 149.0, "image": "https://images.unsplash.com/photo-1587829741301-dc798b83add3?w=600&q=80",
        "description": "A compact mechanical keyboard with hot-swappable switches and USB-C connectivity.", "stock": 13,
    },
    {
        "id": "p4", "name": "Nimbus Backpack", "category": "Bags",
        "price": 64.0, "image": "https://images.unsplash.com/photo-1547949003-9792a18a2601?w=600&q=80",
        "description": "A weather-resistant daypack with a padded laptop sleeve.", "stock": 30,
    },
    {
        "id": "p5", "name": "Halo Desk Lamp", "category": "Home",
        "price": 45.0, "image": "https://images.unsplash.com/photo-1507473885765-e6ed057f782c?w=600&q=80",
        "description": "A dimmable LED desk lamp with adjustable color temperature.", "stock": 52,
    },
    {
        "id": "p6", "name": "Orbit Travel Mug", "category": "Home",
        "price": 22.0, "image": "https://images.unsplash.com/photo-1523362628745-0c100150b504?w=600&q=80",
        "description": "A vacuum-insulated stainless-steel travel mug with a leak-proof lid.", "stock": 88,
    },
    {
        "id": "p7", "name": "Vertex Running Shoes", "category": "Footwear",
        "price": 98.0, "image": "https://images.unsplash.com/photo-1542291026-7eec264c27ff?w=600&q=80",
        "description": "Breathable running shoes with responsive foam cushioning.", "stock": 19,
    },
    {
        "id": "p8", "name": "Drift Bluetooth Speaker", "category": "Audio",
        "price": 59.0, "image": "https://images.unsplash.com/photo-1608043152269-423dbba4e7e1?w=600&q=80",
        "description": "A portable, water-resistant Bluetooth speaker with 14-hour playback.", "stock": 37,
    },
]


def get_product(product_id):
    return next((product for product in SAMPLE_CATALOG if product["id"] == product_id), None)
