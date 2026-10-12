import os
import sys
from pathlib import Path

os.environ.setdefault("AUTH_TOKEN_SECRET", "test-only-signing-key-for-checkout-tests")
os.environ.setdefault("ENABLE_DEMO_ADMIN", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
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


def make_user(db, email):
    user = User(name="Test Customer", email=email, hashed_password=hash_password("test-only-password"))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def run_prediction(db, user, monkeypatch, score, attempt_id=None):
    monkeypatch.setattr(main, "baseline_pipeline", FixedProbabilityPipeline(score))
    monkeypatch.setattr(main, "artifacts_loaded", True)
    request = main.TransactionInput(TransactionAmt=129.0, ProductCD=None, checkout_attempt_id=attempt_id)
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



def test_additive_startup_migration_preserves_legacy_rows(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR, hashed_password VARCHAR, is_active BOOLEAN, created_at DATETIME)")
        connection.exec_driver_sql("CREATE TABLE transactions (id INTEGER PRIMARY KEY, user_id INTEGER, transaction_data JSON, amount FLOAT, currency VARCHAR, status VARCHAR, created_at DATETIME)")
        connection.exec_driver_sql("INSERT INTO users (id, email, hashed_password, is_active) VALUES (1, 'legacy@example.test', 'test-hash', 1)")
        connection.exec_driver_sql("INSERT INTO transactions (id, user_id, transaction_data, amount, currency, status) VALUES (1, 1, '{}', 129.0, 'USD', 'PENDING')")
    monkeypatch.setattr(main, "engine", engine)

    main.initialize_database()

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
