"""Train a versioned GraphSAGE candidate with a coarse DeviceInfo platform feature.

The v2 DeviceInfo category is derived from IEEE-CIS id_30, which contains OS
and OS-version strings. Platform families are model inputs only; graph edges
remain email-domain-only so a shared OS is never treated as a shared device.
Artifacts are written below backend/models/device_info_v2/ and do not replace v1.
"""

import argparse
import json
import random
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import torch
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.preprocessing import LabelEncoder, StandardScaler
from torch.optim import Adam

from app.graph.graph_builder import build_homogeneous_transaction_graph
from app.ml.device_info_v2 import build_training_device_platform
from app.ml.model import GraphSAGE


NUMERICAL_FEATURES = ["TransactionAmt"]
CATEGORICAL_FEATURES = ["ProductCD", "P_emaildomain", "DeviceType", "DeviceInfo"]
INPUT_FEATURES = NUMERICAL_FEATURES + CATEGORICAL_FEATURES
EDGE_FEATURES = ["P_emaildomain"]
SEED = 42


def _set_seed():
    random.seed(SEED)
    np.random.seed(SEED)
    torch.manual_seed(SEED)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(SEED)
    torch.use_deterministic_algorithms(True, warn_only=True)


def _prepare_frame(data_dir):
    transaction = pd.read_csv(
        data_dir / "train_transaction.csv",
        usecols=["TransactionID", "isFraud", "TransactionDT", "TransactionAmt", "ProductCD", "P_emaildomain"],
    )
    identity = pd.read_csv(
        data_dir / "train_identity.csv",
        usecols=["TransactionID", "DeviceType", "id_30"],
    )
    frame = transaction.merge(identity, on="TransactionID", how="left", validate="one_to_one")
    frame["DeviceInfo"] = frame["id_30"].map(build_training_device_platform)
    frame["DeviceType"] = frame["DeviceType"].fillna("UNKNOWN").astype(str)
    for column in ["ProductCD", "P_emaildomain"]:
        frame[column] = frame[column].fillna("UNKNOWN").astype(str)
    frame["TransactionAmt"] = pd.to_numeric(frame["TransactionAmt"], errors="coerce").fillna(0.0)
    return frame


def _split(frame):
    ordered = frame.sort_values(["TransactionDT", "TransactionID"], kind="stable").reset_index(drop=True)
    train_end, val_end = int(len(ordered) * 0.70), int(len(ordered) * 0.85)
    train, validation, test = ordered.iloc[:train_end].copy(), ordered.iloc[train_end:val_end].copy(), ordered.iloc[val_end:].copy()
    for name, part in (("train", train), ("validation", validation), ("test", test)):
        if part["isFraud"].nunique() != 2:
            raise ValueError(f"The chronological {name} partition must contain both classes")
    return train.reset_index(drop=True), validation.reset_index(drop=True), test.reset_index(drop=True)


def _sample_training_rows(train):
    fraud = train[train["isFraud"] == 1]
    legitimate = train[train["isFraud"] == 0]
    keep = min(len(legitimate), len(fraud) * 5)
    return pd.concat([fraud, legitimate.sample(n=keep, random_state=SEED)]).sort_values(
        ["TransactionDT", "TransactionID"], kind="stable"
    ).reset_index(drop=True)


def _fit_transformers(train):
    scalers = {"TransactionAmt": StandardScaler().fit(train[["TransactionAmt"]])}
    encoders = {}
    for column in CATEGORICAL_FEATURES:
        values = list(train[column].dropna().astype(str).unique())
        if "UNKNOWN" not in values:
            values.append("UNKNOWN")
        encoders[column] = LabelEncoder().fit(values)
    return scalers, encoders


def _transform(frame, scalers, encoders):
    result = frame[INPUT_FEATURES].copy()
    result["TransactionAmt"] = scalers["TransactionAmt"].transform(result[["TransactionAmt"]]).reshape(-1)
    for column in CATEGORICAL_FEATURES:
        encoder = encoders[column]
        known = set(encoder.classes_)
        values = result[column].fillna("UNKNOWN").astype(str).map(lambda value: value if value in known else "UNKNOWN")
        result[column] = encoder.transform(values)
    return result


def _graph_frame(frame, transformed):
    result = frame[["TransactionID", "TransactionDT", "P_emaildomain"]].reset_index(drop=True).copy()
    for column in INPUT_FEATURES:
        result[column] = transformed[column].to_numpy()
    result["isFraud"] = frame["isFraud"].to_numpy()
    return result


def _metrics(labels, probabilities):
    predicted = (probabilities >= 0.5).astype(int)
    return {
        "precision": float(precision_score(labels, predicted, zero_division=0)),
        "recall": float(recall_score(labels, predicted, zero_division=0)),
        "f1": float(f1_score(labels, predicted, zero_division=0)),
        "pr_auc": float(average_precision_score(labels, probabilities)),
        "roc_auc": float(roc_auc_score(labels, probabilities)),
        "confusion_matrix": confusion_matrix(labels, predicted, labels=[0, 1]).tolist(),
        "threshold": 0.5,
        "class_distribution": {
            "legitimate": int((labels == 0).sum()),
            "fraud": int((labels == 1).sum()),
        },
    }


