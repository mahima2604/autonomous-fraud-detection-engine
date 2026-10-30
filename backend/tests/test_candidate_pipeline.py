"""Tests for storefront candidate dataset validation, causal graph construction, and artifact isolation."""

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest
import torch

from app.ml.candidate_model import CandidateGraphSAGE
from app.ml.candidate_schema import (
    CANDIDATE_CATEGORICAL_COLS,
    CANDIDATE_FEATURE_COLS,
    CANDIDATE_NUMERICAL_COLS,
    DatasetValidationError,
    validate_candidate_dataset,
)
from app.ml.candidate_train import (
    build_causal_account_graph,
    chronological_split,
    fit_preprocessing,
    train_candidate_pipeline,
    transform_features,
)


def make_valid_candidate_records(num_records=50, num_accounts=5, fraud_count=10):
    """Generate deterministic synthetic records strictly adhering to the storefront candidate schema."""
    base_time = datetime(2026, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
    categories = ["Audio", "Wearables", "Accessories", "Bags", "Home", "Footwear"]
    devices = ["desktop", "mobile", "UNKNOWN"]
    payments = ["CARD", "PAYPAL", "BANK_TRANSFER"]

    records = []
    # Ensure at least fraud_count fraud records across the timeline
    fraud_indices = set(np.linspace(2, num_records - 2, fraud_count, dtype=int))

    for i in range(num_records):
        acc_id = f"acc_{(i % num_accounts) + 1}"
        ts = base_time + timedelta(hours=i * 2)
        records.append({
            "transaction_id": f"tx_{i + 1:04d}",
            "account_id": acc_id,
            "timestamp": ts.isoformat(),
            "transaction_amount": round(50.0 + (i * 3.5) % 200, 2),
            "product_category": categories[i % len(categories)],
            "item_count": (i % 3) + 1,
            "email_domain": "gmail.com" if i % 2 == 0 else "example.org",
            "device_type": devices[i % len(devices)],
            "payment_method": payments[i % len(payments)],
            "billing_shipping_match": 1 if i % 4 != 0 else 0,
            "account_age_days": round(10.0 + i * 0.5, 1),
            "prior_tx_velocity_24h": i % 4,
            "is_fraud": 1 if i in fraud_indices else 0,
        })
    return pd.DataFrame(records)


def test_valid_candidate_dataset_passes_and_orders_chronologically():
    df = make_valid_candidate_records(30)
    # Shuffle dataframe before validation
    shuffled = df.sample(frac=1.0, random_state=123).reset_index(drop=True)
    validated = validate_candidate_dataset(shuffled, require_labels=True)

    assert len(validated) == 30
    assert list(validated.columns)[:3] == ["transaction_id", "account_id", "timestamp"]
    # Check that timestamps are strictly non-decreasing
    assert validated["parsed_timestamp"].is_monotonic_increasing


def test_schema_validator_rejects_missing_required_column():
    df = make_valid_candidate_records(20)
    # Drop account_id
    invalid = df.drop(columns=["account_id"])
    with pytest.raises(DatasetValidationError, match="missing required column.*account_id"):
        validate_candidate_dataset(invalid)


def test_schema_validator_rejects_duplicate_transaction_ids():
    df = make_valid_candidate_records(20)
    df.loc[1, "transaction_id"] = df.loc[0, "transaction_id"]
    with pytest.raises(DatasetValidationError, match="duplicate transaction_id"):
        validate_candidate_dataset(df)


def test_schema_validator_rejects_non_positive_transaction_amount():
    df = make_valid_candidate_records(20)
    df.loc[5, "transaction_amount"] = -10.0
    with pytest.raises(DatasetValidationError, match="must be positive"):
        validate_candidate_dataset(df)


def test_schema_validator_rejects_unparseable_timestamps():
    df = make_valid_candidate_records(20)
    df.loc[3, "timestamp"] = "not-a-valid-date"
    with pytest.raises(DatasetValidationError, match="invalid or unparseable datetime"):
        validate_candidate_dataset(df)


def test_schema_validator_rejects_single_class_labels():
    df = make_valid_candidate_records(20)
    df["is_fraud"] = 0
    with pytest.raises(DatasetValidationError, match="must contain both legitimate.*and fraud"):
        validate_candidate_dataset(df)


def test_schema_validator_rejects_invalid_label_values():
    df = make_valid_candidate_records(20)
    df["is_fraud"] = df["is_fraud"].astype(object)
    df.loc[2, "is_fraud"] = 0.85
    with pytest.raises(DatasetValidationError, match="binary ground truth labels"):
        validate_candidate_dataset(df)


def test_schema_validator_applies_deterministic_defaults_for_optional_columns():
    df = make_valid_candidate_records(20)
    # Drop optional columns
    minimal = df[["transaction_id", "account_id", "timestamp", "transaction_amount", "product_category", "is_fraud"]]
    validated = validate_candidate_dataset(minimal)

    assert (validated["item_count"] == 1).all()
    assert (validated["email_domain"] == "UNKNOWN").all()
    assert (validated["device_type"] == "UNKNOWN").all()
    assert (validated["payment_method"] == "UNKNOWN").all()
    assert (validated["billing_shipping_match"] == 1).all()
    assert (validated["account_age_days"] == 0.0).all()
    assert (validated["prior_tx_velocity_24h"] == 0).all()


def test_chronological_split_prevents_temporal_leakage():
    df = make_valid_candidate_records(60, num_accounts=4, fraud_count=15)
    validated = validate_candidate_dataset(df)
    train, val, test = chronological_split(validated, train_pct=0.70, val_pct=0.15)

    assert len(train) + len(val) + len(test) == 60
    # Strict temporal boundary check: max(train) <= min(val) and max(val) <= min(test)
    assert train["parsed_timestamp"].max() <= val["parsed_timestamp"].min()
    assert val["parsed_timestamp"].max() <= test["parsed_timestamp"].min()


def test_causal_graph_connects_only_same_account_in_forward_time():
    records = [
        {"transaction_id": "tx1", "account_id": "acc_1", "timestamp": "2026-01-01T10:00:00Z", "transaction_amount": 100.0, "product_category": "Audio", "is_fraud": 0},
        {"transaction_id": "tx2", "account_id": "acc_2", "timestamp": "2026-01-01T11:00:00Z", "transaction_amount": 150.0, "product_category": "Audio", "is_fraud": 0},
        {"transaction_id": "tx3", "account_id": "acc_1", "timestamp": "2026-01-01T12:00:00Z", "transaction_amount": 80.0, "product_category": "Wearables", "is_fraud": 1},
        {"transaction_id": "tx4", "account_id": "acc_1", "timestamp": "2026-01-01T13:00:00Z", "transaction_amount": 120.0, "product_category": "Home", "is_fraud": 0},
        {"transaction_id": "tx5", "account_id": "acc_3", "timestamp": "2026-01-01T14:00:00Z", "transaction_amount": 200.0, "product_category": "Footwear", "is_fraud": 1},
    ]
    df = pd.DataFrame(records)
    validated = validate_candidate_dataset(df, require_labels=True)
    scalers, encoders = fit_preprocessing(validated)
    node_features = transform_features(validated, scalers, encoders)

    graph = build_causal_account_graph(node_features, validated, max_neighbors=10)
    edge_index = graph.edge_index.numpy()

    # Nodes:
    # 0: tx1 (acc_1)
    # 1: tx2 (acc_2) - isolated
    # 2: tx3 (acc_1)
    # 3: tx4 (acc_1)
    # 4: tx5 (acc_3) - isolated

    sources = edge_index[0]
    targets = edge_index[1]

    # acc_2 (node 1) and acc_3 (node 4) must NOT have any incoming or outgoing edges
    assert 1 not in sources and 1 not in targets
    assert 4 not in sources and 4 not in targets

    # All edges must only point forward in time from older acc_1 nodes to newer acc_1 nodes
    # For acc_1: nodes are 0, 2, 3
    # Edges should be: (0 -> 2), (0 -> 3), (2 -> 3)
    edge_pairs = set(zip(sources.tolist(), targets.tolist()))
    expected_pairs = {(0, 2), (0, 3), (2, 3)}
    assert edge_pairs == expected_pairs

    # Verify no backward-in-time edges exist
    for src, dst in edge_pairs:
        assert src < dst


def test_candidate_artifact_isolation_prevents_overwriting_active_models(tmp_path):
    root = Path(__file__).resolve().parents[1]
    active_models_dir = (root / "models").resolve()

    df = make_valid_candidate_records(40, num_accounts=4, fraud_count=10)
    csv_file = tmp_path / "valid_storefront.csv"
    df.to_csv(csv_file, index=False)

    # Attempting to save candidate artifacts to active models directory must be rejected
    with pytest.raises(ValueError, match="Candidate artifacts cannot be saved in the active models directory"):
        train_candidate_pipeline(data_path=csv_file, output_dir=active_models_dir, epochs=1)


def test_candidate_training_saves_isolated_candidate_artifacts(tmp_path):
    df = make_valid_candidate_records(40, num_accounts=4, fraud_count=10)
    csv_file = tmp_path / "valid_storefront.csv"
    df.to_csv(csv_file, index=False)

    candidate_out = tmp_path / "candidate_models"
    metadata = train_candidate_pipeline(data_path=csv_file, output_dir=candidate_out, epochs=2)

    assert (candidate_out / "candidate_graphsage.pth").exists()
    assert (candidate_out / "candidate_metadata.json").exists()
    assert (candidate_out / "candidate_scalers.pkl").exists()
    assert (candidate_out / "candidate_encoders.pkl").exists()
    assert (candidate_out / "candidate_baseline.pkl").exists()

    assert metadata["model_name"] == "CandidateGraphSAGE"
    assert "gnn" in metadata["metrics"]
    assert "baseline" in metadata["metrics"]
    assert "roc_auc" in metadata["metrics"]["gnn"]


def test_preprocessing_transform_parity():
    df_train = make_valid_candidate_records(25, num_accounts=3, fraud_count=6)
    validated_train = validate_candidate_dataset(df_train)
    scalers, encoders = fit_preprocessing(validated_train)

    # Test single-row inference transformation
    single_record = {
        "transaction_id": "test_chk_01",
        "account_id": "acc_1",
        "timestamp": "2026-06-01T12:00:00Z",
        "transaction_amount": 129.0,
        "product_category": "Audio",
        "item_count": 1,
        "email_domain": "gmail.com",
        "device_type": "desktop",
        "payment_method": "CARD",
        "billing_shipping_match": 1,
        "account_age_days": 45.0,
        "prior_tx_velocity_24h": 0,
        "is_fraud": 0,
    }
    single_df = validate_candidate_dataset(pd.DataFrame([single_record]), require_labels=False)
    features = transform_features(single_df, scalers, encoders)

    expected_feature_count = len(CANDIDATE_NUMERICAL_COLS) + len(CANDIDATE_CATEGORICAL_COLS)
    assert features.shape == (1, expected_feature_count)
    # Check that scaled amount is finite
    assert np.isfinite(features[0, 0])
