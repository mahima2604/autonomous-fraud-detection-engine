// CartContext.jsx
// Global cart state, scoped per authenticated user and persisted to
// localStorage. When a user logs in, switches accounts, or creates a new ID,
// the previous user's cart is not leaked and the active account's cart is loaded.

import { createContext, useContext, useEffect, useState } from 'react';
import { useAuth } from './AuthContext';

const CartContext = createContext(null);

function getCartStorageKey(user) {
  if (user?.id) return `cart_items_user_${user.id}`;
  if (user?.email) return `cart_items_user_${encodeURIComponent(user.email)}`;
  return 'cart_items_guest';
}

function loadCart(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function CartProvider({ children }) {
  const { user } = useAuth();
  const currentKey = getCartStorageKey(user);

  const [cartState, setCartState] = useState(() => {
    try {
      localStorage.removeItem('cart_items');
    } catch {}

    return {
      key: currentKey,
      items: loadCart(currentKey),
    };
  });

  // When active user/key changes (e.g. logging into another account, registering, or logging out),
  // update the cart state immediately to the active account's cart.
  if (cartState.key !== currentKey) {
    setCartState({
      key: currentKey,
      items: loadCart(currentKey),
    });
  }

  useEffect(() => {
    if (cartState.key === currentKey) {
      try {
        localStorage.setItem(currentKey, JSON.stringify(cartState.items));
      } catch (err) {
        console.error('Failed to persist cart items', err);
      }
    }
  }, [cartState.items, cartState.key, currentKey]);

  function addItem(product, quantity = 1) {
    setCartState((prev) => {
      const existing = prev.items.find((i) => i.id === product.id);
      let nextItems;
      if (existing) {
        nextItems = prev.items.map((i) =>
          i.id === product.id ? { ...i, quantity: i.quantity + quantity } : i
        );
      } else {
        nextItems = [
          ...prev.items,
          { id: product.id, name: product.name, price: product.price, image: product.image, quantity },
        ];
      }
      return { ...prev, items: nextItems };
    });
  }

  function removeItem(productId) {
    setCartState((prev) => ({
      ...prev,
      items: prev.items.filter((i) => i.id !== productId),
    }));
  }

  function increaseQuantity(productId) {
    setCartState((prev) => ({
      ...prev,
      items: prev.items.map((i) => (i.id === productId ? { ...i, quantity: i.quantity + 1 } : i)),
    }));
  }

  function decreaseQuantity(productId) {
    setCartState((prev) => ({
      ...prev,
      items: prev.items
        .map((i) => (i.id === productId ? { ...i, quantity: i.quantity - 1 } : i))
        .filter((i) => i.quantity > 0),
    }));
  }

  function clearCart() {
    setCartState((prev) => ({ ...prev, items: [] }));
    try {
      localStorage.removeItem(currentKey);
    } catch {}
  }

  const items = cartState.items;
  const subtotal = items.reduce((sum, i) => sum + i.price * i.quantity, 0);
  const itemCount = items.reduce((sum, i) => sum + i.quantity, 0);

  const value = {
    items,
    addItem,
    removeItem,
    increaseQuantity,
    decreaseQuantity,
    clearCart,
    subtotal,
    itemCount,
  };

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

export function useCart() {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error('useCart must be used within a CartProvider');
  return ctx;
}
