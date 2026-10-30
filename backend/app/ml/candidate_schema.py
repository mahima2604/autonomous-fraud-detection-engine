"""Schema definition, validation, and documentation for storefront candidate fraud datasets."""

from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple, Union
from pathlib import Path
import numpy as np
import pandas as pd


# Column classification
REQUIRED_IDENTIFIER_COLS = ["transaction_id", "account_id", "timestamp"]
REQUIRED_FEATURE_COLS = ["transaction_amount", "product_category"]
REQUIRED_LABEL_COL = "is_fraud"

REQUIRED_COLUMNS = REQUIRED_IDENTIFIER_COLS + REQUIRED_FEATURE_COLS + [REQUIRED_LABEL_COL]

OPTIONAL_FEATURE_DEFAULTS = {
    "item_count": 1,
    "email_domain": "UNKNOWN",
    "device_type": "UNKNOWN",
    "payment_method": "UNKNOWN",
    "billing_shipping_match": 1,
    "account_age_days": 0.0,
    "prior_tx_velocity_24h": 0,
}

# Strict feature ordering for candidate model
CANDIDATE_NUMERICAL_COLS = [
    "transaction_amount",
    "item_count",
    "account_age_days",
    "prior_tx_velocity_24h",
    "billing_shipping_match",
]

CANDIDATE_CATEGORICAL_COLS = [
    "product_category",
    "email_domain",
    "device_type",
    "payment_method",
]

CANDIDATE_FEATURE_COLS = CANDIDATE_NUMERICAL_COLS + CANDIDATE_CATEGORICAL_COLS

ALLOWED_DEVICE_TYPES: Set[str] = {"desktop", "mobile", "UNKNOWN"}
ALLOWED_PAYMENT_METHODS: Set[str] = {"CARD", "PAYPAL", "BANK_TRANSFER", "UNKNOWN"}


class DatasetValidationError(ValueError):
    """Raised when a candidate dataset fails schema, integrity, or label validation."""
    pass


