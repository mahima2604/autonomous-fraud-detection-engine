# Autonomous Fraud Detection and Prevention Engine

An individual B.Tech IT mini project demonstrating e-commerce checkout risk assessment with a Logistic Regression baseline and a GraphSAGE model. The React application talks to a FastAPI backend, which persists customers, transactions, predictions, reviews, and orders with SQLAlchemy and SQLite. Payment status is **simulated**; no payment provider is connected.

## Current behavior

- The storefront reads its small sample catalog from the backend API. It is not a production inventory system.
- Customer registration/login, cart, checkout, fraud verification, order history, and admin fraud review are implemented in the existing application.
- The live fraud model defaults to **GraphSAGE DeviceInfo v2** (`FRAUD_PRIMARY_MODEL=gnn_device_v2`). Its versioned DeviceInfo input is a coarse OS-family hint; the original model remains available with `FRAUD_PRIMARY_MODEL=gnn`. Select `logistic_regression` to use the saved baseline. Logistic Regression is an optional explicit fallback when `FRAUD_FALLBACK_MODEL=logistic_regression`; fallback is not silent.
- The live score thresholds default to 0.30 and 0.70 and are configured by `FRAUD_REVIEW_THRESHOLD` and `FRAUD_BLOCK_THRESHOLD`. These are policy cutoffs, not calibrated probabilities. LOW scores can continue only after the backend verifies the account email and confirmed shipping address and the ProductCD passes validation. MEDIUM scores use the existing order-specific email OTP and address/account-history and available graph-evidence reassessment. Unsupported or unavailable ProductCD values are held for administrator review. Model/graph execution errors fail closed: without the explicitly configured fallback, assessment returns unavailable; fallback results are held for review. A successfully built but incomplete graph remains marked unvalidated: MEDIUM follows the documented OTP/reassessment policy, while HIGH remains held for an explicit, reasoned administrator decision and retains its HIGH label and score-based BLOCK outcome. These safeguards are not proof of fraud or automatic rejection. The original score is not adjusted after OTP.
- The storefront catalog presents normal e-commerce products (such as headphones, keyboards, backpacks, etc.) alongside Fake Store items. Five catalog products have verified, backend-configured `ProductCD` mappings (`W`, `C`, `R`, `H`, and `S`) corresponding to categories accepted by the fitted encoders. The backend derives `ProductCD` from catalog records, ignores client-supplied codes and prices, and computes totals from trusted prices and quantities. A basket mixing codes has no single transaction code and remains `UNKNOWN` for review. V2 GraphSAGE uses authenticated `P_emaildomain` edges only; v1 retains its saved `P_emaildomain` and `DeviceInfo` edge schema. Missing or unvalidated live graph context remains visible to review. Model probabilities have not been calibrated against labeled storefront checkout data, so the configured cutoffs are not validated storefront probabilities.
- The original v1 `DeviceInfo` is heterogeneous and remains unknown in v1 checkout. V2 defines the `DeviceInfo` input as a coarse platform family derived from training `id_30` and a small browser platform allowlist. It is a categorical input only: v2 creates graph edges from authenticated email domain, never from platform, and does not treat an OS family as a device identity. Unsupported values stay `UNKNOWN`. ProductCD validation and mandatory administrator review are unchanged.
- In the checked-in training data’s sampled training partition, `ProductCD` has no missing rows. Its reserved GraphSAGE `UNKNOWN` embedding therefore has no training examples; serving neutralizes that embedding in memory rather than using its random initialization. New training metadata records unknown-category counts for this check.

## Requirements and setup

Use a Python installation able to install `backend/requirements.txt`, and Node.js/npm able to install the versions in `package-lock.json`.

```powershell
cd D:\fraud-detection-app-codex
npm ci
Copy-Item .env.example .env
```

Set a private random `AUTH_TOKEN_SECRET` of at least 32 characters in the project-root `.env`. For local setup, generate one with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and paste the output after `AUTH_TOKEN_SECRET=`. Do not commit or share `.env`. The backend explicitly loads this repository-root file whether launched from the repository root or `backend`; a nonempty process environment variable takes precedence. See the environment-variable list below. The default database is `backend/fraud_app.db`; set `DATABASE_URL` to select another database. Startup creates missing tables and applies the existing additive schema updates without replacing existing rows.

Install and run the backend in a second PowerShell terminal:

