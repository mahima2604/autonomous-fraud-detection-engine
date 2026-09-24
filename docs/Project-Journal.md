# Project Journal — Frontend

Concise technical record of the frontend implementation for the Autonomous
Fraud Detection and Prevention Engine e-commerce app. Backend, database,
and GNN fraud model are out of scope for this journal (implemented
separately).

## Stack
React 18 + Vite + JavaScript (no TypeScript), React Router 6, Context API
for global state, plain CSS (design tokens in `src/index.css`). No Redux,
no UI framework.

## What was implemented

**Routing** (`src/routes/AppRoutes.jsx`) — all 12 routes from the spec,
split across two shells: `MainLayout` (storefront: navbar/footer) and
`AdminLayout` (fraud dashboard). `checkout`, `fraud-verification`,
`payment`, `order-success`, and `orders` are wrapped in `ProtectedRoute`
(redirects to `/login`, preserving intended destination via router state).

**Auth** (`context/AuthContext.jsx`, `services/authService.js`) — mock
login/register backed by a `mock_users` array in `localStorage`. Session
persisted via `auth_token` / `auth_user` in `localStorage`. Clearly
labeled as insecure/mock in code comments; not a stand-in for real backend
auth.

**Cart** (`context/CartContext.jsx`) — add/remove/increase/decrease/clear,
persisted to `localStorage` under `cart_items`. Subtotal/item count
derived, not stored.

**Products** (`services/productService.js` + `services/mock/mockProducts.js`)
— 8 mock products across categories, category filter on the listing page,
loading/error/empty states.

**Checkout → Fraud Verification → Payment flow** — the core project-specific
feature:
1. `Checkout.jsx` collects shipping/billing + payment method, builds a
   transaction payload via `checkoutService.buildTransactionPayload`
   (explicitly documents which fields are frontend-collected vs. left for
   the backend, e.g. `deviceId`/`ipAddress` are NOT collected client-side),
   and stashes it in `sessionStorage` (`pending_checkout`).
2. `FraudVerification.jsx` calls `fraudService.analyzeTransaction`, which
   (while `VITE_USE_MOCKS=true`) delegates to `services/mock/mockFraud.js`.
   That mock file is explicitly commented as **not** a fraud model — it's a
   labeled placeholder returning the same `{ transactionId, riskLevel,
   fraudScore, decision, reasonCodes }` shape the real backend will return.
   The UI (`FraudStatusCard.jsx`) only renders whatever it receives and
   branches on `decision` (APPROVE / REVIEW / BLOCK) for what button to
   show next — it contains no scoring logic.
3. `Payment.jsx` simulates payment (`paymentService.js`, no gateway, no
   card storage) and creates an order (`orderService.js`), then clears
   cart + pending checkout state and routes to `OrderSuccess.jsx`.

**Order history** (`Orders.jsx`) — mock data table with status badges.

**Admin fraud dashboard** (`pages/admin/FraudDashboard.jsx`) — summary
metric cards + recent-transactions table, backed by
`services/mock/mockDashboard.js`. No ML logic; purely display.

## API service layer
`src/services/` — `api.js` (base URL from `VITE_API_BASE_URL`, `USE_MOCKS`
flag from `VITE_USE_MOCKS`, shared `apiRequest` fetch wrapper),
`authService.js`, `productService.js`, `checkoutService.js`,
`fraudService.js`, `paymentService.js`, `orderService.js`. UI components
never call `fetch` directly. Every service function branches on
`USE_MOCKS`: `true` → local mock data/logic, `false` → real `apiRequest`
call to the documented endpoint. Flipping `VITE_USE_MOCKS=false` once the
backend is up should require no UI changes.

## Mock data (isolated in `src/services/mock/`)
`mockProducts.js`, `mockOrders.js`, `mockFraud.js`, `mockDashboard.js` —
each file-header comments state it is mock-only and names the backend
endpoint that replaces it.

## Backend endpoints expected
```
POST /api/auth/login
POST /api/auth/register
GET  /api/products
GET  /api/products/{id}
POST /api/orders
GET  /api/orders
POST /api/fraud/analyze
POST /api/payment/process
```
The admin dashboard additionally expects (not in the original list, added
because the dashboard needs a data source):
```
GET /api/admin/fraud/summary
GET /api/admin/fraud/recent
```

## Environment variables
`.env.example`:
```
VITE_API_BASE_URL=http://localhost:8080/api
VITE_USE_MOCKS=true
```

## What still needs backend integration
- Set `VITE_USE_MOCKS=false` and confirm each service's `apiRequest` call
  matches the real backend's request/response shape exactly.
- Real auth token handling (refresh, expiry) once backend auth exists.
- `deviceId` / `ipAddress` are intentionally NOT collected client-side —
  confirm how the backend wants to derive/receive these.
- Admin dashboard summary/recent-transactions endpoints don't exist yet in
  the documented contract — need to be defined with the backend team.
