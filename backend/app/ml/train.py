"""Train and compare the causal GraphSAGE model and Logistic Regression baseline."""

import json
import os
import random
import tempfile
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.metrics import (average_precision_score, confusion_matrix,
                             f1_score, precision_score, recall_score,
                             roc_auc_score)
from torch.optim import Adam

from app.graph.graph_builder import build_homogeneous_transaction_graph
from app.ml.baseline import train_baseline_logistic_regression
from app.ml.model import GraphSAGE
from app.ml.preprocessing import select_features_and_preprocess


NUMERICAL_COLS = ["TransactionAmt"]
CATEGORICAL_COLS = ["ProductCD", "P_emaildomain", "DeviceType", "DeviceInfo"]
FEATURE_COLS = NUMERICAL_COLS + CATEGORICAL_COLS
EDGE_COLS = ["P_emaildomain", "DeviceInfo"]
SEED = 42
THRESHOLD = 0.5


def set_seed(seed=SEED):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    torch.use_deterministic_algorithms(True, warn_only=True)


def temporal_split(frame):
    """Chronological 70/15/15 split; transactions never cross time partitions."""
    ordered = frame.sort_values(["TransactionDT", "TransactionID"], kind="stable").reset_index(drop=True)
    first = int(len(ordered) * 0.70)
    second = int(len(ordered) * 0.85)
    train, validation, test = ordered.iloc[:first].copy(), ordered.iloc[first:second].copy(), ordered.iloc[second:].copy()
    if any(part["isFraud"].nunique() != 2 for part in (train, validation, test)):
        raise ValueError("Each chronological split must contain both fraud classes")
    return train, validation, test


def sample_train(frame, max_legit_per_fraud=5):
    fraud = frame[frame.isFraud == 1]
    legit = frame[frame.isFraud == 0]
    keep = min(len(legit), len(fraud) * max_legit_per_fraud)
    sampled = pd.concat([fraud, legit.sample(n=keep, random_state=SEED)])
    return sampled.sort_values(["TransactionDT", "TransactionID"], kind="stable").reset_index(drop=True)


def _raw_features(frame):
    result = frame.copy()
    for column in CATEGORICAL_COLS:
        result[column] = result[column].fillna("UNKNOWN").astype(str)
    return result


def preprocess(frame, scalers=None, encoders=None, fit=False):
    raw = _raw_features(frame)
    processed, scalers, encoders = select_features_and_preprocess(
        raw, NUMERICAL_COLS, CATEGORICAL_COLS, is_train=fit,
        scalers=scalers, encoders=encoders,
    )
    return processed, scalers, encoders


def graph_frame(raw, processed):
    result = raw[["TransactionID", "TransactionDT"]].reset_index(drop=True).copy()
    for feature in FEATURE_COLS:
        result[feature] = processed[feature].to_numpy()
    if "isFraud" in raw:
        result["isFraud"] = raw["isFraud"].to_numpy()
    return result


def metrics(labels, probabilities):
    predictions = (probabilities >= THRESHOLD).astype(int)
    matrix = confusion_matrix(labels, predictions, labels=[0, 1])
    return {
        "precision": float(precision_score(labels, predictions, zero_division=0)),
        "recall": float(recall_score(labels, predictions, zero_division=0)),
        "f1": float(f1_score(labels, predictions, zero_division=0)),
        "pr_auc": float(average_precision_score(labels, probabilities)),
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "confusion_matrix": matrix.tolist(),
        "threshold": THRESHOLD,
    }


def _predict_graph(model, graph, target_start, target_count, device):
    graph = graph.to(device)
    model.eval()
    with torch.no_grad():
        logits = model(graph.x, graph.edge_index)
        return torch.sigmoid(logits[target_start:target_start + target_count]).cpu().numpy()


