"""Tests for Fake Store catalog integration, ProductCD mappings, and checkout safeguards."""
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database.session import Base
from app.catalog import SAMPLE_CATALOG, FAKESTORE_CATALOG, get_product
from app import main
from app.models.user import User


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


def test_fakestore_catalog_keeps_unverified_productcd_unknown():
    """Verify Fake Store store categories are not guessed into dataset codes."""
    valid_codes = {"W", "C", "R", "H", "S"}
    assert len(FAKESTORE_CATALOG) == 20
    for pid in range(1, 21):
        prod = get_product(str(pid))
        assert prod is not None
        assert prod["ProductCD"] == "UNKNOWN"

    # Only neutral sample products carry the verified fitted categories.
    assert {product["ProductCD"] for product in SAMPLE_CATALOG} == valid_codes

    # Non-existent product ID
    assert get_product("non_existent_999") is None


def test_validate_checkout_items_calculates_server_trusted_pricing():
    """Verify backend calculates trusted totals from catalogue prices and rejects uncatalogued items."""
    # Product 1 (109.95 * 2 = 219.90) and Product 2 (22.30 * 1 = 22.30) -> total = 242.20
    items = [
        {"product_id": "1", "quantity": 2},
        {"product_id": "2", "quantity": 1},
    ]
    _, priced_items, total = main.validate_checkout_items(items)
    assert total == 242.20
    assert len(priced_items) == 2
    assert priced_items[0]["ProductCD"] == "UNKNOWN"
    assert priced_items[1]["ProductCD"] == "UNKNOWN"

    # Reject uncatalogued product ID
    with pytest.raises(HTTPException) as exc_info:
        main.validate_checkout_items([{"product_id": "invalid-id-xyz", "quantity": 1}])
    assert exc_info.value.status_code == 422


def test_basket_product_cd_resolution_rules(database, monkeypatch):
    """Verify homogeneous baskets retain a code and mixed-code baskets use UNKNOWN."""
    user = User(name="Test Shopper", email="shopper@gmail.com", hashed_password="test-hash")
    database.add(user)
    database.commit()

    captured_features = {}

    def capture_eval(features, *_args, **_kwargs):
        captured_features.update(features)
        return 0.1, "GraphSAGE"

    monkeypatch.setattr(main, "score_transaction", capture_eval)
    monkeypatch.setattr(main, "require_verified_email", lambda *args, **kwargs: None)

    # Fake Store product IDs are priced by the server but do not have a verified dataset-code map.
    payload_w = main.TransactionInput(
        TransactionAmt=132.25,  # 109.95 + 22.30
        P_emaildomain="gmail.com",
        DeviceType="desktop",
        DeviceInfo="Windows",
        checkout_snapshot={
            "items": [
                {"product_id": "1", "quantity": 1},
                {"product_id": "2", "quantity": 1},
            ],
            "shipping_address": {
                "full_name": "Test User",
                "line1": "123 Market St",
                "city": "Mumbai",
                "postal_code": "400001",
                "country": "India",
                "address_confirmed": True,
            },
            "billing_address": {
                "full_name": "Test User",
                "line1": "123 Market St",
                "city": "Mumbai",
                "postal_code": "400001",
                "country": "India",
                "address_confirmed": True,
            },
        },
    )
    main.predict_fraud(payload_w, db=database, current_user=user)
    assert captured_features.get("ProductCD") == "UNKNOWN"
    assert captured_features.get("DeviceInfo") == "UNKNOWN"

    # 2. Mixed basket codes cannot be represented by one ProductCD.
    captured_features.clear()
    payload_mixed = main.TransactionInput(
        TransactionAmt=165.94,  # 109.95 + 55.99
        P_emaildomain="gmail.com",
        DeviceType="desktop",
        DeviceInfo="Windows",
        checkout_snapshot={
            "items": [
                {"product_id": "1", "quantity": 1},
                {"product_id": "3", "quantity": 1},
            ],
            "shipping_address": {
                "full_name": "Test User",
                "line1": "123 Market St",
                "city": "Mumbai",
                "postal_code": "400001",
                "country": "India",
                "address_confirmed": True,
            },
            "billing_address": {
                "full_name": "Test User",
                "line1": "123 Market St",
                "city": "Mumbai",
                "postal_code": "400001",
                "country": "India",
                "address_confirmed": True,
            },
        },
    )
    main.predict_fraud(payload_mixed, db=database, current_user=user)
    assert captured_features.get("ProductCD") == "UNKNOWN"
    assert captured_features.get("DeviceInfo") == "UNKNOWN"

    # 3. Fake Store categories remain unknown even when one line dominates by quantity.
    captured_features.clear()
    payload_c_dominant = main.TransactionInput(
        TransactionAmt=269.85,
        P_emaildomain="gmail.com",
        DeviceType="desktop",
        DeviceInfo="Windows",
        checkout_snapshot={
            "items": [
                {"product_id": "4", "quantity": 10},
                {"product_id": "1", "quantity": 1},
            ],
            "shipping_address": {
                "full_name": "Test User",
                "line1": "123 Market St",
                "city": "Mumbai",
                "postal_code": "400001",
                "country": "India",
                "address_confirmed": True,
            },
            "billing_address": {
                "full_name": "Test User",
                "line1": "123 Market St",
                "city": "Mumbai",
                "postal_code": "400001",
                "country": "India",
                "address_confirmed": True,
            },
        },
    )
    main.predict_fraud(payload_c_dominant, db=database, current_user=user)
    assert captured_features.get("ProductCD") == "UNKNOWN"


