"""Candidate GraphSAGE and Baseline training pipeline for storefront transactions."""

import argparse
import json
import os
import random
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.preprocessing import LabelEncoder, StandardScaler
from torch.optim import Adam
from torch_geometric.data import Data

from app.ml.candidate_model import CandidateGraphSAGE
from app.ml.candidate_schema import (
    CANDIDATE_CATEGORICAL_COLS,
    CANDIDATE_FEATURE_COLS,
    CANDIDATE_NUMERICAL_COLS,
    DatasetValidationError,
    validate_candidate_dataset,
)


SEED = 42
DEFAULT_REVIEW_THRESHOLD = 0.30
DEFAULT_BLOCK_THRESHOLD = 0.70


def set_seed(seed: int = SEED) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def chronological_split(
    df: pd.DataFrame,
    train_pct: float = 0.70,
    val_pct: float = 0.15,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Chronologically split a dataset sorted by timestamp.

    Never shuffles across time, guaranteeing that future transactions cannot
    leak into training or validation partitions.
    """
    ordered = df.sort_values(["parsed_timestamp", "transaction_id"], kind="stable").reset_index(drop=True)
    n = len(ordered)
    train_end = int(n * train_pct)
    val_end = int(n * (train_pct + val_pct))

    train = ordered.iloc[:train_end].copy().reset_index(drop=True)
    val = ordered.iloc[train_end:val_end].copy().reset_index(drop=True)
    test = ordered.iloc[val_end:].copy().reset_index(drop=True)

    if len(train) == 0 or len(val) == 0 or len(test) == 0:
        raise DatasetValidationError(
            f"Dataset too small ({n} rows) for 70/15/15 chronological partition."
        )

    for name, part in [("Train", train), ("Validation", val), ("Test", test)]:
        counts = part["is_fraud"].value_counts().to_dict()
        if 0 not in counts or 1 not in counts:
            raise DatasetValidationError(
                f"{name} partition is missing a class (counts: {counts}). "
                "Each chronological partition must contain both legitimate and fraud transactions."
            )

    return train, val, test


def sample_training_majority(
    df_train: pd.DataFrame,
    max_legit_per_fraud: int = 5,
    seed: int = SEED,
) -> pd.DataFrame:
    """Downsample majority legitimate class only on the training partition."""
    fraud = df_train[df_train["is_fraud"] == 1]
    legit = df_train[df_train["is_fraud"] == 0]
    keep = min(len(legit), len(fraud) * max_legit_per_fraud)
    sampled = pd.concat([fraud, legit.sample(n=keep, random_state=seed)])
    return sampled.sort_values(["parsed_timestamp", "transaction_id"], kind="stable").reset_index(drop=True)


def fit_preprocessing(
    df_train: pd.DataFrame,
) -> Tuple[Dict[str, StandardScaler], Dict[str, LabelEncoder]]:
    """Fit scalers on numericals and label encoders on categoricals on training data only."""
    scalers = {}
    for col in CANDIDATE_NUMERICAL_COLS:
        scaler = StandardScaler()
        scaler.fit(df_train[[col]].to_numpy(dtype=np.float32))
        scalers[col] = scaler

    encoders = {}
    for col in CANDIDATE_CATEGORICAL_COLS:
        encoder = LabelEncoder()
        classes = list(df_train[col].dropna().unique())
        if "UNKNOWN" not in classes:
            classes.append("UNKNOWN")
        encoder.fit(classes)
        encoders[col] = encoder

    return scalers, encoders


def transform_features(
    df: pd.DataFrame,
    scalers: Dict[str, StandardScaler],
    encoders: Dict[str, LabelEncoder],
) -> np.ndarray:
    """Transform features into a numeric array preserving strict feature ordering.

    Order: CANDIDATE_NUMERICAL_COLS followed by CANDIDATE_CATEGORICAL_COLS.
    """
    arrays = []
    # Scaled numericals
    for col in CANDIDATE_NUMERICAL_COLS:
        scaled = scalers[col].transform(df[[col]].to_numpy(dtype=np.float32))
        arrays.append(scaled)

    # Encoded categoricals
    for col in CANDIDATE_CATEGORICAL_COLS:
        encoder = encoders[col]
        known_classes = set(encoder.classes_)
        safe_series = df[col].apply(lambda v: v if v in known_classes else "UNKNOWN")
        encoded = encoder.transform(safe_series).reshape(-1, 1).astype(np.float32)
        arrays.append(encoded)

    return np.hstack(arrays).astype(np.float32)


def build_causal_account_graph(
    node_features: np.ndarray,
    metadata_df: pd.DataFrame,
    max_neighbors: int = 10,
) -> Data:
    """Build a strictly causal homogeneous transaction graph using account identity only.

    Rules:
    1. Nodes: Transactions in chronological order.
    2. Edges: Directed edges (t_past -> t_current).
    3. Account constraint: Source and target MUST share the exact same non-empty `account_id`.
    4. Causal constraint: `timestamp(t_past) < timestamp(t_current)`. No future connections.
    5. Isolation: No edges are formed across different accounts or based on email domain or device.
    """
    n = len(metadata_df)
    if len(node_features) != n:
        raise ValueError("Node features and metadata must have matching rows")

    timestamps = metadata_df["parsed_timestamp"].astype("int64").to_numpy()
    ordering = np.argsort(timestamps, kind="stable")
    rank = np.empty(n, dtype=np.int64)
    rank[ordering] = np.arange(n)

    sources, targets = [], []
    valid = metadata_df["account_id"].notna() & metadata_df["account_id"].ne("") & metadata_df["account_id"].ne("UNKNOWN")
    groups = metadata_df.loc[valid, ["account_id"]].assign(_node=np.flatnonzero(valid.to_numpy()))

    for _, rows in groups.groupby("account_id", sort=False):
        nodes = rows["_node"].to_numpy()
        # Sort by timestamp rank
        nodes = nodes[np.argsort(rank[nodes], kind="stable")]
        if len(nodes) < 2:
            continue
        for pos, target_node in enumerate(nodes):
            start = max(0, pos - max_neighbors)
            for src_node in nodes[start:pos]:
                # Causal direction: older node informs current/newer node
                sources.append(int(src_node))
                targets.append(int(target_node))

    if sources:
        edge_index = torch.tensor([sources, targets], dtype=torch.long)
    else:
        edge_index = torch.empty((2, 0), dtype=torch.long)

    x = torch.tensor(node_features, dtype=torch.float32)
    y = torch.tensor(metadata_df["is_fraud"].to_numpy(dtype=np.float32), dtype=torch.float32) if "is_fraud" in metadata_df else None
    return Data(x=x, edge_index=edge_index, y=y)


def evaluate_metrics(
    labels: np.ndarray,
    probabilities: np.ndarray,
    threshold: float = 0.5,
    review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
    block_threshold: float = DEFAULT_BLOCK_THRESHOLD,
) -> Dict[str, Any]:
    """Calculate evaluation metrics on held-out predictions without data leakage."""
    preds = (probabilities >= threshold).astype(int)
    cm = confusion_matrix(labels, preds, labels=[0, 1])

    # Threshold-specific policy evaluations
    def threshold_breakdown(t: float) -> Dict[str, Any]:
        p = (probabilities >= t).astype(int)
        m = confusion_matrix(labels, p, labels=[0, 1])
        return {
            "threshold": float(t),
            "precision": float(precision_score(labels, p, zero_division=0)),
            "recall": float(recall_score(labels, p, zero_division=0)),
            "f1": float(f1_score(labels, p, zero_division=0)),
            "confusion_matrix": m.tolist(),
        }

    return {
        "threshold": float(threshold),
        "precision": float(precision_score(labels, preds, zero_division=0)),
        "recall": float(recall_score(labels, preds, zero_division=0)),
        "f1": float(f1_score(labels, preds, zero_division=0)),
        "pr_auc": float(average_precision_score(labels, probabilities)),
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "confusion_matrix": cm.tolist(),
        "class_distribution": {
            "legitimate": int((labels == 0).sum()),
            "fraud": int((labels == 1).sum()),
        },
        "policy_metrics": {
            "review_threshold": review_threshold,
            "block_threshold": block_threshold,
            "at_review_cutoff": threshold_breakdown(review_threshold),
            "at_block_cutoff": threshold_breakdown(block_threshold),
        },
    }


def train_candidate_pipeline(
    data_path: Union[str, Path],
    output_dir: Optional[Union[str, Path]] = None,
    epochs: int = 30,
) -> Dict[str, Any]:
    """Validate, train, and evaluate a candidate GraphSAGE and Logistic Regression model.

    Artifacts are strictly saved under `backend/candidate_models/`. Overwriting active
    artifacts under `backend/models/` is forbidden.
    """
    set_seed()
    data_file = Path(data_path)
    if not data_file.exists():
        raise DatasetValidationError(
            f"Labelled candidate dataset not found at '{data_file}'. "
            "A valid, verified storefront CSV is required to train a candidate model."
        )

    # 1. Schema and integrity validation
    df = validate_candidate_dataset(data_file, require_labels=True)
    print(f"Validated dataset: {len(df)} rows across {df['account_id'].nunique()} accounts.")

    # 2. Chronological 70/15/15 split
    train_df, val_df, test_df = chronological_split(df)
    train_sampled = sample_training_majority(train_df)
    print(f"Chronological split - Train: {len(train_df)} (sampled: {len(train_sampled)}), Val: {len(val_df)}, Test: {len(test_df)}")

    # 3. Fit preprocessing on train only
    scalers, encoders = fit_preprocessing(train_sampled)

    x_train = transform_features(train_sampled, scalers, encoders)
    x_val = transform_features(val_df, scalers, encoders)
    x_test = transform_features(test_df, scalers, encoders)

    # 4. Train baseline Logistic Regression (on non-graph features)
    baseline = LogisticRegression(class_weight="balanced", max_iter=1000, random_state=SEED)
    baseline.fit(x_train, train_sampled["is_fraud"].to_numpy())
    baseline_val_probs = baseline.predict_proba(x_val)[:, 1]
    baseline_test_probs = baseline.predict_proba(x_test)[:, 1]

    # 5. Build causal graphs
    # Train graph
    train_graph = build_causal_account_graph(x_train, train_sampled)

    # Combined graphs for inductive validation and testing
    val_combined_df = pd.concat([train_sampled, val_df], ignore_index=True)
    val_combined_x = np.vstack([x_train, x_val])
    val_graph = build_causal_account_graph(val_combined_x, val_combined_df)

    test_combined_df = pd.concat([train_sampled, val_df, test_df], ignore_index=True)
    test_combined_x = np.vstack([x_train, x_val, x_test])
    test_graph = build_causal_account_graph(test_combined_x, test_combined_df)

    # 6. Initialize candidate GraphSAGE model
    categorical_cardinalities = [len(encoders[c].classes_) for c in CANDIDATE_CATEGORICAL_COLS]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model = CandidateGraphSAGE(
        numerical_dim=len(CANDIDATE_NUMERICAL_COLS),
        categorical_cardinalities=categorical_cardinalities,
        hidden_channels=64,
        out_channels=1,
        num_layers=2,
        dropout=0.5,
        embedding_dim=16,
    ).to(device)

    # Class-weighted loss
    pos_count = float(train_sampled["is_fraud"].sum())
    neg_count = float(len(train_sampled) - pos_count)
    pos_weight = torch.tensor([neg_count / max(1.0, pos_count)], device=device)
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=pos_weight)
    optimizer = Adam(model.parameters(), lr=0.01, weight_decay=5e-4)

    # Train model
    train_data = train_graph.to(device)
    model.train()
    for epoch in range(epochs):
        optimizer.zero_grad(set_to_none=True)
        logits = model(train_data.x, train_data.edge_index)
        loss = loss_fn(logits, train_data.y)
        loss.backward()
        optimizer.step()

    # 7. Evaluate on held-out test set
    model.eval()
    with torch.no_grad():
        test_data = test_graph.to(device)
        test_logits = model(test_data.x, test_data.edge_index)
        val_start = len(train_sampled)
        test_start = len(train_sampled) + len(val_df)
        gnn_test_probs = torch.sigmoid(test_logits[test_start:]).cpu().numpy()

    y_test = test_df["is_fraud"].to_numpy()
    gnn_metrics = evaluate_metrics(y_test, gnn_test_probs)
    baseline_metrics = evaluate_metrics(y_test, baseline_test_probs)

    # 8. Persist candidate artifacts strictly under backend/candidate_models/
    root = Path(__file__).resolve().parents[2]
    candidate_dir = Path(output_dir) if output_dir else root / "candidate_models"

    # Enforce artifact isolation: NEVER overwrite backend/models/
    active_models_dir = (root / "models").resolve()
    if candidate_dir.resolve() == active_models_dir:
        raise ValueError(
            "Candidate artifacts cannot be saved in the active models directory ('backend/models'). "
            "They must be saved in 'backend/candidate_models/'."
        )

    candidate_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "model_name": "CandidateGraphSAGE",
        "model_version": "1.0-storefront-candidate",
        "feature_schema": {
            "numerical_features": CANDIDATE_NUMERICAL_COLS,
            "categorical_features": CANDIDATE_CATEGORICAL_COLS,
            "feature_order": CANDIDATE_FEATURE_COLS,
        },
        "graph_topology": {
            "edge_type": "account_identity",
            "direction": "causal_backward",
            "max_neighbors": 10,
        },
        "training_data": str(data_file),
        "split": "chronological 70/15/15",
        "metrics": {
            "gnn": gnn_metrics,
            "baseline": baseline_metrics,
        },
        "categorical_cardinalities": categorical_cardinalities,
    }

    torch.save(model.cpu().state_dict(), candidate_dir / "candidate_graphsage.pth")
    with open(candidate_dir / "candidate_metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    joblib.dump(scalers, candidate_dir / "candidate_scalers.pkl")
    joblib.dump(encoders, candidate_dir / "candidate_encoders.pkl")
    joblib.dump(baseline, candidate_dir / "candidate_baseline.pkl")

    print(f"Candidate artifacts saved successfully in {candidate_dir}")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train candidate storefront GNN fraud model.")
    parser.add_argument("--data-file", type=Path, required=True, help="Path to validated storefront transactions CSV.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory to save candidate artifacts (defaults to backend/candidate_models).")
    parser.add_argument("--epochs", type=int, default=30)
    args = parser.parse_args()
    train_candidate_pipeline(data_path=args.data_file, output_dir=args.output_dir, epochs=args.epochs)
