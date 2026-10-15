import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("AUTH_TOKEN_SECRET", "test-only-signing-key-for-checkout-tests")
os.environ.setdefault("ENABLE_DEMO_ADMIN", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app import main
from app.database.session import Base
from app.models.admin import Admin
from app.models.fraud_prediction import FraudPrediction
from app.models.order import Order
from app.models.transaction import Transaction
from app.models.user import User
from app.services.auth import create_access_token, create_admin_access_token, hash_password
from app.ml.baseline import train_baseline_logistic_regression


class FixedProbabilityPipeline:
    def __init__(self, score):
        self.score = score

    def predict_proba(self, _frame):
        return np.array([[1 - self.score, self.score]])


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'checkout.sqlite'}")
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture
def database_with_legacy_orders(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-orders.sqlite'}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE orders")
        connection.exec_driver_sql("""
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                transaction_id INTEGER NOT NULL,
                items JSON NOT NULL,
                amount FLOAT NOT NULL,
                currency VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                payment_status VARCHAR NOT NULL,
                payment_method VARCHAR NOT NULL,
                created_at DATETIME NOT NULL
            )
        """)
    main.initialize_database(database_engine=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def make_user(db, email):
    user = User(name="Test Customer", email=email, hashed_password=hash_password("test-only-password"))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def run_prediction(db, user, monkeypatch, score, attempt_id=None, checkout_snapshot=None):
    monkeypatch.setattr(main, "baseline_pipeline", FixedProbabilityPipeline(score))
    monkeypatch.setattr(main, "artifacts_loaded", True)
    request = main.TransactionInput(TransactionAmt=129.0, ProductCD=None, checkout_attempt_id=attempt_id, checkout_snapshot=checkout_snapshot)
    return main.predict_fraud(request, db=db, current_user=user)


def order_request(transaction_id, product_id="p1", quantity=1):
    return main.CreateOrderRequest(
        transaction_id=transaction_id,
        items=[main.OrderItemRequest(product_id=product_id, quantity=quantity)],
        payment_method="CARD",
        shipping_address={"full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City", "postal_code": "00000", "country": "Exampleland"},
        billing_address={"full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City", "postal_code": "00000", "country": "Exampleland"},
    )


def test_configured_fraud_decision_thresholds():
    assert main.classify_fraud_score(main.FRAUD_REVIEW_THRESHOLD) == ("LOW", "APPROVE")
    assert main.classify_fraud_score(0.5) == ("MEDIUM", "REVIEW")
    assert main.classify_fraud_score(main.FRAUD_BLOCK_THRESHOLD) == ("MEDIUM", "REVIEW")
    assert main.classify_fraud_score(0.9) == ("HIGH", "BLOCK")
    with pytest.raises(ValueError):
        main.classify_fraud_score(float("nan"))


def test_prediction_persists_transaction_and_baseline_decision(database, monkeypatch):
    user = make_user(database, "buyer-one@example.test")
    result = run_prediction(database, user, monkeypatch, 0.2)
    transaction = database.query(Transaction).one()
    prediction = database.query(FraudPrediction).one()
    assert result.transaction_id == transaction.id
    assert prediction.decision == "APPROVE"
    assert transaction.status == "APPROVED"
    assert prediction.model_used == "LogisticRegression_Baseline"



def test_prediction_retries_reuse_the_same_transaction(database, monkeypatch):
    user = make_user(database, "retry@example.test")
    first = run_prediction(database, user, monkeypatch, 0.2, attempt_id="checkout-attempt-test")
    second = run_prediction(database, user, monkeypatch, 0.9, attempt_id="checkout-attempt-test")
    assert first.transaction_id == second.transaction_id
    assert second.decision == "APPROVE"
    assert database.query(Transaction).count() == 1
    assert database.query(FraudPrediction).count() == 1


def test_prediction_attempt_id_cannot_be_reused_for_changed_payload(database, monkeypatch):
    user = make_user(database, "changed-retry@example.test")
    run_prediction(database, user, monkeypatch, 0.2, attempt_id="stable-attempt-test")
    changed = main.TransactionInput(TransactionAmt=130.0, checkout_attempt_id="stable-attempt-test")
    with pytest.raises(HTTPException) as error:
        main.predict_fraud(changed, db=database, current_user=user)
    assert error.value.status_code == 409
    assert database.query(Transaction).count() == 1

def test_failed_prediction_does_not_create_transaction(database, monkeypatch):
    user = make_user(database, "buyer-two@example.test")

    class BrokenPipeline:
        def predict_proba(self, _frame):
            raise RuntimeError("internal model error")

    monkeypatch.setattr(main, "baseline_pipeline", BrokenPipeline())
    monkeypatch.setattr(main, "artifacts_loaded", True)
    with pytest.raises(HTTPException) as error:
        main.predict_fraud(main.TransactionInput(TransactionAmt=129), db=database, current_user=user)
    assert error.value.status_code == 503
    assert "internal model error" not in error.value.detail
    assert database.query(Transaction).count() == 0
    assert database.query(FraudPrediction).count() == 0


def test_transaction_amount_must_be_positive_and_finite():
    with pytest.raises(ValidationError):
        main.TransactionInput(TransactionAmt=0)
    with pytest.raises(ValidationError):
        main.TransactionInput(TransactionAmt=float("inf"))


def test_approved_owned_transaction_creates_idempotent_order(database, monkeypatch):
    user = make_user(database, "buyer-three@example.test")
    prediction = run_prediction(database, user, monkeypatch, 0.2)
    request = order_request(prediction.transaction_id)
    first = main.create_order(request, db=database, current_user=user)
    second = main.create_order(request, db=database, current_user=user)
    assert first["id"] == second["id"]
    assert first["amount"] == 129.0
    assert first["paymentStatus"] == "SIMULATED"
    assert first["items"][0]["name"] == "Aurora Wireless Headphones"
    assert database.query(Order).count() == 1
    assert main.get_orders(db=database, current_user=user)[0]["id"] == first["id"]
    assert database.query(Transaction).one().status == "ORDERED"


def test_backend_checkout_snapshot_survives_review_and_controls_resumed_order(database, monkeypatch):
    user = make_user(database, "snapshot-review@example.test")
    admin = Admin(email="snapshot-review-admin@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    snapshot_address = {"full_name": "Saved Buyer", "line1": "9 Saved Road", "city": "Saved City", "postal_code": "99999", "country": "Savedland"}
    snapshot = {
        "items": [{"product_id": "p1", "quantity": 1}],
        "payment_method": "PAYPAL",
        "shipping_address": snapshot_address,
        "billing_address": snapshot_address,
    }
    prediction = run_prediction(database, user, monkeypatch, 0.5, "snapshot-review-attempt", snapshot)
    transaction = database.query(Transaction).one()
    assert transaction.checkout_snapshot == snapshot
    assert transaction.transaction_data["ProductCD"] == "Audio"

    main.approve_review(prediction.transaction_id, main.AdminReviewRequest(), db=database, current_admin=admin)
    status = main.get_transaction_status(prediction.transaction_id, db=database, current_user=user)
    assert status["transaction_id"] == prediction.transaction_id
    assert status["checkout_snapshot"] == snapshot

    # The client retry may have stale details; persisted checkout data is authoritative.
    stale_request = order_request(prediction.transaction_id)
    order = main.create_order(stale_request, db=database, current_user=user)
    retry = main.create_order(stale_request, db=database, current_user=user)
    assert order["transaction_id"] == prediction.transaction_id
    assert order["paymentMethod"] == "PAYPAL"
    assert order["shipping_address"] == snapshot_address
    assert retry["id"] == order["id"]
    assert database.query(Order).count() == 1


def test_review_and_block_decisions_cannot_create_orders(database, monkeypatch):
    for email, score in (("review@example.test", 0.5), ("blocked@example.test", 0.9)):
        user = make_user(database, email)
        prediction = run_prediction(database, user, monkeypatch, score)
        with pytest.raises(HTTPException) as error:
            main.create_order(order_request(prediction.transaction_id), db=database, current_user=user)
        assert error.value.status_code == 409
    assert database.query(Order).count() == 0


def test_admin_review_endpoints_list_and_preserve_prediction(database, monkeypatch):
    user = make_user(database, "review-list@example.test")
    admin = Admin(email="review-admin@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    database.refresh(admin)
    prediction = run_prediction(database, user, monkeypatch, 0.5, "review-list-attempt")
    original_prediction = database.query(FraudPrediction).one()
    original_score = original_prediction.fraud_probability
    original_transaction_id = database.query(Transaction).one().id

    pending = main.get_pending_reviews(db=database, current_admin=admin)
    assert [row["transaction_id"] for row in pending] == [prediction.transaction_id]
    assert pending[0]["fraud_prediction"]["decision"] == "REVIEW"

    response = main.approve_review(
        prediction.transaction_id,
        main.AdminReviewRequest(reason="Verified with customer"),
        db=database,
        current_admin=admin,
    )
    assert response["status"] == "REVIEW_APPROVED"
    assert response["review_decision"] == "APPROVE"
    assert response["reviewed_by_admin_id"] == admin.id
    assert response["reviewed_at"]
    assert response["review_reason"] == "Verified with customer"
    assert database.query(Transaction).one().id == original_transaction_id
    assert database.query(Transaction).one().checkout_attempt_id == "review-list-attempt"
    assert database.query(FraudPrediction).one().decision == "REVIEW"
    assert database.query(FraudPrediction).one().fraud_probability == original_score


@pytest.mark.parametrize(("path_action", "expected_status", "expected_decision"), [
    ("approve", "REVIEW_APPROVED", "APPROVE"),
    ("reject", "REJECTED", "REJECT"),
])
def test_admin_can_decide_review_transaction(database, monkeypatch, path_action, expected_status, expected_decision):
    user = make_user(database, f"review-{path_action}@example.test")
    admin = Admin(email=f"admin-{path_action}@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    database.refresh(admin)
    prediction = run_prediction(database, user, monkeypatch, 0.5)
    handler = main.approve_review if path_action == "approve" else main.reject_review
    response = handler(prediction.transaction_id, main.AdminReviewRequest(), db=database, current_admin=admin)

    assert response["status"] == expected_status
    assert response["review_decision"] == expected_decision
    assert database.query(FraudPrediction).one().decision == "REVIEW"


def test_review_actions_require_admin_authentication(database, monkeypatch):
    customer = make_user(database, "review-customer@example.test")
    prediction = run_prediction(database, customer, monkeypatch, 0.5)
    with pytest.raises(HTTPException) as unauthenticated:
        main.get_current_admin(credentials=None, db=database)
    customer_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=create_access_token(customer.id))
    with pytest.raises(HTTPException) as customer_action:
        main.get_current_admin(credentials=customer_credentials, db=database)

    assert unauthenticated.value.status_code == 401
    assert customer_action.value.status_code == 401
    assert database.query(Transaction).one().status == "REVIEW"
    review_routes = [route for route in main.app.routes if route.path.startswith("/api/admin/reviews/")]
    assert len(review_routes) == 3
    assert all(any(dependency.call == main.get_current_admin for dependency in route.dependant.dependencies) for route in review_routes)


def test_customer_status_is_owner_scoped_and_reflects_admin_decision(database, monkeypatch):
    owner = make_user(database, "status-owner@example.test")
    another_customer = make_user(database, "status-other@example.test")
    admin = Admin(email="status-admin@example.test", hashed_password=hash_password("status-admin-password"))
    database.add(admin)
    database.commit()
    database.refresh(admin)
    prediction = run_prediction(database, owner, monkeypatch, 0.5, "status-owner-attempt")

    own_status = main.get_transaction_status(prediction.transaction_id, db=database, current_user=owner)
    assert own_status["transaction_id"] == prediction.transaction_id
    assert own_status["status"] == "REVIEW"
    assert own_status["fraud_prediction"]["decision"] == "REVIEW"
    with pytest.raises(HTTPException) as hidden_from_other_user:
        main.get_transaction_status(prediction.transaction_id, db=database, current_user=another_customer)
    assert hidden_from_other_user.value.status_code == 404

    main.approve_review(prediction.transaction_id, main.AdminReviewRequest(), db=database, current_admin=admin)
    approved_status = main.get_transaction_status(prediction.transaction_id, db=database, current_user=owner)
    assert approved_status["status"] == "REVIEW_APPROVED"
    assert approved_status["review_decision"] == "APPROVE"
    assert approved_status["fraud_prediction"]["decision"] == "REVIEW"
    assert approved_status["fraud_prediction"]["fraud_probability"] == 0.5

    status_route = next(route for route in main.app.routes if route.path == "/api/transactions/{transaction_id}/status")
    assert any(dependency.call == main.get_current_user for dependency in status_route.dependant.dependencies)


def test_review_actions_reject_repeated_or_conflicting_decisions(database, monkeypatch):
    customer = make_user(database, "review-conflict@example.test")
    admin = Admin(email="review-conflict-admin@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    database.refresh(admin)
    prediction = run_prediction(database, customer, monkeypatch, 0.5)
    first = main.reject_review(prediction.transaction_id, main.AdminReviewRequest(), db=database, current_admin=admin)
    with pytest.raises(HTTPException) as repeated:
        main.reject_review(prediction.transaction_id, main.AdminReviewRequest(), db=database, current_admin=admin)
    with pytest.raises(HTTPException) as conflicting:
        main.approve_review(prediction.transaction_id, main.AdminReviewRequest(), db=database, current_admin=admin)

    assert first["status"] == "REJECTED"
    assert repeated.value.status_code == 409
    assert conflicting.value.status_code == 409
    assert database.query(Transaction).one().status == "REJECTED"
    assert database.query(Transaction).one().review_decision == "REJECT"


def test_admin_approved_review_can_order_but_blocked_and_rejected_cannot(database, monkeypatch):
    admin = Admin(email="payment-review-admin@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    database.refresh(admin)
    headers = {"Authorization": f"Bearer {create_admin_access_token(admin.id)}"}

    approved_user = make_user(database, "admin-approved@example.test")
    review = run_prediction(database, approved_user, monkeypatch, 0.5)
    response = main.approve_review(review.transaction_id, main.AdminReviewRequest(), db=database, current_admin=admin)
    assert response["status"] == "REVIEW_APPROVED"
    order = main.create_order(order_request(review.transaction_id), db=database, current_user=approved_user)
    assert order["transaction_id"] == review.transaction_id
    assert database.query(Transaction).filter(Transaction.id == review.transaction_id).one().status == "ORDERED"

    rejected_user = make_user(database, "admin-rejected@example.test")
    rejected = run_prediction(database, rejected_user, monkeypatch, 0.5)
    main.reject_review(rejected.transaction_id, main.AdminReviewRequest(), db=database, current_admin=admin)
    with pytest.raises(HTTPException) as rejected_error:
        main.create_order(order_request(rejected.transaction_id), db=database, current_user=rejected_user)
    assert rejected_error.value.status_code == 409

    blocked_user = make_user(database, "admin-blocked@example.test")
    blocked = run_prediction(database, blocked_user, monkeypatch, 0.9)
    with pytest.raises(HTTPException) as blocked_error:
        main.create_order(order_request(blocked.transaction_id), db=database, current_user=blocked_user)
    assert blocked_error.value.status_code == 409


def test_admin_approved_review_creates_idempotent_357_50_order(database_with_legacy_orders, monkeypatch):
    database = database_with_legacy_orders
    admin = Admin(email="three-item-review-admin@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    database.refresh(admin)
    user = make_user(database, "three-item-review@example.test")
    monkeypatch.setattr(main, "baseline_pipeline", FixedProbabilityPipeline(0.5))
    monkeypatch.setattr(main, "artifacts_loaded", True)
    prediction = main.predict_fraud(
        main.TransactionInput(TransactionAmt=357.5, checkout_attempt_id="three-item-review-attempt"),
        db=database,
        current_user=user,
    )
    main.approve_review(prediction.transaction_id, main.AdminReviewRequest(), db=database, current_admin=admin)
    request = main.CreateOrderRequest(
        transaction_id=prediction.transaction_id,
        items=[
            main.OrderItemRequest(product_id="p1", quantity=1),
            main.OrderItemRequest(product_id="p2", quantity=1),
            main.OrderItemRequest(product_id="p3", quantity=1),
        ],
        payment_method="CARD",
        shipping_address={"full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City", "postal_code": "00000", "country": "Exampleland"},
        billing_address={"full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City", "postal_code": "00000", "country": "Exampleland"},
    )

    first = main.create_order(request, db=database, current_user=user)
    retry = main.create_order(request, db=database, current_user=user)

    assert first["amount"] == 357.5
    assert first["transaction_id"] == prediction.transaction_id
    assert first["paymentStatus"] == "SIMULATED"
    assert retry["id"] == first["id"]
    assert database.query(Order).count() == 1


def test_user_cannot_order_another_users_transaction(database, monkeypatch):
    owner = make_user(database, "owner@example.test")
    other_user = make_user(database, "other@example.test")
    prediction = run_prediction(database, owner, monkeypatch, 0.2)
    with pytest.raises(HTTPException) as error:
        main.create_order(order_request(prediction.transaction_id), db=database, current_user=other_user)
    assert error.value.status_code == 404
    assert database.query(Order).count() == 0


def test_order_rejects_client_price_mismatch_and_unknown_products(database, monkeypatch):
    user = make_user(database, "buyer-four@example.test")
    prediction = run_prediction(database, user, monkeypatch, 0.2)
    with pytest.raises(HTTPException) as mismatch:
        main.create_order(order_request(prediction.transaction_id, quantity=2), db=database, current_user=user)
    with pytest.raises(HTTPException) as unavailable:
        main.create_order(order_request(prediction.transaction_id, product_id="not-a-product"), db=database, current_user=user)
    assert mismatch.value.status_code == 409
    assert unavailable.value.status_code == 422
    assert database.query(Order).count() == 0


def test_authentication_tokens_are_role_separated(database):
    user = make_user(database, "token-user@example.test")
    admin = Admin(email="admin@example.test", hashed_password=hash_password("test-admin-password"))
    database.add(admin)
    database.commit()
    database.refresh(admin)
    user_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=create_access_token(user.id))
    admin_credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials=create_admin_access_token(admin.id))
    assert main.get_current_user(credentials=user_credentials, db=database).id == user.id
    assert main.get_current_admin(credentials=admin_credentials, db=database).id == admin.id
    with pytest.raises(HTTPException):
        main.get_current_admin(credentials=user_credentials, db=database)
    with pytest.raises(HTTPException):
        main.get_current_user(credentials=admin_credentials, db=database)



def test_additive_startup_migration_preserves_legacy_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR, hashed_password VARCHAR, is_active BOOLEAN, created_at DATETIME)")
        connection.exec_driver_sql("CREATE TABLE transactions (id INTEGER PRIMARY KEY, user_id INTEGER, transaction_data JSON, amount FLOAT, currency VARCHAR, status VARCHAR, created_at DATETIME)")
        connection.exec_driver_sql("INSERT INTO users (id, email, hashed_password, is_active) VALUES (1, 'legacy@example.test', 'test-hash', 1)")
        connection.exec_driver_sql("INSERT INTO transactions (id, user_id, transaction_data, amount, currency, status) VALUES (1, 1, '{}', 129.0, 'USD', 'PENDING')")
    main.initialize_database(database_engine=engine)

    inspector = inspect(engine)
    assert "name" in {column["name"] for column in inspector.get_columns("users")}
    assert "checkout_attempt_id" in {column["name"] for column in inspector.get_columns("transactions")}
    transaction_columns = {column["name"] for column in inspector.get_columns("transactions")}
    assert {"review_decision", "reviewed_by_admin_id", "reviewed_at", "review_reason"}.issubset(transaction_columns)
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT id FROM users").scalar_one() == 1
        assert connection.exec_driver_sql("SELECT id FROM transactions").scalar_one() == 1
        indexes = {index["name"] for index in inspector.get_indexes("transactions")}
        assert "uq_transactions_checkout_attempt_id" in indexes
    engine.dispose()


def test_order_schema_migration_adds_missing_columns_and_preserves_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-order-columns.sqlite'}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE orders")
        connection.exec_driver_sql("""
            CREATE TABLE orders (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                transaction_id INTEGER NOT NULL,
                items JSON NOT NULL,
                amount FLOAT NOT NULL,
                currency VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                payment_status VARCHAR NOT NULL,
                payment_method VARCHAR NOT NULL,
                created_at DATETIME NOT NULL
            )
        """)
        connection.exec_driver_sql("""
            INSERT INTO orders
                (id, user_id, transaction_id, items, amount, currency, status, payment_status, payment_method, created_at)
            VALUES
                (44, 8, 19, '[{"product_id":"p1","quantity":1}]', 129.0, 'USD', 'PROCESSING', 'SIMULATED', 'CARD', '2025-01-02 03:04:05')
        """)

    main.initialize_database(database_engine=engine)
    main.initialize_database(database_engine=engine)

    inspector = inspect(engine)
    order_columns = {column["name"]: column for column in inspector.get_columns("orders")}
    model_columns = {column.name for column in Order.__table__.columns}
    assert model_columns.issubset(order_columns)
    assert order_columns["shipping_address"]["type"].__class__.__name__ == "JSON"
    assert order_columns["billing_address"]["type"].__class__.__name__ == "JSON"
    with engine.connect() as connection:
        preserved = connection.exec_driver_sql(
            "SELECT id, user_id, transaction_id, items, amount FROM orders WHERE id = 44"
        ).one()
    assert tuple(preserved) == (44, 8, 19, '[{"product_id":"p1","quantity":1}]', 129.0)
    engine.dispose()


def test_order_schema_migration_fails_when_primary_key_is_missing(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-orders-without-id.sqlite'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("""
            CREATE TABLE orders (
                user_id INTEGER NOT NULL,
                transaction_id INTEGER NOT NULL,
                items JSON NOT NULL,
                amount FLOAT NOT NULL,
                currency VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                payment_status VARCHAR NOT NULL,
                payment_method VARCHAR NOT NULL,
                created_at DATETIME NOT NULL
            )
        """)

    try:
        with pytest.raises(RuntimeError, match=r"Cannot add missing primary key column orders\.id safely"):
            main._add_missing_order_columns(engine)
    finally:
        engine.dispose()


def test_admin_transaction_history_and_fraud_monitoring_are_distinct(database):
    admin = Admin(email="monitoring-admin@example.test", hashed_password=hash_password("admin-test-password"))
    customer = make_user(database, "monitoring-customer@example.test")
    database.add(admin)
    database.commit()
    database.refresh(admin)

    cases = [
        ("APPROVED", None, 0.10, "LOW", "APPROVE"),
        ("REVIEW", None, 0.50, "MEDIUM", "REVIEW"),
        ("REVIEW_APPROVED", "APPROVE", 0.55, "MEDIUM", "REVIEW"),
        ("REJECTED", "REJECT", 0.60, "MEDIUM", "REVIEW"),
        ("BLOCKED", None, 0.90, "HIGH", "BLOCK"),
    ]
    created = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for index, (status, review_decision, score, risk, decision) in enumerate(cases):
        transaction = Transaction(
            user_id=customer.id,
            amount=100 + index,
            transaction_data={"TransactionAmt": 100 + index},
            status=status,
            review_decision=review_decision,
            created_at=now - timedelta(minutes=index),
        )
        database.add(transaction)
        database.flush()
        prediction = FraudPrediction(
            transaction_id=transaction.id,
            fraud_probability=score,
            risk_level=risk,
            decision=decision,
            model_used="LogisticRegression_Baseline",
            created_at=now - timedelta(minutes=index),
        )
        database.add(prediction)
        created.append((transaction, prediction))

    unscored_transaction = Transaction(
        user_id=customer.id,
        amount=85.0,
        transaction_data={"TransactionAmt": 85.0},
        status="PENDING",
        created_at=now + timedelta(minutes=2),
    )
    database.add(unscored_transaction)
    database.flush()
    database.add(Order(
        user_id=customer.id,
        transaction_id=created[0][0].id,
        items=[],
        shipping_address={},
        billing_address={},
        amount=100.0,
        currency="USD",
        status="PROCESSING",
        payment_status="SIMULATED",
        payment_method="CARD",
    ))

    # Multiple persisted assessments for one transaction must still render once,
    # with the latest model outcome selected by timestamp and id.
    database.add(FraudPrediction(
        transaction_id=created[1][0].id,
        fraud_probability=0.52,
        risk_level="MEDIUM",
        decision="REVIEW",
        model_used="LogisticRegression_Baseline",
        created_at=now + timedelta(minutes=1),
    ))
    database.commit()

    history = main.get_admin_transactions(db=database, current_admin=admin)
    monitoring = main.get_recent_predictions(limit=100, db=database, current_admin=admin)

    assert len(history) == len(cases) + 1
    assert len({row["transaction_id"] for row in history}) == len(cases) + 1
    assert next(row for row in history if row["transaction_id"] == created[1][0].id)["fraud_prediction"]["fraud_probability"] == 0.52
    assert next(row for row in history if row["transaction_id"] == unscored_transaction.id)["fraud_prediction"] is None
    assert next(row for row in history if row["transaction_id"] == created[0][0].id)["order_id"] is not None
    assert {row["decision"] for row in monitoring} == {"REVIEW", "BLOCK"}
    assert {row["transaction_id"] for row in monitoring} == {created[index][0].id for index in (1, 2, 3, 4)}
    assert all(row["status"] != "APPROVED" for row in monitoring)


def test_admin_prediction_explanation_uses_fitted_pipeline_features(database, monkeypatch):
    admin = Admin(email="explanation-admin@example.test", hashed_password=hash_password("admin-test-password"))
    customer = make_user(database, "explanation-customer@example.test")
    database.add(admin)
    database.commit()
    database.refresh(admin)

    feature_names = ["TransactionAmt", "ProductCD", "P_emaildomain", "DeviceType", "DeviceInfo"]
    training = pd.DataFrame([
        [25.0, "W", "mail-a.test", "mobile", "phone-a"],
        [35.0, "W", "mail-a.test", "mobile", "phone-b"],
        [45.0, "H", "mail-b.test", "desktop", "computer-a"],
        [55.0, "H", "mail-b.test", "desktop", "computer-b"],
        [65.0, "C", "mail-c.test", "mobile", "phone-a"],
        [75.0, "C", "mail-c.test", "mobile", "phone-b"],
        [85.0, "R", "mail-d.test", "desktop", "computer-a"],
        [95.0, "R", "mail-d.test", "desktop", "computer-b"],
    ], columns=feature_names)
    labels = np.array([0, 0, 0, 1, 0, 1, 1, 1])
    fitted_pipeline = train_baseline_logistic_regression(
        training, labels, ["TransactionAmt"], feature_names[1:]
    )
    monkeypatch.setattr(main, "baseline_pipeline", fitted_pipeline)
    monkeypatch.setattr(main, "artifacts_loaded", True)

    actual_features = {
        "TransactionAmt": 72.0,
        "ProductCD": "C",
        "P_emaildomain": "mail-c.test",
        "DeviceType": "mobile",
        "DeviceInfo": "phone-a",
    }
    score = float(fitted_pipeline.predict_proba(pd.DataFrame([actual_features]))[0, 1])
    risk, decision = main.classify_fraud_score(score)
    transaction = Transaction(
        user_id=customer.id,
        amount=72.0,
        transaction_data=actual_features,
        status="REVIEW" if decision == "REVIEW" else "APPROVED",
        review_decision=None,
    )
    database.add(transaction)
    database.flush()
    prediction = FraudPrediction(
        transaction_id=transaction.id,
        fraud_probability=round(score, 4),
        risk_level=risk,
        decision=decision,
        model_used="LogisticRegression_Baseline",
    )
    database.add(prediction)
    database.commit()

    explanation = main.get_admin_transaction_explanation(
        transaction.id, db=database, current_admin=admin
    )

    assert explanation["transaction_id"] == transaction.id
    assert explanation["model_name"] == "LogisticRegression_Baseline"
    assert explanation["model_version"] is None
    assert explanation["risk_score"] == round(score, 4)
    assert explanation["risk_category"] == risk
    assert explanation["model_decision"] == decision
    assert {feature["name"] for feature in explanation["features"]} == set(feature_names)
    assert explanation["attribution_available"] is True
    assert len(explanation["feature_contributions"]) == len(feature_names)
    assert np.isclose(
        explanation["baseline_log_odds"] + sum(item["contribution_log_odds"] for item in explanation["feature_contributions"]),
        explanation["model_log_odds"],
        atol=1e-5,
    )
    assert "card1" not in {feature["name"] for feature in explanation["features"]}
    assert explanation["review"]["decision"] is None


def test_admin_monitoring_routes_require_admin_dependency():
    protected_paths = {
        "/api/admin/transactions",
        "/api/admin/fraud/recent",
        "/api/admin/transactions/{transaction_id}/explanation",
    }
    routes = {route.path: route for route in main.app.routes if route.path in protected_paths}

    assert set(routes) == protected_paths
    assert all(
        any(dependency.call == main.get_current_admin for dependency in route.dependant.dependencies)
        for route in routes.values()
    )

def test_catalog_and_order_routes_are_registered_without_admin_creation_route():
    paths = {(method, route.path) for route in main.app.routes for method in getattr(route, "methods", set())}
    assert ("GET", "/api/products") in paths
    assert ("GET", "/api/products/{product_id}") in paths
    assert ("POST", "/api/orders") in paths
    assert ("GET", "/api/orders") in paths
    assert not any(
        method == "POST"
        and "admin" in path
        and "auth/login" not in path
        and not path.startswith("/api/admin/reviews/")
        for method, path in paths
    )