def test_client_amount_manipulation_is_rejected(database, monkeypatch):
    """Verify client-supplied amounts are checked against trusted totals."""
    user = User(name="Tamper User", email="tamper@gmail.com", hashed_password="test-hash")
    database.add(user)
    database.commit()
    monkeypatch.setattr(main, "require_verified_email", lambda *args, **kwargs: None)

    # Client tries to pay $10.00 for Product 1 (which costs $109.95) -> 409 Conflict
    tampered_amount_payload = main.TransactionInput(
        TransactionAmt=10.00,
        P_emaildomain="gmail.com",
        DeviceType="desktop",
        DeviceInfo="Windows",
        checkout_snapshot={
            "items": [{"product_id": "1", "quantity": 1}],
            "shipping_address": {
                "full_name": "Test User",
                "line1": "123 Market St",
                "city": "Mumbai",
                "postal_code": "400001",
                "country": "India",
                "address_confirmed": True,
            },
            "billing_address": {
                "full_name": "Test User",
                "line1": "123 Market St",
                "city": "Mumbai",
                "postal_code": "400001",
                "country": "India",
                "address_confirmed": True,
            },
        },
    )
    with pytest.raises(HTTPException) as exc_info:
        main.predict_fraud(tampered_amount_payload, db=database, current_user=user)
    assert exc_info.value.status_code == 409


def test_device_info_normalization():
    """Verify device observation normalization across OS platforms."""
    assert main.normalize_device_info("Windows", "desktop") == "Windows"
    assert main.normalize_device_info("Win32", "desktop") == "Windows"
    assert main.normalize_device_info("MacIntel", "desktop") == "MacOS"
    assert main.normalize_device_info("iPhone", "mobile") == "iOS Device"
    assert main.normalize_device_info("Linux aarch64", "desktop") == "Linux x86_64"
    assert main.normalize_device_info("Android 13", "mobile") == "Android 7.0"
    assert main.normalize_device_info(None, "desktop") == "UNKNOWN"
    assert main.normalize_device_info(None, "mobile") == "UNKNOWN"