```powershell
cd D:\fraud-detection-app-codex\backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Run the frontend in another terminal:

```powershell
cd D:\fraud-detection-app-codex
npm run dev
```

Checkout address lookup uses Leaflet with OpenStreetMap tiles and Photon (OpenStreetMap data) search/reverse geocoding. Leaflet is included in the frontend dependencies. Search runs only when the customer submits the search form; the browser waits briefly before sending a request and cancels the previous request, which keeps requests modest. Public geocoding and tile services can be slow, rate-limited, or unavailable and do not guarantee a complete or correct address. Customers can always edit the fields and must explicitly confirm the delivery address. Browser location is requested only after clicking **Use my current location**; denying permission leaves manual entry and search available. Location requires a secure context (HTTPS, or localhost) and browser permission. The application does not claim delivery serviceability.

To create an administrator, run `python -m app.admin_provisioning` from `backend`; it prompts for credentials and does not print the password. Demo-admin bootstrap is disabled unless explicitly enabled for development.

## Environment variables

Names used by the application/configuration:

- `AUTH_TOKEN_SECRET` (required; private, at least 32 characters)
- `VITE_API_BASE_URL`
- `DATABASE_URL` (optional; defaults to the backend SQLite file)
- `CORS_ORIGINS`
- `FRAUD_PRIMARY_MODEL` (`gnn_device_v2` by default, or `gnn` / `logistic_regression`)
- `FRAUD_FALLBACK_MODEL` (empty by default or `logistic_regression`)
- `FRAUD_REVIEW_THRESHOLD`, `FRAUD_BLOCK_THRESHOLD`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM_EMAIL` (backend email OTP delivery; no development OTP fallback)
- `ENABLE_DEMO_ADMIN`, `APP_ENV`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` (demo bootstrap only; development only)

The admin UI does not itself enforce HTTPS; deploy behind HTTPS before sending credentials over a network.

## Email OTP setup

Checkout sends a server-generated six-digit code to the email address on the authenticated backend user record. The request does not accept a destination email from the browser. Configure these values in the backend process environment or the project-root `.env` file; do not use `VITE_` variables:

- `SMTP_HOST` — SMTP server name, such as `smtp.gmail.com`
- `SMTP_PORT` — STARTTLS port; defaults to `587`
- `SMTP_USERNAME` — SMTP login, usually your full sender email address
- `SMTP_PASSWORD` — SMTP password or app-specific password
- `SMTP_FROM_EMAIL` — approved sender address

Gmail is a possible no-cost option for a demonstration. Enable 2-Step Verification on the Google account, create an App Password, then use `smtp.gmail.com`, port `587`, the account email as `SMTP_USERNAME` and `SMTP_FROM_EMAIL`, and the App Password as `SMTP_PASSWORD`. Google may restrict App Password availability by account type or organization policy; check Gmail's current sending limits and test delivery to your own inbox. Do not use the account's normal sign-in password. Other SMTP providers can be configured with their STARTTLS host, port, username, password, and sender address.

If SMTP settings are missing or delivery fails, the API returns an error and checkout cannot continue. No test OTP is returned to the browser. OTPs expire after 10 minutes, verification is limited to 5 attempts, resend cooldown is 30 seconds, and requests are limited to 3 per email and account in a 30-minute window. Verification is stored against the signed-in user and current account email, lasts 24 hours, and becomes invalid if that account email changes. The database stores an HMAC hash of the code; a successful code is cleared and cannot be reused.

Account/login email verification and order verification are separate. After fraud assessment (and any required administrator approval), the customer reviews the saved shipping address and requests a fresh email OTP for that specific checkout attempt. Order codes expire after 10 minutes, allow 5 incorrect attempts, have a 30-second resend cooldown, and are limited to 3 sends per attempt and 10 sends per account per 30-minute window. Resending replaces the prior code. The backend stores only an HMAC hash and binds the challenge to the user, account email, transaction/checkout attempt, and normalized shipping-address hash. The backend consumes the verification in the same database transaction that creates the order; repeating an already completed order attempt returns that order idempotently. Existing databases are upgraded at startup using the existing additive migration approach: `order_verifications` is created and the two account send-limit columns are added to `users`.

The order step displays the persisted address for a separate explicit review/confirmation. This records customer intent for this checkout and protects against address changes after review; it does not prove the recipient lives there or establish delivery serviceability. The initial checkout address confirmation and format validation remain separate from the order email OTP.

Every checkout attempt still requires this fresh order-specific OTP even when the account email is already verified. The payment page's explicit “Confirm address and send order code” action starts the challenge; loading or refreshing the page only reads challenge status. The send endpoint also requires an explicit address-confirmation signal and checks that the submitted normalized address matches the assessed checkout snapshot.

Available simulated methods are Credit / Debit Card, PayPal, Bank Transfer, and Cash on Delivery (COD). No payment credentials are collected. Non-COD methods keep the existing `SIMULATED` status; COD orders use `PENDING_CASH_COLLECTION` and are not marked paid.

## High-risk checkout reassessment

The score thresholds remain `FRAUD_REVIEW_THRESHOLD` (default `0.30`) and `FRAUD_BLOCK_THRESHOLD` (default `0.70`). A score above the block threshold retains its score-based `BLOCK` outcome and HIGH risk level; the storefront operational state is `REVIEW`/hold so an administrator can act. These values are policy cutoffs, not calibrated storefront fraud probabilities. The prediction record and API expose both `score_based_decision` and the separate operational `decision`.

Every new storefront transaction stays in operational `REVIEW`, regardless of score band, OTP, address confirmation, or platform hint. Score-based outcome remains separate from operational state. Order creation stays blocked until an authorized administrator records approval; rejection remains terminal. OTP/address and risk reassessment provide evidence but cannot release an order.

Before a high-risk decision, an administrator must run the backend reassessment. It records format/confirmation checks, recent account checkout/order counts, normalized-address order/account counts, and any cancellation/refusal-like statuses the local order database actually contains. A shared address is reported as contextual evidence and never flags fraud by itself. The current application has no external carrier or delivery-outcome feed; absence of cancellation/refusal records means no such history was available. Address and transaction history scans are bounded to the newest 5,000 rows and the response says when that scan may have been truncated.

The reassessment reconstructs the graph for the specific saved model version. V1 uses `P_emaildomain` and `DeviceInfo`; missing v1 DeviceInfo remains unvalidated. V2 uses authenticated email-domain edges only; its coarse platform-family input never creates edges. Incomplete required topology remains visible and is not reported as validated. High-risk approval still requires a current reassessment, reason, and explicit acknowledgment of incomplete topology when applicable. No score, risk level, or model decision is rewritten by reassessment or administrator review.

### Historical model evaluation

The original v1 benchmark on the chronological IEEE-CIS test split reports ROC-AUC 0.7411 and PR-AUC 0.1367 for GraphSAGE. The separately trained v2 model reports ROC-AUC 0.7428 and PR-AUC 0.1270 on the same-sized held-out partition. V2 has slightly higher ROC-AUC and lower PR-AUC; these results do not establish an overall accuracy improvement or storefront calibration. Both use actual labeled IEEE-CIS data and the existing chronological split; no benchmark cache or v1 artifact was changed.

## Data and model artifacts

Training expects these locally available files under `data/`:

- `train_transaction.csv`
- `train_identity.csv`

Separate `test_transaction.csv` and `test_identity.csv` files are also present locally, but the current training code does not consume them; it evaluates on the labeled training data’s held-out chronological partition. `data/` is Git-ignored and no authoritative source URL, license, or redistribution permission is documented in this repository. Verify those terms independently before sharing the data or artifacts.

Training uses `isFraud` as its label, joins on `TransactionID`, sorts by `TransactionDT`, splits 70/15/15 chronologically, and samples legitimate rows only from the training partition. Preprocessing is fitted on the sampled training partition. Evaluation records standard metrics at threshold 0.5 and binary metrics at both configured live-policy cutoffs. The saved metadata contains prior evaluation results; those values have not been independently reproduced in this documentation update.

Run training/evaluation from `backend` with an output directory separate from the active artifacts:

```powershell
cd D:\fraud-detection-app-codex\backend
python -m app.ml.train --output-dir models\candidate-run --epochs 30
```

This requires the training CSVs and can be resource-intensive. The separate output directory prevents the active files in `backend/models/` from being overwritten. Inspect and validate candidate artifacts before selecting them for serving. Do not load model artifacts from untrusted sources: the Logistic Regression pipeline and encoders/scalers use joblib serialization.

## Tests and quality checks

```powershell
cd D:\fraud-detection-app-codex\backend
python -m pytest -q
cd D:\fraud-detection-app-codex
npm run lint
npm test
npm run build
```

The backend tests cover graph behavior, artifact loading/live scoring, checkout persistence, authorization, admin review, and order rules, including order OTP scope and replay protections. Frontend tests use Node's built-in test runner for address/geocoding and API service behavior; the frontend is also checked with ESLint and the production build.

## Known limitations

- Dataset source/license and artifact provenance are unresolved in the repository.
- V2's `DeviceInfo` means a coarse client-reported OS family, trained from IEEE-CIS `id_30`, not the original heterogeneous v1 field. It is a model input only, is allowlist-normalized, and never creates device edges or proves physical identity. Browser hints are spoofable; missing and unsupported values stay `UNKNOWN`. V1 remains selectable and retains its original behavior. See the [DeviceInfo compatibility audit](docs/DeviceInfo-compatibility.md).
- Catalog `ProductCD` codes were checked against the local transaction data and fitted encoders. A selected code does not make a live transaction equivalent to historical IEEE-CIS data. Mixed-code and unsupported values stay on review; no real-world category meaning is inferred. See the [ProductCD compatibility audit](docs/ProductCD-compatibility.md) for raw and sampled frequencies and the serving behavior.
- The Benchmark page evaluates historical IEEE-CIS data; those metrics do not establish model accuracy for live storefront checkout. V2 graph topology uses only `P_emaildomain`; platform-family DeviceInfo values never form graph links. Catalog labels convey only opaque dataset codes and do not imply a semantic code-to-product mapping.
- The catalog and stock values are sample data; inventory is not reserved/decremented.
- Payment is simulated. No real charge or payment-provider result exists.
- Login abuse controls/rate limiting and browser storage token exposure remain deployment security work.

## Historical journal

[`docs/Project-Journal.md`](docs/Project-Journal.md) contains historical implementation notes. Its mock-auth and mock-service descriptions are superseded by the current backend-integrated implementation documented above.