def train_device_info_v2(data_dir=None, output_dir=None, epochs=30):
    _set_seed()
    project_root = Path(__file__).resolve().parents[3]
    data_dir = Path(data_dir or project_root / "data")
    output_dir = Path(output_dir or project_root / "backend" / "models" / "device_info_v2")
    frame = _prepare_frame(data_dir)
    train, validation, test = _split(frame)
    sampled_train = _sample_training_rows(train)
    scalers, encoders = _fit_transformers(sampled_train)
    x_train = _transform(sampled_train, scalers, encoders)
    x_validation = _transform(validation, scalers, encoders)
    x_test = _transform(test, scalers, encoders)

    train_graph = build_homogeneous_transaction_graph(
        _graph_frame(sampled_train, x_train), INPUT_FEATURES, EDGE_FEATURES,
        edge_frame=sampled_train[["TransactionDT", "P_emaildomain"]],
    )
    validation_all = pd.concat([sampled_train, validation], ignore_index=True)
    validation_x = pd.concat([x_train, x_validation], ignore_index=True)
    validation_graph = build_homogeneous_transaction_graph(
        _graph_frame(validation_all, validation_x), INPUT_FEATURES, EDGE_FEATURES,
        edge_frame=validation_all[["TransactionDT", "P_emaildomain"]],
    )
    test_all = pd.concat([sampled_train, validation, test], ignore_index=True)
    test_x = pd.concat([x_train, x_validation, x_test], ignore_index=True)
    test_graph = build_homogeneous_transaction_graph(
        _graph_frame(test_all, test_x), INPUT_FEATURES, EDGE_FEATURES,
        edge_frame=test_all[["TransactionDT", "P_emaildomain"]],
    )

    cardinalities = [len(encoders[column].classes_) for column in CATEGORICAL_FEATURES]
    model = GraphSAGE(
        in_channels=len(INPUT_FEATURES), hidden_channels=64, num_layers=2,
        categorical_cardinalities=cardinalities, embedding_dim=16,
    )
    positives = float(train_graph.y.sum().item())
    negatives = float(len(train_graph.y) - positives)
    loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor([negatives / positives]))
    optimizer = Adam(model.parameters(), lr=0.01, weight_decay=5e-4)
    model.train()
    for epoch in range(epochs):
        optimizer.zero_grad(set_to_none=True)
        logits = model(train_graph.x, train_graph.edge_index)
        loss = loss_fn(logits, train_graph.y)
        loss.backward()
        optimizer.step()
        if epoch == 0 or (epoch + 1) % 5 == 0:
            print(f"Epoch {epoch + 1}/{epochs} loss={loss.item():.5f}")

    model.eval()
    with torch.no_grad():
        validation_start = len(sampled_train)
        validation_probs = torch.sigmoid(model(validation_graph.x, validation_graph.edge_index)[validation_start:]).numpy()
        test_start = len(sampled_train) + len(validation)
        test_probs = torch.sigmoid(model(test_graph.x, test_graph.edge_index)[test_start:]).numpy()
    validation_metrics = _metrics(validation["isFraud"].to_numpy(), validation_probs)
    test_metrics = _metrics(test["isFraud"].to_numpy(), test_probs)

    metadata = {
        "model_name": "GraphSAGE_DevicePlatform",
        "model_version": "2.0-device-platform",
        "input_features": INPUT_FEATURES,
        "numerical_features": NUMERICAL_FEATURES,
        "categorical_features": CATEGORICAL_FEATURES,
        "edge_features": EDGE_FEATURES,
        "feature_semantics": {
            "DeviceInfo": "Coarse OS family derived from IEEE-CIS id_30 during training and browser platform hints at serving.",
            "DeviceInfo_graph_edge": "Disabled; platform families are not physical-device identifiers.",
        },
        "device_info_classes": sorted(set(encoders["DeviceInfo"].classes_) - {"UNKNOWN"}),
        "max_neighbors": 10,
        "in_channels": len(INPUT_FEATURES),
        "hidden_channels": 64,
        "num_layers": 2,
        "dropout": 0.5,
        "categorical_cardinalities": cardinalities,
        "embedding_dim": 16,
        "seed": SEED,
        "split": "chronological 70/15/15 by TransactionDT",
        "train_sampling": "all fraud plus up to five legitimate rows per fraud, random_state=42",
        "training_rows": int(len(sampled_train)),
        "validation_metrics": validation_metrics,
        "held_out_metrics": test_metrics,
        "platform_source": "train_identity.id_30; raw DeviceInfo is intentionally excluded from v2 training",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), output_dir / "graphsage_device_info_v2.pth")
    (output_dir / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    joblib.dump(scalers, output_dir / "scalers.pkl")
    joblib.dump(encoders, output_dir / "encoders.pkl")
    print("Validation metrics:", json.dumps(validation_metrics))
    print("Held-out metrics:", json.dumps(test_metrics))
    print(f"Versioned artifacts saved to {output_dir}")
    return metadata


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--epochs", type=int, default=30)
    args = parser.parse_args()
    train_device_info_v2(args.data_dir, args.output_dir, args.epochs)
