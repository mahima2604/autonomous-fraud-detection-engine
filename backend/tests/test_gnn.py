import numpy as np
import pandas as pd
import pytest
import torch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main
from app.graph.graph_builder import build_homogeneous_transaction_graph
from app.ml.model import GraphSAGE
from app.models.fraud_prediction import FraudPrediction
from app.models.user import User
from app.models.email_verification import EmailVerification
from app.database.session import Base


def verify_test_email(db, user):
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    db.add(EmailVerification(
        user_id=user.id, email_address=user.email, code_hash=None, status="VERIFIED",
        created_at=now, expires_at=now + timedelta(minutes=10), resend_after=now,
        window_started_at=now, sends_in_window=1, attempts=0, verified_at=now,
    ))
    db.commit()


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'gnn.sqlite'}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_graph_edges_only_use_earlier_matching_transactions():
    nodes = pd.DataFrame({"TransactionAmt": [0.1, 0.2, 0.3]})
    edges = pd.DataFrame({
        "P_emaildomain": ["shared.example", "shared.example", "shared.example"],
        "TransactionDT": [10, 20, 30],
    })
    graph = build_homogeneous_transaction_graph(
        nodes, ["TransactionAmt"], ["P_emaildomain"], edge_frame=edges,
    )
    pairs = set(map(tuple, graph.edge_index.t().tolist()))
    assert pairs == {(0, 1), (0, 2), (1, 2)}
    assert graph.x.shape == (3, 1)


def test_graph_does_not_connect_missing_or_unknown_identity_keys():
    nodes = pd.DataFrame({"TransactionAmt": [0.1, 0.2, 0.3, 0.4, 0.5]})
    edges = pd.DataFrame({
        "P_emaildomain": ["UNKNOWN", None, "", "shared.example", "shared.example"],
        "TransactionDT": [10, 20, 30, 40, 50],
    })

    graph = build_homogeneous_transaction_graph(
        nodes, ["TransactionAmt"], ["P_emaildomain"], edge_frame=edges,
    )

    assert set(map(tuple, graph.edge_index.t().tolist())) == {(3, 4)}


def test_saved_training_and_serving_graph_schemas_match():
    from app.ml import train

    assert list(main.gnn_metadata["input_features"]) == train.FEATURE_COLS
    assert list(main.gnn_metadata["edge_features"]) == train.EDGE_COLS
    assert list(main.gnn_metadata["categorical_features"]) == train.CATEGORICAL_COLS
    assert main.gnn_metadata["in_channels"] == len(train.FEATURE_COLS)
    assert main.gnn_metadata["max_neighbors"] == 10


def test_checkout_model_features_keep_store_categories_separate_from_model_schema():
    user = User(name="Test", email="Buyer@Example.Test", hashed_password="test-hash")
    snapshot = {"items": [{"product_id": "p1", "quantity": 1}]}
    values = {
        "TransactionAmt": 129.0,
        "ProductCD": "Audio",
        "P_emaildomain": "spoofed.example",
        "DeviceType": "desktop",
        "DeviceInfo": "Win32",
    }

    model_features = main.prepare_checkout_model_features(values, user, snapshot)
    saved_snapshot = main.enrich_checkout_snapshot(snapshot)

    assert model_features["ProductCD"] == "UNKNOWN"
    assert model_features["DeviceInfo"] == "UNKNOWN"
    assert model_features["P_emaildomain"] == "example.test"
    assert saved_snapshot["items"][0]["store_category"] == "Audio"
    assert "store_category" not in model_features


@pytest.mark.parametrize(
    ("reported_device_type", "reported_device_info", "expected_device_type"),
    [
        ("desktop", "Windows", "desktop"),
        ("mobile", "iOS Device", "mobile"),
        ("UNKNOWN", "Trident/7.0", "UNKNOWN"),
    ],
)
def test_checkout_device_metadata_never_infers_training_deviceinfo(
    reported_device_type, reported_device_info, expected_device_type,
):
    user = User(name="Device Audit Buyer", email="device-audit@example.test", hashed_password="test-hash")
    features = main.prepare_checkout_model_features(
        {
            "TransactionAmt": 30.0,
            "ProductCD": "C",
            "DeviceType": reported_device_type,
            "DeviceInfo": reported_device_info,
        },
        user,
    )

    assert features["DeviceType"] == expected_device_type
    assert features["DeviceInfo"] == "UNKNOWN"
    review_reason = main.checkout_feature_review_reason(features, "GraphSAGE")
    assert "no trustworthy DeviceInfo source" in review_reason