def validate_candidate_dataset(
    data: Union[pd.DataFrame, str, Path],
    require_labels: bool = True,
) -> pd.DataFrame:
    """Validate that a DataFrame or CSV file conforms to the storefront candidate schema.

    Enforces:
    - Presence of all required columns.
    - No duplicate transaction_id values.
    - Parseable timestamps with strict chronological sorting.
    - Binary (0 or 1) ground-truth labels with both classes present (when require_labels=True).
    - Positive numeric transaction amounts.
    - Valid non-negative numerical ranges and normalized categoricals.

    Returns a clean, chronologically sorted DataFrame with validated feature columns.
    """
    if isinstance(data, (str, Path)):
        path = Path(data)
        if not path.exists():
            raise DatasetValidationError(f"Candidate dataset file does not exist: {path}")
        try:
            df = pd.read_csv(path)
        except Exception as error:
            raise DatasetValidationError(f"Could not parse CSV file {path}: {error}") from error
    elif isinstance(data, pd.DataFrame):
        df = data.copy()
    else:
        raise DatasetValidationError(f"Expected pandas DataFrame or path to CSV, got {type(data)}")

    if df.empty:
        raise DatasetValidationError("Candidate dataset is empty (0 rows)")

    # 1. Check required columns
    required = REQUIRED_COLUMNS if require_labels else [col for col in REQUIRED_COLUMNS if col != REQUIRED_LABEL_COL]
    missing = [col for col in required if col not in df.columns]
    if missing:
        raise DatasetValidationError(
            f"Dataset is missing required column(s): {sorted(missing)}. "
            f"Required columns: {required}"
        )

    # 2. Check for duplicate transaction identifiers
    duplicates = df[df["transaction_id"].duplicated(keep=False)]
    if not duplicates.empty:
        dup_ids = duplicates["transaction_id"].head(5).tolist()
        raise DatasetValidationError(
            f"Dataset contains duplicate transaction_id values (sample: {dup_ids}, count: {len(duplicates)})"
        )

    # 3. Check for missing values in required identifiers and features
    for col in required:
        null_count = df[col].isna().sum()
        if null_count > 0:
            raise DatasetValidationError(
                f"Required column '{col}' contains {null_count} missing/null values"
            )

    # 4. Validate and parse timestamp
    try:
        df["parsed_timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    except Exception as error:
        raise DatasetValidationError(f"Failed to parse 'timestamp' column: {error}") from error

    nat_count = df["parsed_timestamp"].isna().sum()
    if nat_count > 0:
        raise DatasetValidationError(
            f"'timestamp' column contains {nat_count} invalid or unparseable datetime strings"
        )

    # 5. Validate transaction_amount
    try:
        amounts = pd.to_numeric(df["transaction_amount"], errors="coerce")
    except Exception as error:
        raise DatasetValidationError(f"Failed to parse 'transaction_amount' as numeric: {error}") from error

    if amounts.isna().any():
        raise DatasetValidationError("'transaction_amount' contains non-numeric values")
    if (amounts <= 0).any():
        invalid_count = (amounts <= 0).sum()
        raise DatasetValidationError(f"'transaction_amount' must be positive; found {invalid_count} non-positive rows")
    df["transaction_amount"] = amounts.astype(float)

    # 6. Validate labels when required
    if require_labels:
        labels = df[REQUIRED_LABEL_COL]
        # Check integer 0 or 1
        valid_mask = labels.isin([0, 1, "0", "1", True, False])
        if not valid_mask.all():
            invalid_labels = labels[~valid_mask].head(5).tolist()
            raise DatasetValidationError(
                f"'is_fraud' must contain binary ground truth labels (0 or 1); found invalid values: {invalid_labels}"
            )
        df[REQUIRED_LABEL_COL] = labels.astype(int)
        class_counts = df[REQUIRED_LABEL_COL].value_counts().to_dict()
        if 0 not in class_counts or 1 not in class_counts:
            raise DatasetValidationError(
                f"Dataset must contain both legitimate (0) and fraud (1) samples. Found: {class_counts}"
            )

    # 7. Apply deterministic defaults for optional columns
    for col, default_val in OPTIONAL_FEATURE_DEFAULTS.items():
        if col not in df.columns:
            df[col] = default_val
        else:
            df[col] = df[col].fillna(default_val)

    # 8. Validate numerical bounds for optional columns
    for num_col, min_val in [
        ("item_count", 1),
        ("account_age_days", 0.0),
        ("prior_tx_velocity_24h", 0),
    ]:
        col_vals = pd.to_numeric(df[num_col], errors="coerce").fillna(min_val)
        if (col_vals < min_val).any():
            invalid = (col_vals < min_val).sum()
            raise DatasetValidationError(f"'{num_col}' contains {invalid} values below minimum {min_val}")
        df[num_col] = col_vals

    # Validate billing_shipping_match
    match_vals = df["billing_shipping_match"].isin([0, 1, "0", "1", True, False])
    if not match_vals.all():
        raise DatasetValidationError("'billing_shipping_match' must be binary (0 or 1)")
    df["billing_shipping_match"] = df["billing_shipping_match"].astype(int)

    # Normalize device_type
    df["device_type"] = (
        df["device_type"]
        .astype(str)
        .str.strip()
        .str.lower()
        .map(lambda d: d if d in {"desktop", "mobile"} else "UNKNOWN")
    )

    # Normalize payment_method
    df["payment_method"] = (
        df["payment_method"]
        .astype(str)
        .str.strip()
        .str.upper()
        .map(lambda p: p if p in ALLOWED_PAYMENT_METHODS else "UNKNOWN")
    )

    # Clean string categoricals
    for cat_col in ["product_category", "email_domain", "account_id"]:
        df[cat_col] = df[cat_col].astype(str).str.strip().replace("", "UNKNOWN")

    # 9. Sort chronologically by parsed_timestamp and transaction_id (stable sort)
    df = df.sort_values(["parsed_timestamp", "transaction_id"], kind="stable").reset_index(drop=True)
    return df
