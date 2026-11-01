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
from app.ml.device_info_v2 import (
    DEVICE_INFO_V2_SOURCE,
    build_training_device_platform,
    normalize_browser_platform_hint,
)


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
def database():
    engine = create_engine("sqlite://")
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


def test_device_info_v2_uses_verified_os_training_field_and_strict_browser_allowlist():
    assert build_training_device_platform("Windows 10") == "Windows"
    assert build_training_device_platform("Mac OS X 10_13_6") == "MacOS"
    assert build_training_device_platform("iOS 11.2.1") == "iOS"
    assert build_training_device_platform("Android 7.0") == "Android"
    assert build_training_device_platform("Linux") == "Linux"
    assert build_training_device_platform(None) == "UNKNOWN"
    assert normalize_browser_platform_hint("Windows") == "Windows"
    assert normalize_browser_platform_hint("MacIntel") == "MacOS"
    assert normalize_browser_platform_hint("Mozilla/5.0 (Windows NT 10.0)") == "UNKNOWN"
    assert normalize_browser_platform_hint("random-device-id") == "UNKNOWN"


def test_device_info_v2_scoring_persists_platform_but_keeps_review_and_ignores_raw_deviceinfo(database, monkeypatch):
    user = User(name="V2 Platform Buyer", email="platform-v2@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()
    database.refresh(user)
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "gnn_device_v2")
    assert main.device_info_v2_loaded and main.device_info_v2_model is not None

    response = main.predict_fraud(
        main.TransactionInput(
            TransactionAmt=129.0,
            ProductCD="C",
            DeviceType="desktop",
            DeviceInfo="untrusted arbitrary body value",
            DevicePlatformHint="Windows",
        ),
        db=database,
        current_user=user,
    )
    saved = database.query(main.Transaction).filter(main.Transaction.id == response.transaction_id).one()
    prediction = database.query(FraudPrediction).filter(FraudPrediction.transaction_id == saved.id).one()
    assert saved.transaction_data["DeviceInfo"] == "Windows"
    assert saved.transaction_data["DeviceInfoSource"] == DEVICE_INFO_V2_SOURCE
    assert prediction.model_used == "GraphSAGE_DeviceInfo_v2"
    assert prediction.decision == "REVIEW"
    assert saved.status == "REVIEW"


def test_device_info_v2_graph_never_uses_platform_family_as_an_edge(database):
    assert main.device_info_v2_loaded
    first_user = User(name="Windows Buyer", email="buyer@first-platform.example", hashed_password="test-hash")
    second_user = User(name="Windows Buyer Two", email="buyer@second-platform.example", hashed_password="test-hash")
    database.add_all([first_user, second_user])
    database.commit()
    first = main.Transaction(
        user_id=first_user.id, amount=25, transaction_data={
            "TransactionAmt": 25, "ProductCD": "C", "P_emaildomain": "first-platform.example",
            "DeviceType": "desktop", "DeviceInfo": "Windows", "DeviceInfoSource": DEVICE_INFO_V2_SOURCE,
        }, status="REVIEW",
    )
    database.add(first)
    database.commit()
    graph, context = main._build_live_device_info_v2_graph(
        {
            "TransactionAmt": 30, "ProductCD": "C", "DeviceType": "desktop",
            "DeviceInfo": "Windows", "DeviceInfoSource": DEVICE_INFO_V2_SOURCE,
        },
        second_user,
        database,
    )
    assert graph.edge_index.numel() == 0
    assert context["training_topology"] == "P_emaildomain"
    assert "DeviceInfo" not in context["training_topology"]


