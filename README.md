# Autonomous Fraud Detection and Prevention Engine

An individual B.Tech IT mini project demonstrating e-commerce checkout risk assessment with a Logistic Regression baseline and a GraphSAGE model. The React application talks to a FastAPI backend, which persists customers, transactions, predictions, reviews, and orders with SQLAlchemy and SQLite. Payment status is **simulated**; no payment provider is connected.

## Current behavior

- The storefront reads its small sample catalog from the backend API. It is not a production inventory system.
- Customer registration/login, cart, checkout, fraud verification, order history, and admin fraud review are implemented in the existing application.
- The live fraud model defaults to **GraphSAGE** (`FRAUD_PRIMARY_MODEL`). Select `logistic_regression` to use the saved baseline. Logistic Regression is an optional explicit fallback when `FRAUD_FALLBACK_MODEL=logistic_regression`; fallback is not silent.
- The configured live policy approves scores at or below the review threshold, sends scores through the block threshold for review, and blocks higher scores. The defaults are configured by `FRAUD_REVIEW_THRESHOLD` and `FRAUD_BLOCK_THRESHOLD`.
- Storefront product categories are retained in the backend checkout snapshot. They are not treated as IEEE-CIS `ProductCD` codes. When `ProductCD` is unknown or outside the fitted training categories, the app retains the actual model score and model name but holds the transaction for admin review instead of allowing the score alone to block or approve it. The admin explanation shows the score-based threshold outcome and the manual-review reason. GraphSAGE serving now uses the saved model's `P_emaildomain` and `DeviceInfo` edge schema and the same causal graph builder as training; it reports topology as unvalidated when a required live relationship or connected history is missing.
- Live `P_emaildomain` is derived from the authenticated account email. Live `DeviceInfo` remains unknown because checkout has no trustworthy dataset-equivalent value; `navigator.platform` is not used as an identity. The graph therefore has no `DeviceInfo` links in current checkout, and GraphSAGE stays subject to the existing manual-review safeguard until the displayed topology checks have sufficient genuine data. This does not change fraud scoring or make email verification a legitimacy signal.
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

To create an administrator, run `python -m app.admin_provisioning` from `backend`; it prompts for credentials and does not print the password. Demo-admin bootstrap is disabled unless explicitly enabled for development.

## Environment variables

Names used by the application/configuration:

- `AUTH_TOKEN_SECRET` (required; private, at least 32 characters)
- `VITE_API_BASE_URL`
- `DATABASE_URL` (optional; defaults to the backend SQLite file)
- `CORS_ORIGINS`
- `FRAUD_PRIMARY_MODEL` (`gnn` by default or `logistic_regression`)
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
npm run build
```

The backend tests cover graph behavior, artifact loading/live scoring, checkout persistence, authorization, admin review, and order rules. There is no browser-based frontend test framework configured; the frontend is checked with ESLint and the production build.

## Known limitations

- Dataset source/license and artifact provenance are unresolved in the repository.
- Live `DeviceInfo` has no reliable dataset-equivalent source, so the model receives unknown and cannot create `DeviceInfo` links. The graph uses authentic account email domains where historical values exist and reports insufficient topology data until all trained edge relationships have genuine connected history. See the [DeviceInfo compatibility audit](docs/DeviceInfo-compatibility.md) for the training/live feature comparison and required evidence.
- Dataset-style `ProductCD` is unknown for storefront checkouts; no mapping to catalog categories is assumed. These checkouts are routed to manual review while their score and model are preserved. See the [ProductCD compatibility audit](docs/ProductCD-compatibility.md) for the evidence and per-category decisions.
- The Benchmark page evaluates historical IEEE-CIS data; those metrics do not establish model accuracy for live storefront checkout. Live GraphSAGE uses the saved model's `P_emaildomain` and `DeviceInfo` edge schema, but checkout has no trustworthy `DeviceInfo` value, so live topology remains insufficiently validated. Store categories are not mapped to IEEE-CIS `ProductCD`, and the existing `REVIEW` safeguard remains active when those required inputs or mappings are unavailable.
- The catalog and stock values are sample data; inventory is not reserved/decremented.
- Payment is simulated. No real charge or payment-provider result exists.
- Login abuse controls/rate limiting and browser storage token exposure remain deployment security work.

## Historical journal

[`docs/Project-Journal.md`](docs/Project-Journal.md) contains historical implementation notes. Its mock-auth and mock-service descriptions are superseded by the current backend-integrated implementation documented above.