def run_training(data_dir=None, output_dir=None, epochs=30):
    set_seed()
    root = Path(__file__).resolve().parents[3]
    data_dir = Path(data_dir or root / "data")
    output_dir = Path(output_dir or root / "backend" / "models")
    tx_path, identity_path = data_dir / "train_transaction.csv", data_dir / "train_identity.csv"
    if not tx_path.exists() or not identity_path.exists():
        raise FileNotFoundError("Expected labelled train_transaction.csv and train_identity.csv under data/")

    # Read only required columns. This bounds memory use versus merging all 394+
    # source columns, while using every genuine labeled transaction for splitting.
    transaction_columns = ["TransactionID", "isFraud", "TransactionDT", *NUMERICAL_COLS,
                           "ProductCD", "P_emaildomain"]
    identity_columns = ["TransactionID", "DeviceType", "DeviceInfo"]
    transactions = pd.read_csv(tx_path, usecols=transaction_columns)
    identities = pd.read_csv(identity_path, usecols=identity_columns)
    data = transactions.merge(identities, on="TransactionID", how="left", validate="one_to_one")
    del transactions, identities
    train_all, validation, test = temporal_split(data)
    train = sample_train(train_all)
    print(f"Chronological rows train/validation/test: {len(train_all)}/{len(validation)}/{len(test)}")
    print(f"Training rows after deterministic 1:{5} majority sampling: {len(train)}")

    baseline = train_baseline_logistic_regression(
        _raw_features(train), train.isFraud.to_numpy(), NUMERICAL_COLS, CATEGORICAL_COLS
    )
    # Baseline and GNN use the identical held-out transactions and threshold.
    x_test_baseline = _raw_features(test)[FEATURE_COLS]
    baseline_probabilities = baseline.predict_proba(x_test_baseline)[:, list(baseline.classes_).index(1)]

    train_processed, scalers, encoders = preprocess(train, fit=True)
    val_processed, _, _ = preprocess(validation, scalers, encoders)
    test_processed, _, _ = preprocess(test, scalers, encoders)
    train_graph_frame = graph_frame(train, train_processed)
    train_graph = build_homogeneous_transaction_graph(
        train_graph_frame, FEATURE_COLS, EDGE_COLS, edge_frame=train[["TransactionDT", *EDGE_COLS]]
    )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    categorical_cardinalities = [len(encoders[column].classes_) for column in CATEGORICAL_COLS]
    model = GraphSAGE(
        in_channels=len(FEATURE_COLS), hidden_channels=64, num_layers=2,
        categorical_cardinalities=categorical_cardinalities, embedding_dim=16,
    ).to(device)
    training_data = train_graph.to(device)
    positive = training_data.y.sum().item()
    negative = len(training_data.y) - positive
    if positive == 0 or negative == 0:
        raise ValueError("Training partition must contain both classes")
    loss_function = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor([negative / positive], device=device))
    optimizer = Adam(model.parameters(), lr=0.01, weight_decay=5e-4)
    model.train()
    for epoch in range(epochs):
        optimizer.zero_grad(set_to_none=True)
        logits = model(training_data.x, training_data.edge_index)
        loss = loss_function(logits, training_data.y)
        loss.backward()
        optimizer.step()
        if epoch == 0 or (epoch + 1) % 5 == 0:
            print(f"Epoch {epoch + 1}/{epochs} loss={loss.item():.5f}")

    # Append validation/test nodes after training nodes. Causal edges only point
    # backward in time, so later labels/features cannot affect earlier outputs.
    validation_raw = pd.concat([train, validation], ignore_index=True)
    validation_processed = pd.concat([train_processed, val_processed], ignore_index=True)
    validation_graph = build_homogeneous_transaction_graph(
        graph_frame(validation_raw, validation_processed), FEATURE_COLS, EDGE_COLS,
        edge_frame=validation_raw[["TransactionDT", *EDGE_COLS]],
    )
    val_start = len(train)
    val_probabilities = _predict_graph(model, validation_graph, val_start, len(validation), device)
    print("Validation (for promotion check):", json.dumps(metrics(validation.isFraud.to_numpy(), val_probabilities)))

    test_raw = pd.concat([train, validation, test], ignore_index=True)
    test_processed = pd.concat([train_processed, val_processed, test_processed], ignore_index=True)
    test_graph = build_homogeneous_transaction_graph(
        graph_frame(test_raw, test_processed), FEATURE_COLS, EDGE_COLS,
        edge_frame=test_raw[["TransactionDT", *EDGE_COLS]],
    )
    test_start = len(train) + len(validation)
    gnn_probabilities = _predict_graph(model, test_graph, test_start, len(test), device)
    gnn_metrics = metrics(test.isFraud.to_numpy(), gnn_probabilities)
    baseline_metrics = metrics(test.isFraud.to_numpy(), baseline_probabilities)
    print("Held-out GraphSAGE metrics:", json.dumps(gnn_metrics))
    print("Held-out Logistic Regression metrics:", json.dumps(baseline_metrics))

    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = {
        "model_name": "GraphSAGE",
        "model_version": "1",
        "input_features": FEATURE_COLS,
        "numerical_features": NUMERICAL_COLS,
        "categorical_features": CATEGORICAL_COLS,
        "edge_features": EDGE_COLS,
        "max_neighbors": 10,
        "in_channels": len(FEATURE_COLS),
        "hidden_channels": 64,
        "num_layers": 2,
        "dropout": 0.5,
        "categorical_cardinalities": categorical_cardinalities,
        "embedding_dim": 16,
        "seed": SEED,
        "threshold": THRESHOLD,
        "split": "chronological 70/15/15 by TransactionDT",
        "train_sampling": "all fraud plus up to five legitimate rows per fraud, random_state=42",
        "held_out_metrics": gnn_metrics,
        "baseline_held_out_metrics": baseline_metrics,
        "training_device": str(device),
    }
    state_path = output_dir / "graphsage.pth"
    metadata_path = output_dir / "graphsage_metadata.json"
    # Atomically replace only after training and held-out evaluation complete.
    with tempfile.NamedTemporaryFile(dir=output_dir, suffix=".pth", delete=False) as temporary:
        temp_state = Path(temporary.name)
    try:
        torch.save(model.cpu().state_dict(), temp_state)
        os.replace(temp_state, state_path)
        temp_metadata = metadata_path.with_suffix(".json.tmp")
        temp_metadata.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        os.replace(temp_metadata, metadata_path)
    finally:
        if temp_state.exists():
            temp_state.unlink()

    # Persist the matching GNN preprocessing separately from existing baseline.
    joblib.dump(scalers, output_dir / "gnn_scalers.pkl")
    joblib.dump(encoders, output_dir / "gnn_encoders.pkl")
    joblib.dump(baseline, output_dir / "baseline_pipeline.pkl")
    return gnn_metrics, baseline_metrics


if __name__ == "__main__":
    run_training(epochs=int(os.getenv("GNN_EPOCHS", "30")))