def test_catalog_codes_and_checkout_features_come_from_trusted_products(database, monkeypatch):
    from app.catalog import SAMPLE_CATALOG

    expected_codes = {"W", "C", "R", "H", "S"}
    encoder_codes = set(main.gnn_encoders["ProductCD"].classes_) - {"UNKNOWN"}
    baseline_codes = set(main.baseline_product_cd_values or ())
    assert {product["ProductCD"] for product in SAMPLE_CATALOG} == expected_codes
    assert expected_codes == encoder_codes
    assert expected_codes == baseline_codes
    assert len({product["id"] for product in SAMPLE_CATALOG}) == len(SAMPLE_CATALOG)
    assert {product["name"] for product in SAMPLE_CATALOG} == {
        "Aurora Wireless Headphones",
        "Pulse Fitness Tracker",
        "Cascade Mechanical Keyboard",
        "Nimbus Backpack",
        "Halo Desk Lamp",
    }
    assert main.get_product_by_id("p2")["ProductCD"] == "C"

    user = User(name="Catalog Buyer", email="catalog@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()
    verify_test_email(database, user)
    captured = {}

    def capture_features(features, *_args):
        captured.update(features)
        return 0.1, "GraphSAGE"

    monkeypatch.setattr(main, "score_transaction", capture_features)
    address = {
        "full_name": "Catalog Buyer", "line1": "1 Example Road", "city": "Example City",
        "postal_code": "560001", "country": "India", "address_confirmed": True,
    }
    snapshot = {
        "items": [{"product_id": "p2", "quantity": 1, "price": 0.01, "ProductCD": "S"}],
        "shipping_address": address,
        "billing_address": {key: value for key, value in address.items() if key != "address_confirmed"},
    }
    response = main.predict_fraud(
        main.TransactionInput(TransactionAmt=79.5, ProductCD="S", checkout_snapshot=snapshot),
        db=database,
        current_user=user,
    )
    saved = database.query(main.Transaction).one()
    assert saved.transaction_data["ProductCD"] == "C"
    assert saved.transaction_data["TransactionAmt"] == 79.5
    assert captured["ProductCD"] == "C"
    assert captured["TransactionAmt"] == 79.5
    assert response.decision == "REVIEW"  # All transactions remain pending administrator review.
    assert response.score_based_decision == "APPROVE"  # Model score classification is preserved.
    assert saved.status == "REVIEW"

    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    monkeypatch.setattr(main, "artifacts_loaded", True)
    monkeypatch.setattr(main, "score_transaction", lambda *_args: (0.1, "LogisticRegression_Baseline"))
    mixed_snapshot = {
        "items": [{"product_id": "p1", "quantity": 1}, {"product_id": "p2", "quantity": 1}],
        "shipping_address": address,
        "billing_address": {key: value for key, value in address.items() if key != "address_confirmed"},
    }
    mixed_response = main.predict_fraud(
        main.TransactionInput(TransactionAmt=208.5, ProductCD="W", checkout_snapshot=mixed_snapshot),
        db=database,
        current_user=user,
    )
    mixed_transaction = database.query(main.Transaction).filter_by(id=mixed_response.transaction_id).one()
    assert mixed_transaction.transaction_data["ProductCD"] == "UNKNOWN"
    assert mixed_response.score_based_decision == "APPROVE"
    assert mixed_response.decision == "REVIEW"
    assert mixed_transaction.status == "REVIEW"
    assert mixed_response.review_reason and "ProductCD is unavailable" in mixed_response.review_reason


@pytest.mark.parametrize(
    ("product_id", "product_code"),
    [("p1", "W"), ("p2", "C"), ("p3", "R"), ("p4", "H"), ("p5", "S")],
)
def test_each_catalog_product_uses_a_code_supported_by_both_saved_encoders(product_id, product_code):
    _, priced_items, trusted_total = main.validate_checkout_items(
        [{"product_id": product_id, "quantity": 2, "price": -1, "ProductCD": "tampered"}]
    )

    assert priced_items[0]["product_id"] == product_id
    assert priced_items[0]["ProductCD"] == product_code
    assert trusted_total == 2 * main.get_product_by_id(product_id)["price"]
    assert main.product_cd_review_reason({"ProductCD": product_code}, "GraphSAGE") is None
    assert main.product_cd_review_reason({"ProductCD": product_code}, "LogisticRegression_Baseline") is None


def test_unsupported_productcd_holds_low_score_for_admin_review(database, monkeypatch):
    user = User(name="Unsupported Code Buyer", email="unsupported@example.test", hashed_password="test-hash")
    admin = main.Admin(email="catalog-reviewer@example.test", hashed_password="test-hash")
    database.add_all([user, admin])
    database.commit()
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    monkeypatch.setattr(main, "artifacts_loaded", True)
    monkeypatch.setattr(main, "score_transaction", lambda *_args: (0.1, "LogisticRegression_Baseline"))

    response = main.predict_fraud(
        main.TransactionInput(TransactionAmt=20.0, ProductCD="Audio"),
        db=database,
        current_user=user,
    )

    transaction = database.query(main.Transaction).one()
    assert response.score_based_decision == "APPROVE"
    assert response.decision == "REVIEW"
    assert transaction.status == "REVIEW"
    assert response.review_reason and "outside the fitted training categories" in response.review_reason
    pending = main.get_pending_reviews(db=database, current_admin=admin)
    assert len(pending) == 1
    assert pending[0]["fraud_prediction"]["operational_decision"] == "REVIEW"
    approved = main.approve_review(
        transaction.id,
        main.AdminReviewRequest(reason="Reviewed unsupported ProductCD input."),
        db=database,
        current_admin=admin,
    )
    assert approved["status"] == "REVIEW_APPROVED"
    assert approved["review_decision"] == "APPROVE"
    assert transaction.status == "REVIEW_APPROVED"


def test_graph_validation_fallback_is_held_for_admin_review(database, monkeypatch):
    user = User(name="Graph Fallback Buyer", email="fallback@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()

    def fail_graph(*_args, **_kwargs):
        raise RuntimeError("graph validation unavailable")

    class LowScorePipeline:
        named_steps = main.baseline_pipeline.named_steps

        def predict_proba(self, _frame):
            return np.array([[0.9, 0.1]])

    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "gnn")
    monkeypatch.setattr(main, "FALLBACK_FRAUD_MODEL", "logistic_regression")
    monkeypatch.setattr(main, "artifacts_loaded", True)
    monkeypatch.setattr(main, "baseline_pipeline", LowScorePipeline())
    monkeypatch.setattr(main, "_build_live_gnn_graph", fail_graph)

    response = main.predict_fraud(
        main.TransactionInput(TransactionAmt=20.0, ProductCD="W"),
        db=database,
        current_user=user,
    )

    transaction = database.query(main.Transaction).one()
    assert response.model_used == "LogisticRegression_Baseline_Fallback"
    assert response.score_based_decision == "APPROVE"
    assert response.decision == "REVIEW"
    assert transaction.status == "REVIEW"
    assert response.review_reason and "GraphSAGE inference failed" in response.review_reason


def test_graph_validation_error_without_fallback_returns_unavailable(database, monkeypatch):
    user = User(name="Graph Error Buyer", email="graph-error@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()

    def fail_prediction(*_args, **_kwargs):
        raise RuntimeError("graph validation unavailable")

    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "gnn")
    monkeypatch.setattr(main, "FALLBACK_FRAUD_MODEL", "")
    monkeypatch.setattr(main, "predict_with_gnn", fail_prediction)

    with pytest.raises(main.HTTPException) as unavailable:
        main.predict_fraud(
            main.TransactionInput(TransactionAmt=20.0, ProductCD="W"),
            db=database,
            current_user=user,
        )

    assert unavailable.value.status_code == 503
    assert database.query(main.Transaction).count() == 0
    assert database.query(FraudPrediction).count() == 0


def test_saved_graph_topology_mismatch_uses_only_explicit_fallback_and_holds_for_review(database, monkeypatch):
    user = User(name="Topology Mismatch Buyer", email="topology-mismatch@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()

    class LowScorePipeline:
        named_steps = main.baseline_pipeline.named_steps

        def predict_proba(self, _frame):
            return np.array([[0.9, 0.1]])

    monkeypatch.setattr(main, "gnn_metadata", {**main.gnn_metadata, "edge_features": ["P_emaildomain"]})
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "gnn")
    monkeypatch.setattr(main, "FALLBACK_FRAUD_MODEL", "logistic_regression")
    monkeypatch.setattr(main, "artifacts_loaded", True)
    monkeypatch.setattr(main, "baseline_pipeline", LowScorePipeline())

    response = main.predict_fraud(
        main.TransactionInput(TransactionAmt=20.0, ProductCD="W"),
        db=database,
        current_user=user,
    )

    transaction = database.query(main.Transaction).one()
    assert response.model_used == "LogisticRegression_Baseline_Fallback"
    assert response.score_based_decision == "APPROVE"
    assert response.decision == "REVIEW"
    assert transaction.status == "REVIEW"
    assert response.review_reason and "GraphSAGE inference failed" in response.review_reason


def test_missing_deviceinfo_is_unvalidated_but_keeps_existing_checkout_score_policy(database, monkeypatch):
    user = User(name="Missing DeviceInfo Buyer", email="missing-device@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()
    verify_test_email(database, user)
    address = {
        "full_name": "Missing DeviceInfo Buyer", "line1": "1 Example Road", "city": "Example City",
        "postal_code": "560001", "country": "India", "address_confirmed": True,
    }
    topology = {}

    def capture_unvalidated_graph(features, current_user, db):
        _, topology["context"] = main._build_live_gnn_graph(features, current_user, db)
        return 0.1, "GraphSAGE"

    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "gnn")
    monkeypatch.setattr(main, "score_transaction", capture_unvalidated_graph)
    snapshot = {
        "items": [{"product_id": "p1", "quantity": 1}],
        "shipping_address": address,
        "billing_address": {key: value for key, value in address.items() if key != "address_confirmed"},
    }
    response = main.predict_fraud(
        main.TransactionInput(TransactionAmt=129.0, checkout_snapshot=snapshot),
        db=database,
        current_user=user,
    )

    transaction = database.query(main.Transaction).one()
    assert transaction.transaction_data["DeviceInfo"] == "UNKNOWN"
    assert topology["context"]["topology_validation_status"] == "UNVALIDATED_INSUFFICIENT_DATA"
    assert response.decision == "REVIEW"
    assert response.score_based_decision == "APPROVE"
    assert transaction.status == "REVIEW"


def test_checkout_rejects_unknown_product_id_and_client_amount_override(database, monkeypatch):
    user = User(name="Tamper Buyer", email="tamper@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()
    verify_test_email(database, user)
    address = {
        "full_name": "Tamper Buyer", "line1": "1 Example Road", "city": "Example City",
        "postal_code": "560001", "country": "India", "address_confirmed": True,
    }
    snapshot = {
        "items": [{"product_id": "p2", "quantity": 1}],
        "shipping_address": address,
        "billing_address": {key: value for key, value in address.items() if key != "address_confirmed"},
    }
    with pytest.raises(main.HTTPException) as unknown_product:
        main.predict_fraud(
            main.TransactionInput(TransactionAmt=79.5, checkout_snapshot={**snapshot, "items": [{"product_id": "tampered", "quantity": 1}]}),
            db=database,
            current_user=user,
        )
    assert unknown_product.value.status_code == 422

    monkeypatch.setattr(main, "score_transaction", lambda *_args: (0.1, "GraphSAGE"))
    with pytest.raises(main.HTTPException) as tampered_amount:
        main.predict_fraud(
            main.TransactionInput(TransactionAmt=0.01, ProductCD="W", checkout_snapshot=snapshot),
            db=database,
            current_user=user,
        )
    assert tampered_amount.value.status_code == 409
    assert database.query(main.Transaction).count() == 0


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
def test_storefront_categories_remain_unmapped_and_topology_unvalidated(store_category):
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
    assert "backend-validated dataset code" in review_reason
    assert "topology remains unvalidated" in review_reason


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


def test_trained_artifact_loads_and_scores_live_checkout(database, monkeypatch):
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "gnn")
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
            checkout_snapshot={"items": [{"product_id": "p1", "quantity": 1}], "verified_email": user.email, "shipping_address": {"full_name": "Buyer", "line1": "1 Road", "city": "City", "postal_code": "560001", "country": "India", "address_confirmed": True}, "billing_address": {"full_name": "Buyer", "line1": "1 Road", "city": "City", "postal_code": "560001", "country": "India"}},
        ),
        db=database,
        current_user=user,
    )

    assert response.model_used == "LogisticRegression_Baseline"
    assert np.isfinite(response.fraud_probability)
    assert response.risk_level == main.classify_fraud_score(response.fraud_probability)[0]
    assert response.decision == "REVIEW"
    assert response.score_based_decision == ("BLOCK" if response.risk_level == "HIGH" else "REVIEW" if response.risk_level == "MEDIUM" else "APPROVE")
    stored = database.query(main.Transaction).one().transaction_data
    assert stored["ProductCD"] == "W"
    assert stored["DeviceInfo"] == "UNKNOWN"
    assert stored["P_emaildomain"] == "example.test"


