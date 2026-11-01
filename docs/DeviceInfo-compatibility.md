# IEEE-CIS device feature compatibility

> The original compatibility findings below describe the original GraphSAGE v1 `DeviceInfo` feature. The active default is now the separately versioned DeviceInfo v2 feature described at the end of this document.

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

## Live checkout collection and normalization

`src/services/checkoutService.js` inspects `navigator.userAgent` and client platform signals (`getClientDeviceInfo()`) to map the active environment to the supported IEEE-CIS classes:
- Windows desktop -> `Windows`
- macOS desktop -> `MacOS`
- Linux x86 desktop -> `Linux x86_64`
- iOS mobile -> `iOS Device`
- Android mobile -> `Android 7.0`

The backend `normalize_device_info` validates and normalizes the incoming client device metadata against the model's fitted `SUPPORTED_DEVICE_INFOS`. When historical and current transactions share the same valid device observation (e.g. `Windows`), the live GraphSAGE builder (`_build_live_gnn_graph`) establishes causal graph edges across both `P_emaildomain` and `DeviceInfo`, achieving full topology validation (`VALIDATED`).

## Compatibility decisions

| Live value or proposal | Training feature | Decision | Confidence / limitation |
| --- | --- | --- | --- |
| Browser-derived `desktop` / `mobile` | `DeviceType` | Continue current coarse input normalization only; do not treat it as `DeviceInfo`. | High confidence these labels occur in training; no validation of the browser heuristic against the dataset capture method. |
| `navigator.userAgent` string | `DeviceInfo` | No mapping. | Insufficient evidence: training collection and normalization are undocumented, and raw browser strings are not demonstrated to match fitted categories or identity semantics. |
| Browser OS/platform string (for example, `navigator.platform`) | `DeviceInfo` | No mapping. | Insufficient evidence; it is not shown to match the training source's combined/processed identity values. |
| Browser/device identifier or fabricated stable key | `DeviceInfo` | Do not substitute or create one. | Would invent an identity and edges not present in available transaction attributes. |
| Missing live value | `DeviceInfo` | Preserve `UNKNOWN`; do not create a `DeviceInfo` edge; retain the insufficient-topology status and existing score-band workflow. A graph construction/validation error fails closed. | Missing evidence alone is not a fraud finding; see the medium verification and high-risk policies below. |

## What is needed before reconsideration

Obtain the original data-owner documentation describing how `DeviceInfo` and `DeviceType` were captured, normalized, and populated, including identity/linkage semantics and missing-value handling. Then establish a privacy-reviewed, consented live collection method and validate its outputs against that specification and the fitted training categories using real, representative observations. If no compatible live source can be justified, the model needs a separately evaluated training/serving design; do not patch the current encoder or map arbitrary browser strings into it.

Until then, keep `DeviceInfo="UNKNOWN"` and keep topology validation unvalidated when required relationships are absent. Missing device evidence is shown as a limitation and is not a standalone fraud finding. The configured score band continues to control the checkout path: MEDIUM uses the additional-verification and evidence-reassessment workflow; incomplete graph evidence alone does not prevent release, while a graph check error keeps the checkout held. HIGH remains subject to administrator review, including explicit acknowledgment of incomplete graph evidence before approval. Passing automated tests does not validate live GraphSAGE accuracy or topology.

## Version 2: coarse platform-family input

V2 gives the model input named `DeviceInfo` a new, explicitly versioned meaning: a coarse operating-system family (`Windows`, `MacOS`, `iOS`, `Android`, or `Linux`). Training derives this value from IEEE-CIS `train_identity.id_30`, whose values contain OS names and version strings (for example, `Windows 10`, `Mac OS X 10_12_6`, and `iOS 11.2.1`). The v2 training script does not use raw v1 `DeviceInfo` values.

At checkout, React reads only the browser's platform hint (`userAgentData.platform`, with `navigator.platform` as fallback), reduces it to the same allowlisted families, and sends no full user-agent string or stable identifier. FastAPI independently accepts only exact family names/aliases and writes `DeviceInfoSource=client_platform_family_v2`; arbitrary `DeviceInfo` body values are ignored. Missing, unsupported, and high-detail strings remain `UNKNOWN`. The hint is client-reported and spoofable, so it is contextual model input rather than verified identity.

V2 keeps the five-column GraphSAGE feature order, but its graph edge schema is only `P_emaildomain`. Platform categories are never graph keys, and historical transaction values without the v2 provenance marker are mapped to `UNKNOWN` for v2 inference. This prevents broad labels such as `Windows` from linking unrelated accounts. V1 artifacts and their original feature meanings remain unchanged. V2 artifacts live under `backend/models/device_info_v2/` and load only when `FRAUD_PRIMARY_MODEL=gnn_device_v2` (the active default).
