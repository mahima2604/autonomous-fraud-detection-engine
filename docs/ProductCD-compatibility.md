# ProductCD catalog and live checkout compatibility

## Dataset and encoder inspection

`ProductCD` is an opaque categorical feature in the local IEEE-CIS files. The inspected `data/train_transaction.csv` has 590,540 rows: W 439,670; C 68,519; R 37,699; H 33,024; S 11,628. The local test file has 506,691 rows: W 360,987; C 69,266; R 35,647; H 29,373; S 11,418. The saved GraphSAGE encoder includes C, H, R, S, W, plus its reserved `UNKNOWN` value. The saved Logistic Regression encoder includes the five observed codes and has no `UNKNOWN` column. The sampled model-training partition inspected from local data contained the same five observed codes. These values establish encoder compatibility, not a real-world meaning for any code.

## Storefront behavior

The storefront requests product information from Fake Store API through `src/services/productService.js` and uses the backend catalog endpoint when that request is unavailable. Fake Store product categories are not equivalent to IEEE-CIS `ProductCD`; the project has no verified mapping between them.

The backend keeps Fake Store products available for display and checkout pricing but assigns each `ProductCD` as `UNKNOWN`. It obtains product IDs, prices, and codes from its catalog records, validates quantities, and computes totals on the server. A basket with no single validated code also resolves to `UNKNOWN`. The frontend cannot override the backend code or price. Unsupported or unknown codes follow the existing review safeguard; the application does not silently substitute a different code.

The sample catalog products (such as headphones, keyboards, backpacks, etc.) carry backend-verified `ProductCD` mappings (`W`, `C`, `R`, `H`, and `S`) corresponding to the five categories accepted by the fitted encoders. These appear as normal products across the store. No category-to-code inference is made for Fake Store items.

## Historical transactions and prediction limits

Existing transaction records retain their stored prediction and decision history. They are not automatically rescored when catalog configuration changes. The database records inspected for this pass do not include a catalog-mapping version, so the exact mapping revision used for every historical checkout cannot be established from the records alone.

Even when a sample catalog code is accepted by an encoder, that does not establish that a live Fake Store transaction is statistically representative of the IEEE-CIS training data or that its score is accurate. Live checkout feature coverage, including `DeviceInfo`, differs from the historical dataset. See [DeviceInfo compatibility](DeviceInfo-compatibility.md) for the graph evidence limitation.