def test_high_score_with_untrained_productcd_is_held_for_admin_review(database, monkeypatch):
    user = User(name="Review Buyer", email="review-buyer@gmail.com", hashed_password="test-hash")
    database.add(user)
    database.commit()
    verify_test_email(database, user)
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "gnn")
    monkeypatch.setattr(main, "gnn_artifacts_loaded", True)
    monkeypatch.setattr(main, "score_transaction", lambda *_args: (0.882, "GraphSAGE"))

    response = main.predict_fraud(
        main.TransactionInput(
            TransactionAmt=208.5,
            ProductCD="Audio",
            DeviceType="desktop",
            DeviceInfo="UNKNOWN",
            checkout_snapshot={
                "verified_email": user.email,
                "items": [
                    {"product_id": "p1", "quantity": 1},
                    {"product_id": "p2", "quantity": 1},
                ],
                "shipping_address": {"full_name": "Buyer", "line1": "1 Road", "city": "City", "postal_code": "560001", "country": "India", "address_confirmed": True},
                "billing_address": {"full_name": "Buyer", "line1": "1 Road", "city": "City", "postal_code": "560001", "country": "India"},
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
    assert response.review_reason and "High-risk score" in response.review_reason
    assert stored.fraud_probability == pytest.approx(0.882)
    assert stored.model_used == "GraphSAGE"
    assert stored.decision == "REVIEW"
    assert transaction.status == "REVIEW"
    assert transaction.transaction_data["ProductCD"] == "UNKNOWN"

    explanation = main.build_prediction_explanation(transaction, stored)
    assert explanation["automated_score_decision"] == "BLOCK"
    assert explanation["model_decision"] == "REVIEW"
    assert "High-risk score" in explanation["manual_review_reason"]


def test_known_training_productcd_preserves_configured_score_decision(database, monkeypatch):
    user = User(name="Known Feature Buyer", email="known@example.test", hashed_password="test-hash")
    database.add(user)
    database.commit()
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    monkeypatch.setattr(main, "artifacts_loaded", True)

    monkeypatch.setattr(main, "score_transaction", lambda *_args: (0.882, "LogisticRegression_Baseline"))
    response = main.predict_fraud(
        main.TransactionInput(TransactionAmt=157, ProductCD="C"),
        db=database,
        current_user=user,
    )

    assert response.fraud_probability == pytest.approx(0.882)
    assert response.risk_level == "HIGH"
    assert response.decision == "REVIEW"
    assert response.score_based_decision == "BLOCK"
    assert "High-risk score" in response.review_reason


def test_graphsage_high_score_is_not_downgraded_by_insufficient_live_topology_data(database, monkeypatch):
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
    assert response.score_based_decision == "BLOCK"
    assert response.model_used == "GraphSAGE"
    assert "High-risk score" in response.review_reason


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


def test_graph_explanation_distinguishes_schema_mismatch_from_missing_relationship_data(database, monkeypatch):
    user = User(name="Schema Buyer", email="schema-buyer@example.test", hashed_password="test-hash")
    database.add(user)
    database.flush()
    transaction = main.Transaction(
        user_id=user.id,
        amount=42.0,
        transaction_data={"TransactionAmt": 42.0, "ProductCD": "C", "DeviceInfo": "UNKNOWN"},
        status="REVIEW",
    )
    database.add(transaction)
    database.flush()
    prediction = FraudPrediction(
        transaction_id=transaction.id,
        fraud_probability=0.4476,
        risk_level="MEDIUM",
        decision="REVIEW",
        score_based_decision="REVIEW",
        model_used="GraphSAGE",
    )
    database.add(prediction)
    database.commit()
    monkeypatch.setattr(main, "reproduce_stored_prediction_score", lambda *_args, **_kwargs: (True, 0.4476, 2, "Reproduced"))

    def schema_error(*_args, **_kwargs):
        raise RuntimeError("Saved GraphSAGE edge schema is incompatible with checkout graph construction")

    monkeypatch.setattr(main, "_build_live_gnn_graph", schema_error)
    explanation = main.build_prediction_explanation(transaction, prediction, db=database)

    assert explanation["graph_context"]["topology_validation_status"] == "UNVALIDATED_TOPOLOGY_MISMATCH"
    assert explanation["graph_context"]["connected_neighbors"] is None
    assert explanation["graph_context"]["live_topology"] == "Unavailable"


def test_checkout_preparation_does_not_trust_deviceinfo_supplied_by_client():
    user = User(name="No Device Buyer", email="no-device@example.test", hashed_password="test-hash")
    features = main.prepare_checkout_model_features(
        {"TransactionAmt": 20.0, "DeviceType": "desktop", "DeviceInfo": "Windows"},
        user,
        {"items": [{"product_id": "p1", "quantity": 1}]},
    )
    assert features["DeviceInfo"] == "UNKNOWN"
    assert main.normalize_device_info(None, "desktop") == "UNKNOWN"


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