@pytest.mark.parametrize("store_category", sorted({product["category"] for product in main.SAMPLE_CATALOG}))
def test_storefront_categories_remain_unmapped_and_reviewed(store_category):
    user = User(name="Mapping Audit Buyer", email="mapping-audit@example.test", hashed_password="test-hash")
    category = store_category
    model_features = main.prepare_checkout_model_features(
        {"TransactionAmt": 30.0, "ProductCD": category},
        user,
        {"items": [{"product_id": "catalog-item", "quantity": 1}]},
    )

    assert model_features["ProductCD"] == "UNKNOWN"
    assert category not in {str(value) for value in main.gnn_encoders["ProductCD"].classes_}
    review_reason = main.checkout_feature_review_reason(model_features, "GraphSAGE")
    assert "no verified mapping" in review_reason
    assert "review" in review_reason.lower()


def test_live_graph_uses_training_edge_schema_and_fitted_unknown_encoding(database, monkeypatch):
    from datetime import datetime, timedelta

    user = User(name="Graph Buyer", email="buyer@gmail.com", hashed_password="test-hash")
    other_user = User(name="Other Buyer", email="other@gmail.com", hashed_password="test-hash")
    database.add_all([user, other_user])
    database.flush()
    first_time = datetime(2025, 1, 1)
    database.add_all([
        main.Transaction(
            user_id=user.id,
            amount=20,
            transaction_data={
                "TransactionAmt": 20,
                "ProductCD": "Audio",
                "P_emaildomain": "example.test",
                "DeviceType": "desktop",
                "DeviceInfo": "Win32",
            },
            created_at=first_time,
        ),
        main.Transaction(
            user_id=other_user.id,
            amount=30,
            transaction_data={
                "TransactionAmt": 30,
                "ProductCD": "W",
                "P_emaildomain": "other.test",
                "DeviceType": "desktop",
                "DeviceInfo": "Win32",
            },
            created_at=first_time + timedelta(seconds=1),
        ),
    ])
    database.commit()

    captured = {}
    real_builder = main.build_homogeneous_transaction_graph

    def capture_graph(*args, **kwargs):
        graph = real_builder(*args, **kwargs)
        captured["graph"] = graph
        captured["edge_frame"] = kwargs["edge_frame"]
        return graph

    monkeypatch.setattr(main, "build_homogeneous_transaction_graph", capture_graph)
    main.predict_with_gnn({
        "TransactionAmt": 42.5,
        "ProductCD": "UNKNOWN",
        "P_emaildomain": "example.test",
        "DeviceType": "desktop",
        "DeviceInfo": "UNKNOWN",
    }, user, database)

    graph = captured["graph"]
    assert set(map(tuple, graph.edge_index.t().tolist())) == {(0, 1), (0, 2), (1, 2)}
    assert captured["edge_frame"]["P_emaildomain"].tolist() == ["gmail.com", "gmail.com", "gmail.com"]
    assert captured["edge_frame"]["DeviceInfo"].tolist() == ["UNKNOWN", "UNKNOWN", "UNKNOWN"]
    assert list(main.gnn_metadata["edge_features"]) == ["P_emaildomain", "DeviceInfo"]
    assert graph.x.shape == (3, len(main.gnn_metadata["input_features"]))
    assert graph.x[2, 0].item() == pytest.approx(
        main.gnn_scalers["TransactionAmt"].transform(pd.DataFrame({"TransactionAmt": [42.5]}))[0, 0]
    )
    assert graph.x[2, 1].item() == main.gnn_encoders["ProductCD"].transform(["UNKNOWN"])[0]
    assert graph.x[2, 4].item() == main.gnn_encoders["DeviceInfo"].transform(["UNKNOWN"])[0]
    _, context = main._build_live_gnn_graph({
        "TransactionAmt": 42.5, "ProductCD": "UNKNOWN", "DeviceType": "desktop",
    }, user, database)
    assert context["live_topology"] == "P_emaildomain"
    assert context["connected_neighbors"] == 2
    assert context["topology_validation_status"] == "UNVALIDATED_INSUFFICIENT_DATA"


def test_graphsage_returns_one_logit_per_node_including_single_node():
    model = GraphSAGE(in_channels=5, hidden_channels=8, num_layers=2)
    logits = model(torch.zeros((1, 5)), torch.empty((2, 0), dtype=torch.long))
    assert logits.shape == (1,)


