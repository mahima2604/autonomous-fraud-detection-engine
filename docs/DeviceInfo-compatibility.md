# IEEE-CIS device feature compatibility

## Finding

Live checkout does not collect a trustworthy value compatible with the saved model's `DeviceInfo` feature. The backend deliberately sets that feature to `UNKNOWN` for the current transaction and all historical serving nodes. The graph builder excludes `UNKNOWN` relationship keys, so checkout currently creates no `DeviceInfo` edges. The prediction explanation reports the resulting topology as insufficient; that status must remain unvalidated.

## What the training data establishes

The official competition documentation places both `DeviceType` and `DeviceInfo` in the separate identity table, joined to transaction rows by `TransactionID`; identity rows are unavailable for many transactions. NVIDIA's write-up by the competition's winning team describes this identity data as including network connection information and a digital signature involving user-agent, browser, operating system, and version information. The Kaggle page and available project files do not provide a canonical field-level extraction specification or a mapping from browser observations to `DeviceInfo` values. [Kaggle dataset description](https://www.kaggle.com/c/ieee-fraud-detection/data) · [NVIDIA competition analysis](https://developer.nvidia.com/blog/leveraging-machine-learning-to-detect-fraud-tips-to-develop-a-winning-kaggle-solution/)

Local inspection found:

| Source | Verified local facts |
| --- | --- |
| `data/train_identity.csv` | 144,233 rows; 140,810 nonmissing `DeviceType` values; 118,666 nonmissing `DeviceInfo` values; 1,786 distinct nonmissing `DeviceInfo` strings. |
| `DeviceType` values | `desktop` (85,165), `mobile` (55,645), and 3,423 missing values. |
| `DeviceInfo` values | Heterogeneous labels including OS names, browser/runtime-like strings, and device/build-style names. The raw values do not establish that this is a stable hardware identifier or a raw browser user-agent field. |
| Saved GraphSAGE encoder | `DeviceType` has 3 classes including `UNKNOWN`; `DeviceInfo` has 915 classes including `UNKNOWN`. These are fitted on the sampled training partition, not all raw identity rows. |
| Saved GraphSAGE graph schema | Input features include both fields; edge columns are `P_emaildomain` and `DeviceInfo`; the causal builder connects equal, nonmissing raw values to up to 10 earlier nodes. |

The source documentation supports that these are identity/device-related categorical features. It does not prove that every `DeviceInfo` string has one uniform meaning, nor does it give a canonical rule to derive the training value from an arbitrary browser request. The sampled encoder's class list is not a semantic dictionary.

## What live checkout collects

`src/services/checkoutService.js` applies `/Mobi|Android/i` to `navigator.userAgent` and sends only `DeviceType="mobile"` or `"desktop"`. It sends `DeviceInfo="UNKNOWN"`; it does not send the full user-agent, operating system, browser version, device model, or a stable device identifier. The backend independently normalizes the coarse type to `desktop`, `mobile`, or `UNKNOWN` and overwrites `DeviceInfo` with `UNKNOWN`, including for historical graph nodes.

The observed training `DeviceType` vocabulary matches the two strings produced by the current client heuristic. That establishes a vocabulary overlap only; the regex has not been validated against the training capture process, and it classifies anything not matching its mobile pattern as desktop (including some tablets or unusual clients). It is a separate feature from `DeviceInfo` and is not evidence that a browser user-agent, operating-system string, or form factor can substitute for a training `DeviceInfo` value.

## Compatibility decisions

| Live value or proposal | Training feature | Decision | Confidence / limitation |
| --- | --- | --- | --- |
| Browser-derived `desktop` / `mobile` | `DeviceType` | Continue current coarse input normalization only; do not treat it as `DeviceInfo`. | High confidence these labels occur in training; no validation of the browser heuristic against the dataset capture method. |
| `navigator.userAgent` string | `DeviceInfo` | No mapping. | Insufficient evidence: training collection and normalization are undocumented, and raw browser strings are not demonstrated to match fitted categories or identity semantics. |
| Browser OS/platform string (for example, `navigator.platform`) | `DeviceInfo` | No mapping. | Insufficient evidence; it is not shown to match the training source's combined/processed identity values. |
| Browser/device identifier or fabricated stable key | `DeviceInfo` | Do not substitute or create one. | Would invent an identity and edges not present in available transaction attributes. |
| Missing live value | `DeviceInfo` | Preserve `UNKNOWN`; do not create a `DeviceInfo` edge; retain the existing REVIEW safeguard and insufficient topology status. | Directly supported by current code and missing-value behavior. |

## What is needed before reconsideration

Obtain the original data-owner documentation describing how `DeviceInfo` and `DeviceType` were captured, normalized, and populated, including identity/linkage semantics and missing-value handling. Then establish a privacy-reviewed, consented live collection method and validate its outputs against that specification and the fitted training categories using real, representative observations. If no compatible live source can be justified, the model needs a separately evaluated training/serving design; do not patch the current encoder or map arbitrary browser strings into it.

Until then, keep `DeviceInfo="UNKNOWN"`, keep topology validation unvalidated when required relationships are absent, and keep the current administrator-review safeguard. Passing automated tests does not validate live GraphSAGE accuracy or topology.