def test_full_checkout_and_admin_explanation_flow_for_fakestore_products(database, monkeypatch):
    """End-to-end verification of catalog-derived ProductCD and unknown checkout DeviceInfo."""
    user = User(name="Test Buyer", email="buyer@gmail.com", hashed_password="test-hash")
    database.add(user)
    database.commit()

    monkeypatch.setattr(main, "score_transaction", lambda *args, **kwargs: (0.15, "GraphSAGE"))
    monkeypatch.setattr(main, "require_verified_email", lambda *args, **kwargs: None)
    monkeypatch.setattr(main, "reproduce_stored_prediction_score", lambda *args, **kwargs: (True, 0.15, 0, "Matched"))

    address = {
        "full_name": "Test Buyer",
        "line1": "456 Main St",
        "city": "Bengaluru",
        "postal_code": "560001",
        "country": "India",
        "address_confirmed": True,
    }

    # This mixed-code basket cannot be represented by one ProductCD; browser platform is not a device identity.
    payload = main.TransactionInput(
        TransactionAmt=165.94,
        P_emaildomain="gmail.com",
        DeviceType="desktop",
        DeviceInfo="Windows",
        checkout_attempt_id="e2e-attempt-p1-p3",
        checkout_snapshot={
            "items": [
                {"product_id": "1", "quantity": 1},
                {"product_id": "3", "quantity": 1},
            ],
            "shipping_address": address,
            "billing_address": address,
        },
    )
    res = main.predict_fraud(payload, db=database, current_user=user)
    tx = database.query(main.Transaction).filter(main.Transaction.id == res.transaction_id).first()
    pred = database.query(main.FraudPrediction).filter(main.FraudPrediction.transaction_id == res.transaction_id).first()
    exp = main.build_prediction_explanation(tx, pred, db=database)

    # Mixed ProductCD and device identity stay unavailable in live model inputs.
    assert tx.transaction_data.get("ProductCD") == "UNKNOWN"
    assert tx.transaction_data.get("DeviceInfo") == "UNKNOWN"
    product_cd_feat = next(f for f in exp["features"] if f["name"] == "ProductCD")
    assert product_cd_feat["value"] == "UNKNOWN"
    device_info_feat = next(f for f in exp["features"] if f["name"] == "DeviceInfo")
    assert device_info_feat["value"] == "UNKNOWN"
    assert "no single backend-validated ProductCD code" in exp["feature_provenance"]["ProductCD"]
    assert "no trustworthy" in exp["feature_provenance"]["DeviceInfo"]


def test_sample_product_checkout_preserves_supported_product_cd(database, monkeypatch):
    """Verify checking out with a sample product preserves its supported ProductCD through fraud prediction."""
    user = User(name="Sample Buyer", email="sample@gmail.com", hashed_password="test-hash")
    database.add(user)
    database.commit()

    captured_features = {}

    def capture_eval(features, *_args, **_kwargs):
        captured_features.update(features)
        return 0.15, "GraphSAGE"

    monkeypatch.setattr(main, "score_transaction", capture_eval)
    monkeypatch.setattr(main, "require_verified_email", lambda *args, **kwargs: None)

    address = {
        "full_name": "Sample Buyer",
        "line1": "123 Market St",
        "city": "Mumbai",
        "postal_code": "400001",
        "country": "India",
        "address_confirmed": True,
    }

    # Test each sample product (p1: W, p2: C, p3: R, p4: H, p5: S)
    for sample_id, expected_code, price in [
        ("p1", "W", 129.0),
        ("p2", "C", 79.5),
        ("p3", "R", 149.0),
        ("p4", "H", 64.0),
        ("p5", "S", 45.0),
    ]:
        captured_features.clear()
        payload = main.TransactionInput(
            TransactionAmt=price,
            P_emaildomain="gmail.com",
            DeviceType="desktop",
            DeviceInfo="UNKNOWN",
            checkout_attempt_id=f"sample-attempt-{sample_id}",
            checkout_snapshot={
                "items": [{"product_id": sample_id, "quantity": 1}],
                "shipping_address": address,
                "billing_address": address,
            },
        )
        res = main.predict_fraud(payload, db=database, current_user=user)
        tx = database.query(main.Transaction).filter(main.Transaction.id == res.transaction_id).first()
        assert tx.transaction_data.get("ProductCD") == expected_code
        assert captured_features.get("ProductCD") == expected_code