def test_metrics_include_live_policy_thresholds_and_original_class_counts(monkeypatch):
    from app.ml import train
    monkeypatch.setattr(train, "REVIEW_THRESHOLD", 0.30)
    monkeypatch.setattr(train, "BLOCK_THRESHOLD", 0.70)

    result = train.metrics(np.array([0, 0, 1, 1]), np.array([0.1, 0.3, 0.7, 0.9]))

    assert result["class_distribution"] == {"legitimate": 2, "fraud": 2}
    assert result["threshold"] == 0.5
    assert result["live_policy"]["review_or_block"]["confusion_matrix"] == [[2, 0], [0, 2]]
    assert result["live_policy"]["block"]["confusion_matrix"] == [[2, 0], [1, 1]]


def test_trained_artifact_loads_and_scores_live_checkout(database):
    assert main.gnn_artifacts_loaded
    assert main.gnn_metadata["in_channels"] == 5
    assert main.gnn_model is not None
    assert main.gnn_metadata["categorical_cardinalities"] == [
        len(main.gnn_encoders[name].classes_)
        for name in main.gnn_metadata["categorical_features"]
    ]
    assert all("UNKNOWN" in main.gnn_encoders[name].classes_ for name in main.gnn_metadata["categorical_features"])
    assert list(main.baseline_pipeline.feature_names_in_) == list(main.BASELINE_FEATURES)
    product_unknown_index = list(main.gnn_encoders["ProductCD"].classes_).index("UNKNOWN")
    assert torch.count_nonzero(main.gnn_model.embeddings[0].weight[product_unknown_index]).item() == 0
    user = User(name="Test", email="gnn@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()
    response = main.predict_fraud(
        main.TransactionInput(
            TransactionAmt=42.5,
            ProductCD="UNKNOWN",
            P_emaildomain="example.test",
            DeviceType="desktop",
            DeviceInfo="test-device",
        ),
        db=database,
        current_user=user,
    )
    assert response.model_used == "GraphSAGE"
    assert np.isfinite(response.fraud_probability)
    assert 0 <= response.fraud_probability <= 1
    assert response.decision == "REVIEW"
    assert response.review_reason and "ProductCD is unavailable" in response.review_reason
    assert database.query(FraudPrediction).one().model_used == "GraphSAGE"
    stored_prediction = database.query(FraudPrediction).one()
    assert stored_prediction.fraud_probability == pytest.approx(response.fraud_probability)
    assert stored_prediction.decision == "REVIEW"


def test_logistic_regression_artifact_scores_checkout_with_unknown_store_features(database, monkeypatch):
    user = User(name="Baseline Buyer", email="baseline@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()
    verify_test_email(database, user)
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")

    response = main.predict_fraud(
        main.TransactionInput(
            TransactionAmt=129,
            ProductCD="Audio",
            DeviceType="desktop",
            DeviceInfo="Win32",
            checkout_snapshot={"items": [{"product_id": "p1", "quantity": 1}], "verified_email": user.email},
        ),
        db=database,
        current_user=user,
    )

    assert response.model_used == "LogisticRegression_Baseline"
    assert np.isfinite(response.fraud_probability)
    assert response.decision == "REVIEW"
    assert response.review_reason and "ProductCD is unavailable" in response.review_reason
    stored = database.query(main.Transaction).one().transaction_data
    assert stored["ProductCD"] == "UNKNOWN"
    assert stored["DeviceInfo"] == "UNKNOWN"
    assert stored["P_emaildomain"] == "example.test"


def test_high_score_with_untrained_productcd_is_saved_but_sent_to_manual_review(database, monkeypatch):
    user = User(name="Review Buyer", email="review-buyer@gmail.com", hashed_password="test-hash")
    database.add(user)
    database.commit()
    verify_test_email(database, user)
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "gnn")
    monkeypatch.setattr(main, "gnn_artifacts_loaded", True)
    monkeypatch.setattr(main, "score_transaction", lambda *_args: (0.882, "GraphSAGE"))

    response = main.predict_fraud(
        main.TransactionInput(
            TransactionAmt=157,
            ProductCD="Audio",
            DeviceType="desktop",
            DeviceInfo="UNKNOWN",
            checkout_snapshot={
                "verified_email": user.email,
                "items": [
                    {"product_id": "p7", "quantity": 1},
                    {"product_id": "p8", "quantity": 1},
                ],
            },
        ),
        db=database,
        current_user=user,
    )

    stored = database.query(FraudPrediction).one()
    transaction = database.query(main.Transaction).one()
    assert response.fraud_probability == pytest.approx(0.882)
    assert response.risk_level == "HIGH"
    assert response.decision == "REVIEW"
    assert response.model_used == "GraphSAGE"
    assert response.review_reason and "no verified mapping" in response.review_reason
    assert stored.fraud_probability == pytest.approx(0.882)
    assert stored.model_used == "GraphSAGE"
    assert stored.decision == "REVIEW"
    assert transaction.status == "REVIEW"
    assert transaction.transaction_data["ProductCD"] == "UNKNOWN"

    explanation = main.build_prediction_explanation(transaction, stored)
    assert explanation["automated_score_decision"] == "BLOCK"
    assert explanation["model_decision"] == "REVIEW"
    assert explanation["manual_review_reason"] == response.review_reason


def test_known_training_productcd_preserves_configured_score_decision(database, monkeypatch):
    user = User(name="Known Feature Buyer", email="known@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    monkeypatch.setattr(main, "artifacts_loaded", True)

    class FixedScore:
        def predict_proba(self, _frame):
            return np.array([[0.118, 0.882]])

    monkeypatch.setattr(main, "baseline_pipeline", FixedScore())
    response = main.predict_fraud(
        main.TransactionInput(TransactionAmt=157, ProductCD="C"),
        db=database,
        current_user=user,
    )

    assert response.fraud_probability == pytest.approx(0.882)
    assert response.decision == "BLOCK"
    assert response.review_reason is None


def test_graphsage_score_preserves_review_for_insufficient_live_topology_data(database, monkeypatch):
    user = User(name="Graph Review Buyer", email="graph-review@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "gnn")
    monkeypatch.setattr(main, "gnn_artifacts_loaded", True)
    monkeypatch.setattr(main, "score_transaction", lambda *_args: (0.882, "GraphSAGE"))

    response = main.predict_fraud(
        main.TransactionInput(TransactionAmt=157, ProductCD="C"),
        db=database,
        current_user=user,
    )

    assert response.fraud_probability == pytest.approx(0.882)
    assert response.risk_level == "HIGH"
    assert response.decision == "REVIEW"
    assert response.model_used == "GraphSAGE"
    assert response.review_reason and "no trustworthy DeviceInfo source" in response.review_reason


def test_graphsage_explanation_does_not_receive_linear_attribution_and_reports_unvalidated_topology(database, monkeypatch):
    user = User(name="Explain Buyer", email="explain-gnn@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "gnn")
    monkeypatch.setattr(main, "gnn_artifacts_loaded", True)

    response = main.predict_fraud(
        main.TransactionInput(
            TransactionAmt=88.0,
            ProductCD="UNKNOWN",
            P_emaildomain="example.test",
            DeviceType="desktop",
            DeviceInfo="UNKNOWN",
        ),
        db=database,
        current_user=user,
    )
    transaction = database.query(main.Transaction).filter(main.Transaction.id == response.transaction_id).one()
    stored_prediction = database.query(FraudPrediction).filter(FraudPrediction.transaction_id == transaction.id).one()

    explanation = main.build_prediction_explanation(transaction, stored_prediction, db=database)

    assert explanation["model_name"] == "GraphSAGE"
    assert explanation["attribution_available"] is False
    assert explanation["feature_contributions"] == []
    assert "baseline_log_odds" not in explanation
    assert "model_log_odds" not in explanation
    assert "Linear feature attribution is mathematically inapplicable to Graph Neural Networks" in explanation["attribution_note"]
    assert "graph_context" in explanation
    assert explanation["graph_context"]["training_topology"] == "P_emaildomain, DeviceInfo"
    assert explanation["graph_context"]["live_topology"] == "No connected historical edges"
    assert explanation["graph_context"]["topology_validation_status"] == "UNVALIDATED_INSUFFICIENT_DATA"
    assert "DeviceInfo" in explanation["graph_context"]["missing_edge_features"]
    assert explanation["graph_context"]["connected_neighbors"] == 0
    assert explanation["graph_context"]["feature_order"] == main.gnn_metadata["input_features"]
    assert explanation["graph_context"]["feature_dimensions"] == len(main.gnn_metadata["input_features"])
    assert explanation["score_reproduced"] is True
    assert explanation["recomputed_risk_score"] == pytest.approx(stored_prediction.fraud_probability, abs=0.0001)


def test_explanation_reports_score_reproduction_failure_when_scores_differ(database, monkeypatch):
    user = User(name="Tamper Buyer", email="tamper@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "gnn")
    monkeypatch.setattr(main, "gnn_artifacts_loaded", True)

    response = main.predict_fraud(
        main.TransactionInput(
            TransactionAmt=50.0,
            ProductCD="UNKNOWN",
            P_emaildomain="example.test",
            DeviceType="desktop",
            DeviceInfo="UNKNOWN",
        ),
        db=database,
        current_user=user,
    )
    transaction = database.query(main.Transaction).filter(main.Transaction.id == response.transaction_id).one()
    stored_prediction = database.query(FraudPrediction).filter(FraudPrediction.transaction_id == transaction.id).one()

    # Tamper with stored score to test mismatch detection
    stored_prediction.fraud_probability = 0.9999
    database.commit()

    explanation = main.build_prediction_explanation(transaction, stored_prediction, db=database)
    assert explanation["score_reproduced"] is False
    assert "does not match stored score" in explanation["reproduction_note"]
    assert explanation["graph_context"]["topology_validation_status"] == "UNVALIDATED_STORED_SCORE_MISMATCH"


def test_historical_transactions_retain_original_model_and_score_when_config_changes(database, monkeypatch):
    user = User(name="Historical Buyer", email="hist@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()

    # Step 1: Score with GraphSAGE
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "gnn")
    monkeypatch.setattr(main, "gnn_artifacts_loaded", True)
    gnn_response = main.predict_fraud(
        main.TransactionInput(
            TransactionAmt=75.0,
            ProductCD="UNKNOWN",
            P_emaildomain="example.test",
            DeviceType="desktop",
            DeviceInfo="UNKNOWN",
        ),
        db=database,
        current_user=user,
    )
    assert gnn_response.model_used == "GraphSAGE"

    # Step 2: Change serving configuration to Logistic Regression
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    monkeypatch.setattr(main, "artifacts_loaded", True)

    # Step 3: Fetch transaction and explanation - must retain GraphSAGE model identity and score
    txn = database.query(main.Transaction).filter(main.Transaction.id == gnn_response.transaction_id).one()
    pred = database.query(FraudPrediction).filter(FraudPrediction.transaction_id == txn.id).one()
    assert pred.model_used == "GraphSAGE"
    assert pred.fraud_probability == pytest.approx(gnn_response.fraud_probability)

    explanation = main.build_prediction_explanation(txn, pred, db=database)
    assert explanation["model_name"] == "GraphSAGE"
    assert explanation["attribution_available"] is False
    assert explanation["feature_contributions"] == []


def test_technical_model_failure_does_not_create_fake_approval_or_rejection(database, monkeypatch):
    user = User(name="Failing Buyer", email="fail@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "gnn")

    def failing_scorer(*_args, **_kwargs):
        raise RuntimeError("Inference engine hardware error")

    monkeypatch.setattr(main, "predict_with_gnn", failing_scorer)

    with pytest.raises(main.HTTPException) as exc_info:
        main.predict_fraud(
            main.TransactionInput(
                TransactionAmt=100.0,
                ProductCD="UNKNOWN",
                P_emaildomain="example.test",
                DeviceType="desktop",
                DeviceInfo="UNKNOWN",
            ),
            db=database,
            current_user=user,
        )

    assert exc_info.value.status_code == 503
    assert database.query(main.Transaction).count() == 0
    assert database.query(FraudPrediction).count() == 0


def test_invalid_or_non_finite_scores_raise_error_and_never_approve():
    with pytest.raises(ValueError, match="invalid probability"):
        main.classify_fraud_score(float("nan"))

    with pytest.raises(ValueError, match="invalid probability"):
        main.classify_fraud_score(float("inf"))

    with pytest.raises(ValueError, match="invalid probability"):
        main.classify_fraud_score(-0.1)

    with pytest.raises(ValueError, match="invalid probability"):
        main.classify_fraud_score(1.5)


def test_duplicate_checkout_submission_returns_persisted_transaction_idempotently(database, monkeypatch):
    user = User(name="Idempotent Buyer", email="idem@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "gnn")
    monkeypatch.setattr(main, "gnn_artifacts_loaded", True)

    attempt_id = "attempt-unique-test-12345"
    tx_input = main.TransactionInput(
        TransactionAmt=60.0,
        ProductCD="UNKNOWN",
        P_emaildomain="example.test",
        DeviceType="desktop",
        DeviceInfo="UNKNOWN",
        checkout_attempt_id=attempt_id,
    )

    first_res = main.predict_fraud(tx_input, db=database, current_user=user)
    second_res = main.predict_fraud(tx_input, db=database, current_user=user)

    assert first_res.transaction_id == second_res.transaction_id
    assert first_res.fraud_probability == second_res.fraud_probability
    assert first_res.model_used == second_res.model_used
    assert database.query(main.Transaction).filter(main.Transaction.checkout_attempt_id == attempt_id).count() == 1
    assert database.query(FraudPrediction).count() == 1
