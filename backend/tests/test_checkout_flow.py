import os
import sys
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
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
from app.models.email_verification import EmailVerification
from app.models.order_verification import OrderVerification
from app.services.auth import (
    create_access_token, create_admin_access_token, hash_password,
    read_access_token, read_admin_access_token,
)
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
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    monkeypatch.setattr(main, "baseline_pipeline", FixedProbabilityPipeline(score))
    monkeypatch.setattr(main, "artifacts_loaded", True)
    verified_email(db, user)
    snapshot = dict(checkout_snapshot or {})
    snapshot.setdefault("verified_email", user.email)
    if "items" in snapshot:
        snapshot.setdefault("shipping_address", {"full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City", "postal_code": "560001", "country": "India", "address_confirmed": True})
        snapshot.setdefault("billing_address", {"full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City", "postal_code": "560001", "country": "India"})
        snapshot["shipping_address"].setdefault("address_confirmed", True)
    request = main.TransactionInput(TransactionAmt=129.0, ProductCD="C", checkout_attempt_id=attempt_id, checkout_snapshot=snapshot)
    return main.predict_fraud(request, db=db, current_user=user)


def verified_email(db, user):
    now = datetime.utcnow()
    record = db.query(EmailVerification).filter(EmailVerification.user_id == user.id).first()
    if record is None:
        db.add(EmailVerification(
            user_id=user.id, email_address=user.email, code_hash=None, status="VERIFIED",
            created_at=now, expires_at=now + timedelta(minutes=10), resend_after=now,
            window_started_at=now, sends_in_window=1, attempts=0, verified_at=now,
        ))
    else:
        record.email_address = user.email
        record.status = "VERIFIED"
        record.verified_at = now
    db.commit()


def order_request(transaction_id, product_id="p1", quantity=1, payment_method="CARD"):
    return main.CreateOrderRequest(
        transaction_id=transaction_id,
        items=[main.OrderItemRequest(product_id=product_id, quantity=quantity)],
        payment_method=payment_method,
        shipping_address={"full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City", "postal_code": "560001", "country": "India"},
        billing_address={"full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City", "postal_code": "560001", "country": "India"},
    )


def valid_checkout_snapshot(user, items=None, address=None):
    address = address or {
        "full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City",
        "postal_code": "560001", "country": "India", "address_confirmed": True,
    }
    return {
        "items": items or [{"product_id": "p1", "quantity": 1}],
        "payment_method": "CARD",
        "shipping_address": dict(address),
        "billing_address": {key: value for key, value in address.items() if key != "address_confirmed"},
        "verified_email": user.email,
    }


def verify_order_code(db, user, transaction_id, monkeypatch):
    sent_codes = []
    monkeypatch.setattr(main.email_otp, "send_code", lambda email, code: sent_codes.append((email, code)))
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).one()
    address = main.transaction_shipping_address(transaction)
    main.send_order_verification(
        transaction_id,
        main.OrderVerificationSendRequest(shipping_address=address, address_confirmed=True),
        db=db,
        current_user=user,
    )
    assert sent_codes and sent_codes[-1][0] == user.email
    main.verify_order_verification(
        transaction_id,
        main.OrderVerificationCodeRequest(code=sent_codes[-1][1]),
        db=db,
        current_user=user,
    )
    return sent_codes[-1][1]


def run_graph_prediction(db, user, monkeypatch, score, checkout_snapshot):
    verified_email(db, user)
    monkeypatch.setattr(main, "score_transaction", lambda *_args: (score, "GraphSAGE"))
    return main.predict_fraud(
        main.TransactionInput(
            TransactionAmt=129.0,
            checkout_attempt_id=f"graph-review-{user.id}",
            checkout_snapshot=checkout_snapshot,
        ),
        db=db,
        current_user=user,
    )


def test_configured_fraud_decision_thresholds():
    assert main.classify_fraud_score(main.FRAUD_REVIEW_THRESHOLD) == ("LOW", "APPROVE")
    assert main.classify_fraud_score(0.5) == ("MEDIUM", "REVIEW")
    assert main.classify_fraud_score(main.FRAUD_BLOCK_THRESHOLD) == ("MEDIUM", "REVIEW")
    assert main.classify_fraud_score(0.9) == ("HIGH", "BLOCK")
    with pytest.raises(ValueError):
        main.classify_fraud_score(float("nan"))


@pytest.mark.parametrize(("score", "risk", "decision"), [
    (main.FRAUD_REVIEW_THRESHOLD - 1e-9, "LOW", "APPROVE"),
    (main.FRAUD_REVIEW_THRESHOLD, "LOW", "APPROVE"),
    (main.FRAUD_REVIEW_THRESHOLD + 1e-9, "MEDIUM", "REVIEW"),
    (main.FRAUD_BLOCK_THRESHOLD, "MEDIUM", "REVIEW"),
    (main.FRAUD_BLOCK_THRESHOLD + 1e-9, "HIGH", "BLOCK"),
])
def test_risk_policy_threshold_edges(score, risk, decision):
    assert main.classify_fraud_score(score) == (risk, decision)


def test_historical_score_classification_is_consistent_across_admin_views(database):
    admin = Admin(email="classification-admin@example.test", hashed_password=hash_password("admin-test-password"))
    customer = make_user(database, "classification-customer@example.test")
    database.add(admin)
    database.commit()
    database.refresh(admin)
    transaction = Transaction(
        user_id=customer.id,
        amount=42.0,
        transaction_data={"TransactionAmt": 42.0, "ProductCD": "C"},
        status="REVIEW",
        review_reason="Saved operational review",
    )
    database.add(transaction)
    database.flush()
    prediction = FraudPrediction(
        transaction_id=transaction.id,
        fraud_probability=0.4476,
        risk_level="HIGH",
        decision="REVIEW",
        score_based_decision="BLOCK",
        model_used="GraphSAGE",
    )
    database.add(prediction)
    database.commit()

    before = (prediction.risk_level, prediction.score_based_decision, transaction.status, transaction.review_decision)
    summary = main.get_fraud_summary(db=database, current_admin=admin)
    recent = main.get_recent_predictions(limit=100, db=database, current_admin=admin)[0]
    admin_row = next(row for row in main.get_admin_transactions(db=database, current_admin=admin) if row["transaction_id"] == transaction.id)
    customer_row = main.get_admin_customer_details(customer.id, db=database, current_admin=admin)["transactions"][0]
    explanation = main.build_prediction_explanation(transaction, prediction, db=database)
    after = (prediction.risk_level, prediction.score_based_decision, transaction.status, transaction.review_decision)

    assert summary["risk_breakdown"] == {"LOW": 0, "MEDIUM": 1, "HIGH": 0}
    assert recent["risk_level"] == "MEDIUM" and recent["score_based_decision"] == "REVIEW"
    assert recent["recorded_risk_level"] == "HIGH" and recent["recorded_score_based_decision"] == "BLOCK"
    assert admin_row["fraud_prediction"]["risk_level"] == customer_row["fraud_prediction"]["risk_level"] == "MEDIUM"
    assert admin_row["fraud_prediction"]["score_based_decision"] == customer_row["fraud_prediction"]["score_based_decision"] == "REVIEW"
    assert customer_row["fraud_prediction"]["recorded_risk_level"] == "HIGH"
    assert customer_row["fraud_prediction"]["recorded_score_based_decision"] == "BLOCK"
    assert admin_row["fraud_prediction"]["operational_decision"] == customer_row["fraud_prediction"]["operational_decision"] == "REVIEW"
    assert explanation["risk_category"] == "MEDIUM"
    assert explanation["automated_score_decision"] == "REVIEW"
    assert explanation["historical_classification_notice"]
    assert "exceeds 0.70" not in explanation["historical_classification_notice"]
    assert recent["review_reason"] == explanation["historical_classification_notice"]
    assert before == after


def test_fraud_summary_counts_pending_review_separately_from_terminal_decisions(database):
    admin = Admin(email="summary-admin@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.flush()
    samples = [
        (0.90, "REVIEW", None, "REVIEW"),
        (0.95, "REJECTED", "REJECT", "REVIEW"),
        (0.10, "APPROVED", None, "APPROVE"),
        (0.85, "BLOCKED", None, "BLOCK"),
    ]
    for score, status, review_decision, decision in samples:
        transaction = Transaction(amount=12.0, transaction_data={"TransactionAmt": 12.0}, status=status, review_decision=review_decision)
        database.add(transaction)
        database.flush()
        risk, score_outcome = main.classify_fraud_score(score)
        database.add(FraudPrediction(
            transaction_id=transaction.id,
            fraud_probability=score,
            risk_level=risk,
            decision=decision,
            score_based_decision=score_outcome,
            model_used="GraphSAGE",
        ))
    database.commit()

    summary = main.get_fraud_summary(db=database, current_admin=admin)

    assert summary["total_predictions"] == 4
    assert summary["transaction_status_breakdown"] == {
        "approved": 1,
        "pending_review": 1,
        "blocked": 1,
        "admin_rejected": 1,
        "auto_approved": 1,
        "admin_approved": 0,
    }
    assert summary["transaction_status_rates"] == {
        "auto_approval": 0.25,
        "manual_review_queue": 0.25,
        "automated_prevention": 0.25,
    }


def test_checkout_policy_routes_medium_to_verification_and_high_to_review():
    verified = {"email_otp_verified": True, "delivery_address_confirmed": True}
    assert main.classify_checkout_score(main.FRAUD_REVIEW_THRESHOLD, verified) == ("LOW", "REVIEW")
    assert main.classify_checkout_score(main.FRAUD_REVIEW_THRESHOLD + 1e-9, verified) == ("MEDIUM", "REVIEW")
    assert main.classify_checkout_score(main.FRAUD_BLOCK_THRESHOLD, verified) == ("MEDIUM", "REVIEW")
    assert main.classify_checkout_score(main.FRAUD_BLOCK_THRESHOLD + 1e-9, verified) == ("HIGH", "REVIEW")


@pytest.mark.parametrize(("score", "risk", "score_outcome"), [
    (0.12, "LOW", "APPROVE"),
    (0.50, "MEDIUM", "REVIEW"),
    (0.90, "HIGH", "BLOCK"),
])
def test_verified_storefront_checkout_uses_score_for_three_level_policy(database, monkeypatch, score, risk, score_outcome):
    user = make_user(database, f"risk-{risk.lower()}@example.test")
    result = run_prediction(database, user, monkeypatch, score, checkout_snapshot={
        "items": [{"product_id": "p1", "quantity": 1}],
        "shipping_address": {"full_name": "Buyer", "line1": "1 Road", "city": "City", "postal_code": "560001", "country": "India", "address_confirmed": True},
        "billing_address": {"full_name": "Buyer", "line1": "1 Road", "city": "City", "postal_code": "560001", "country": "India"},
    })
    transaction = database.query(Transaction).one()
    assert result.risk_level == risk
    assert result.decision == "REVIEW"
    assert result.score_based_decision == score_outcome
    assert transaction.checkout_snapshot["verification_signals"]["email_otp_verified"] is True
    assert transaction.checkout_snapshot["verification_signals"]["delivery_address_confirmed"] is True


def test_low_score_without_both_verification_signals_is_not_auto_approved():
    assert main.classify_checkout_score(0.1, {"email_otp_verified": True}) == ("LOW", "REVIEW")


def test_high_score_is_held_for_review_even_with_both_verification_signals():
    assert main.classify_checkout_score(0.9, {
        "email_otp_verified": True,
        "delivery_address_confirmed": True,
    }) == ("HIGH", "REVIEW")


def test_medium_checkout_requires_order_otp_and_releases_after_evidence_reassessment(database, monkeypatch):
    user = make_user(database, "medium-checkout@example.test")
    admin = Admin(email="reviewer-medium@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    result = run_prediction(
        database, user, monkeypatch, 0.50, "medium-verification-attempt",
        valid_checkout_snapshot(user),
    )
    transaction = database.query(Transaction).one()
    prediction = database.query(FraudPrediction).one()

    assert (result.risk_level, result.decision, result.score_based_decision) == ("MEDIUM", "REVIEW", "REVIEW")
    assert transaction.status == "REVIEW"
    assert prediction.fraud_probability == 0.5
    assert prediction.decision == "REVIEW"
    pending = main.get_pending_reviews(db=database, current_admin=admin)
    assert len(pending) == 1
    assert pending[0]["transaction_id"] == transaction.id

    with pytest.raises(HTTPException) as blocked:
        main.create_order(order_request(transaction.id), db=database, current_user=user)
    assert blocked.value.status_code == 409

    verify_order_code(database, user, transaction.id, monkeypatch)
    database.refresh(transaction)
    database.refresh(prediction)
    # OTP verification records evidence but DOES NOT auto-approve:
    assert transaction.status == "REVIEW"
    assert prediction.decision == "REVIEW"
    assert prediction.score_based_decision == "REVIEW"
    assert prediction.fraud_probability == 0.5
    reassessment = transaction.risk_reassessment
    assert reassessment["ready_for_admin_decision"] is True
    assert reassessment["address_account_checks"]["address_check"]["format_valid"] is True
    amount_context = reassessment["address_account_checks"]["account_history"]["transaction_amount_context_last_30_days"]
    assert amount_context["currency"] == "USD"
    assert amount_context["current_amount"] == 129.0
    assert amount_context["same_currency_previous_transaction_count"] == 0
    assert "no amount cutoff" in amount_context["interpretation"]
    assert reassessment["graph_relationship_check"]["check_performed"] is True

    # Order still blocked before admin decision
    with pytest.raises(HTTPException) as blocked_before_admin:
        main.create_order(order_request(transaction.id), db=database, current_user=user)
    assert blocked_before_admin.value.status_code == 409

    # Admin reviews and approves
    main.approve_review(
        transaction.id,
        main.AdminReviewRequest(reason="Admin verified medium risk transaction"),
        db=database,
        current_admin=admin,
    )
    database.refresh(transaction)
    assert transaction.status == "REVIEW_APPROVED"
    assert transaction.review_decision == "APPROVE"

    status = main.get_transaction_status(transaction.id, db=database, current_user=user)
    assert status["operational_decision"] == "ADMIN_APPROVE"
    assert status["fraud_prediction"]["decision"] == "REVIEW"

    order = main.create_order(order_request(transaction.id), db=database, current_user=user)
    assert order["transaction_id"] == transaction.id


def test_medium_delivery_failure_history_holds_for_admin_review_until_reasoned_decision(database, monkeypatch):
    user = make_user(database, "medium-delivery-history@example.test")
    other_user = make_user(database, "prior-delivery-account@example.test")
    snapshot = valid_checkout_snapshot(user)
    prior_snapshot = valid_checkout_snapshot(other_user, address=snapshot["shipping_address"])
    prior_transaction = Transaction(
        user_id=other_user.id,
        checkout_attempt_id="prior-delivery-attempt",
        checkout_snapshot=prior_snapshot,
        transaction_data={"TransactionAmt": 129.0},
        amount=129.0,
        currency="USD",
        status="ORDERED",
    )
    database.add(prior_transaction)
    database.flush()
    database.add(Order(
        user_id=other_user.id,
        transaction_id=prior_transaction.id,
        items=[{"product_id": "p1", "quantity": 1}],
        shipping_address={key: value for key, value in prior_snapshot["shipping_address"].items() if key != "address_confirmed"},
        billing_address=prior_snapshot["billing_address"],
        amount=129.0,
        currency="USD",
        status="DELIVERY_REFUSED",
        payment_status="SIMULATED",
        payment_method="CARD",
    ))
    database.commit()

    prediction = run_prediction(
        database, user, monkeypatch, 0.5, "medium-delivery-history-attempt", snapshot,
    )
    transaction = database.query(Transaction).filter(Transaction.id == prediction.transaction_id).one()
    verify_order_code(database, user, transaction.id, monkeypatch)
    database.refresh(transaction)
    saved_prediction = database.query(FraudPrediction).filter(FraudPrediction.transaction_id == transaction.id).one()

    assert transaction.status == "REVIEW"
    assert transaction.review_decision is None
    assert saved_prediction.risk_level == "MEDIUM"
    assert saved_prediction.decision == "REVIEW"
    assert saved_prediction.score_based_decision == "REVIEW"
    assert saved_prediction.fraud_probability == 0.5
    assert transaction.risk_reassessment["medium_verification"]["status"] == "HELD_FOR_ADMIN_REVIEW"
    assert "DELIVERY_REFUSED (1)" in transaction.risk_reassessment["medium_verification"]["decision_reason"]
    assert "not proof of fraud" in transaction.risk_reassessment["medium_verification"]["decision_reason"]
    assert "medium_verification_release" not in transaction.risk_reassessment

    admin = Admin(email="medium-delivery-reviewer@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    pending = main.get_pending_reviews(db=database, current_admin=admin)
    row = next(item for item in pending if item["transaction_id"] == transaction.id)
    assert row["fraud_prediction"]["risk_level"] == "MEDIUM"
    assert row["fraud_prediction"]["decision"] == "REVIEW"
    assert row["fraud_prediction"]["operational_decision"] == "REVIEW"
    assert "DELIVERY_REFUSED" in row["fraud_prediction"]["review_reason"]

    with pytest.raises(HTTPException) as blocked_without_review:
        main.create_order(order_request(transaction.id), db=database, current_user=user)
    assert blocked_without_review.value.status_code == 409
    assert database.query(Order).filter(Order.transaction_id == transaction.id).count() == 0

    with pytest.raises(HTTPException) as missing_reason:
        main.approve_review(transaction.id, main.AdminReviewRequest(), db=database, current_admin=admin)
    assert missing_reason.value.status_code == 422
    assert transaction.status == "REVIEW"
    assert transaction.review_decision is None

    challenge = database.query(OrderVerification).filter(OrderVerification.transaction_id == transaction.id).one()
    challenge.expires_at = datetime.utcnow() - timedelta(seconds=1)
    database.commit()
    main.approve_review(
        transaction.id,
        main.AdminReviewRequest(reason="Reviewed the recorded delivery outcome; no confirmed fraud evidence."),
        db=database,
        current_admin=admin,
    )
    with pytest.raises(HTTPException) as expired_order_otp:
        main.create_order(order_request(transaction.id), db=database, current_user=user)
    assert expired_order_otp.value.status_code == 403
    verify_order_code(database, user, transaction.id, monkeypatch)
    order = main.create_order(order_request(transaction.id), db=database, current_user=user)
    assert order["transaction_id"] == transaction.id
    assert database.query(Order).filter(Order.transaction_id == transaction.id).count() == 1
    assert saved_prediction.fraud_probability == 0.5


def test_medium_release_does_not_treat_shared_address_or_incomplete_graph_alone_as_fraud(database, monkeypatch):
    user = make_user(database, "medium-shared-address@example.test")
    other_user = make_user(database, "medium-shared-address-other@example.test")
    snapshot = valid_checkout_snapshot(user)
    other_transaction = Transaction(
        user_id=other_user.id,
        checkout_attempt_id="shared-address-history-only",
        checkout_snapshot=valid_checkout_snapshot(other_user, address=snapshot["shipping_address"]),
        transaction_data={"TransactionAmt": 129.0},
        amount=129.0,
        currency="USD",
        status="VERIFY",
    )
    database.add(other_transaction)
    database.commit()

    prediction = run_graph_prediction(database, user, monkeypatch, 0.5, snapshot)
    incomplete_context = {
        "training_topology": "P_emaildomain, DeviceInfo",
        "live_topology": "P_emaildomain",
        "missing_edge_features": ["DeviceInfo"],
        "connected_neighbors": 0,
        "topology_validation_status": "UNVALIDATED_INSUFFICIENT_DATA",
        "topology_note": "DeviceInfo relationship evidence is unavailable for this checkout.",
    }
    monkeypatch.setattr(main, "_build_live_gnn_graph", lambda *_args, **_kwargs: (None, incomplete_context))
    verify_order_code(database, user, prediction.transaction_id, monkeypatch)

    transaction = database.query(Transaction).filter(Transaction.id == prediction.transaction_id).one()
    history = transaction.risk_reassessment["medium_verification"]["address_account_checks"]["account_history"]
    graph = transaction.risk_reassessment["medium_verification"]["graph_relationship_check"]
    assert history["other_accounts_with_matching_checkout_address_last_30_days"] == 1
    assert history["other_new_accounts_with_matching_checkout_address_last_30_days"] == 1
    assert history["shared_address_is_informational_only"] is True
    assert graph["status"] == "INCOMPLETE_EVIDENCE"
    assert transaction.status == "REVIEW"
    assert transaction.risk_reassessment["ready_for_admin_decision"] is True
    assert transaction.risk_reassessment["score"] == 0.5


def test_medium_graph_check_failure_keeps_transaction_held(database, monkeypatch):
    user = make_user(database, "medium-graph-failure@example.test")
    prediction = run_graph_prediction(database, user, monkeypatch, 0.5, valid_checkout_snapshot(user))
    monkeypatch.setattr(
        main, "_build_live_gnn_graph",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("controlled graph check failure")),
    )
    sent_codes = []
    monkeypatch.setattr(main.email_otp, "send_code", lambda email, code: sent_codes.append(code))
    address = main.transaction_shipping_address(database.query(Transaction).filter(Transaction.id == prediction.transaction_id).one())
    main.send_order_verification(
        prediction.transaction_id,
        main.OrderVerificationSendRequest(shipping_address=address, address_confirmed=True),
        db=database,
        current_user=user,
    )
    with pytest.raises(HTTPException) as failed_check:
        main.verify_order_verification(
            prediction.transaction_id,
            main.OrderVerificationCodeRequest(code=sent_codes[0]),
            db=database,
            current_user=user,
        )
    transaction = database.query(Transaction).filter(Transaction.id == prediction.transaction_id).one()
    assert failed_check.value.status_code == 503
    assert transaction.status == "REVIEW"
    assert database.query(Order).filter(Order.transaction_id == transaction.id).count() == 0


def test_medium_release_is_invalidated_if_confirmed_address_changes(database, monkeypatch):
    user = make_user(database, "medium-stale-address@example.test")
    result = run_prediction(database, user, monkeypatch, 0.5, "medium-stale-attempt", valid_checkout_snapshot(user))
    verify_order_code(database, user, result.transaction_id, monkeypatch)
    transaction = database.query(Transaction).one()
    snapshot = dict(transaction.checkout_snapshot)
    snapshot["shipping_address"] = dict(snapshot["shipping_address"], line1="Changed after verification")
    transaction.checkout_snapshot = snapshot
    database.commit()
    with pytest.raises(HTTPException) as blocked:
        main.create_order(order_request(transaction.id), db=database, current_user=user)
    assert blocked.value.status_code == 409
    assert database.query(Order).count() == 0


def test_failed_medium_otp_keeps_checkout_held_and_blocks_order(database, monkeypatch):
    user = make_user(database, "medium-invalid-otp@example.test")
    result = run_prediction(database, user, monkeypatch, 0.5, "medium-invalid-otp-attempt", valid_checkout_snapshot(user))
    sent_codes = []
    monkeypatch.setattr(main.email_otp, "send_code", lambda email, code: sent_codes.append(code))
    address = main.transaction_shipping_address(database.query(Transaction).one())
    main.send_order_verification(
        result.transaction_id,
        main.OrderVerificationSendRequest(shipping_address=address, address_confirmed=True),
        db=database,
        current_user=user,
    )
    with pytest.raises(HTTPException) as incorrect:
        main.verify_order_verification(
            result.transaction_id,
            main.OrderVerificationCodeRequest(code="000000" if sent_codes[0] != "000000" else "000001"),
            db=database,
            current_user=user,
        )
    assert incorrect.value.status_code == 400
    transaction = database.query(Transaction).one()
    assert transaction.status == "REVIEW"
    with pytest.raises(HTTPException) as blocked:
        main.create_order(order_request(transaction.id), db=database, current_user=user)
    assert blocked.value.status_code == 409
    assert database.query(Order).count() == 0


def test_prediction_persists_transaction_and_baseline_decision(database, monkeypatch):
    user = make_user(database, "buyer-one@example.test")
    result = run_prediction(database, user, monkeypatch, 0.2)
    transaction = database.query(Transaction).one()
    prediction = database.query(FraudPrediction).one()
    assert result.transaction_id == transaction.id
    assert prediction.decision == "REVIEW"
    assert prediction.score_based_decision == "APPROVE"
    assert transaction.status == "REVIEW"
    assert prediction.model_used == "LogisticRegression_Baseline"


def test_storefront_prediction_rejects_client_supplied_total_before_model_scoring(database, monkeypatch):
    user = make_user(database, "subtotal-check@example.test")
    verified_email(database, user)
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    monkeypatch.setattr(main, "artifacts_loaded", True)

    class MustNotScore:
        def predict_proba(self, _frame):
            raise AssertionError("Mismatched cart totals must be rejected before scoring")

    monkeypatch.setattr(main, "baseline_pipeline", MustNotScore())
    request = main.TransactionInput(
        TransactionAmt=128,
        checkout_snapshot={
            "items": [{"product_id": "p1", "quantity": 1}],
            "payment_method": "CARD",
            "shipping_address": {},
            "billing_address": {},
            "verified_email": user.email,
        },
    )

    with pytest.raises(HTTPException) as error:
        main.predict_fraud(request, db=database, current_user=user)

    assert error.value.status_code == 409
    assert database.query(Transaction).count() == 0


def test_storefront_prediction_rejects_missing_addresses_before_model_scoring(database, monkeypatch):
    user = make_user(database, "address-required@example.test")
    verified_email(database, user)
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    monkeypatch.setattr(main, "artifacts_loaded", True)

    class MustNotScore:
        def predict_proba(self, _frame):
            raise AssertionError("Missing checkout addresses must be rejected before scoring")

    monkeypatch.setattr(main, "baseline_pipeline", MustNotScore())
    request = main.TransactionInput(
        TransactionAmt=129,
        checkout_snapshot={
            "items": [{"product_id": "p1", "quantity": 1}],
            "shipping_address": {},
            "billing_address": {},
            "verified_email": user.email,
        },
    )
    with pytest.raises(HTTPException) as error:
        main.predict_fraud(request, db=database, current_user=user)
    assert error.value.status_code == 422
    assert database.query(Transaction).count() == 0


def test_storefront_prediction_rejects_unconfirmed_shipping_address_before_model_scoring(database, monkeypatch):
    user = make_user(database, "confirmation-required@example.test")
    verified_email(database, user)
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    monkeypatch.setattr(main, "artifacts_loaded", True)

    class MustNotScore:
        def predict_proba(self, _frame):
            raise AssertionError("Unconfirmed delivery addresses must be rejected before scoring")

    monkeypatch.setattr(main, "baseline_pipeline", MustNotScore())
    address = {"full_name": "Buyer", "line1": "1 Road", "city": "City", "postal_code": "560001", "country": "India"}
    with pytest.raises(HTTPException) as error:
        main.predict_fraud(main.TransactionInput(
            TransactionAmt=129,
            checkout_snapshot={"items": [{"product_id": "p1", "quantity": 1}], "shipping_address": address, "billing_address": address},
        ), db=database, current_user=user)
    assert error.value.status_code == 422
    assert database.query(Transaction).count() == 0



def test_prediction_retries_reuse_the_same_transaction(database, monkeypatch):
    user = make_user(database, "retry@example.test")
    first = run_prediction(database, user, monkeypatch, 0.2, attempt_id="checkout-attempt-test")
    second = run_prediction(database, user, monkeypatch, 0.9, attempt_id="checkout-attempt-test")
    assert first.transaction_id == second.transaction_id
    assert second.decision == "REVIEW"
    assert second.score_based_decision == "APPROVE"
    assert database.query(Transaction).count() == 1
    assert database.query(FraudPrediction).count() == 1


def test_prediction_attempt_id_cannot_be_reused_for_changed_payload(database, monkeypatch):
    user = make_user(database, "changed-retry@example.test")
    run_prediction(database, user, monkeypatch, 0.2, attempt_id="stable-attempt-test")
    changed = main.TransactionInput(TransactionAmt=130.0, checkout_attempt_id="stable-attempt-test", checkout_snapshot={"verified_email": user.email})
    with pytest.raises(HTTPException) as error:
        main.predict_fraud(changed, db=database, current_user=user)
    assert error.value.status_code == 409
    assert database.query(Transaction).count() == 1

def test_failed_prediction_does_not_create_transaction(database, monkeypatch):
    user = make_user(database, "buyer-two@example.test")
    verified_email(database, user)

    class BrokenPipeline:
        def predict_proba(self, _frame):
            raise RuntimeError("internal model error")

    monkeypatch.setattr(main, "baseline_pipeline", BrokenPipeline())
    monkeypatch.setattr(main, "artifacts_loaded", True)
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    with pytest.raises(HTTPException) as error:
        main.predict_fraud(main.TransactionInput(TransactionAmt=129, checkout_snapshot={"verified_email": user.email}), db=database, current_user=user)
    assert error.value.status_code == 503
    assert "internal model error" not in error.value.detail
    assert database.query(Transaction).count() == 0
    assert database.query(FraudPrediction).count() == 0


def test_registration_database_failure_is_not_reported_as_email_conflict(database, monkeypatch):
    def fail_commit():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(database, "commit", fail_commit)

    with pytest.raises(HTTPException) as error:
        main.register_customer(
            main.RegisterRequest(name="New Customer", email="new@example.test", password="test-password"),
            db=database,
        )

    assert error.value.status_code == 503
    assert error.value.detail == "Account could not be created; please retry"
    assert database.query(User).filter(User.email == "new@example.test").first() is None


def test_transaction_amount_must_be_positive_and_finite():
    with pytest.raises(ValidationError):
        main.TransactionInput(TransactionAmt=0)
    with pytest.raises(ValidationError):
        main.TransactionInput(TransactionAmt=float("inf"))


@pytest.mark.parametrize("postal_code", ["12345", "1234567", "12A456", " 12345 "])
def test_order_address_rejects_invalid_indian_pin(postal_code):
    with pytest.raises(ValidationError):
        main.OrderAddressInput(full_name="Buyer", line1="1 Road", city="City", postal_code=postal_code, country="India")


@pytest.mark.parametrize("missing", ["full_name", "line1", "city", "country"])
def test_order_address_rejects_missing_required_field(missing):
    address = {"full_name": "Buyer", "line1": "1 Road", "city": "City", "postal_code": "560001", "country": "India"}
    del address[missing]
    with pytest.raises(ValidationError):
        main.OrderAddressInput(**address)


def test_order_address_accepts_six_digit_pin():
    address = main.OrderAddressInput(full_name="Buyer", line1="1 Road", city="City", locality="Area", state="Karnataka", postal_code="560001", country="India")
    assert address.postal_code == "560001"
    assert address.locality == "Area"


def test_approved_owned_transaction_creates_idempotent_order(database, monkeypatch):
    user = make_user(database, "buyer-three@example.test")
    prediction = run_prediction(database, user, monkeypatch, 0.2, checkout_snapshot=valid_checkout_snapshot(user))
    verify_order_code(database, user, prediction.transaction_id, monkeypatch)
    request = order_request(prediction.transaction_id)
    with pytest.raises(HTTPException) as unapproved:
        main.create_order(request, db=database, current_user=user)
    assert unapproved.value.status_code == 409
    admin = Admin(email="admin-buyer-three@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    main.approve_review(prediction.transaction_id, main.AdminReviewRequest(reason="Admin review verified"), db=database, current_admin=admin)
    first = main.create_order(request, db=database, current_user=user)
    second = main.create_order(request, db=database, current_user=user)
    assert first["id"] == second["id"]
    assert first["amount"] == 129.0
    assert first["paymentStatus"] == "SIMULATED"
    assert first["items"][0]["name"] == "Aurora Wireless Headphones"
    assert database.query(Order).count() == 1
    assert main.get_orders(db=database, current_user=user)[0]["id"] == first["id"]
    assert database.query(Transaction).one().status == "ORDERED"


def test_cod_order_records_method_and_remains_unpaid(database, monkeypatch):
    user = make_user(database, "cod-order@example.test")
    prediction = run_prediction(database, user, monkeypatch, 0.1, checkout_snapshot=valid_checkout_snapshot(user))
    verify_order_code(database, user, prediction.transaction_id, monkeypatch)
    admin = Admin(email="admin-cod@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    main.approve_review(prediction.transaction_id, main.AdminReviewRequest(reason="Admin review verified"), db=database, current_admin=admin)

    result = main.create_order(
        order_request(prediction.transaction_id, payment_method="COD"),
        db=database,
        current_user=user,
    )

    stored = database.query(Order).one()
    assert result["payment_method"] == "COD"
    assert result["paymentStatus"] == "PENDING_CASH_COLLECTION"
    assert stored.payment_method == "COD"
    assert stored.payment_status != "PAID"


def test_checkout_requires_fresh_order_otp_even_after_login_email_verification(database, monkeypatch):
    user = make_user(database, "fresh-order-code@example.test")
    prediction = run_prediction(database, user, monkeypatch, 0.1, checkout_snapshot=valid_checkout_snapshot(user))
    admin = Admin(email="admin-fresh@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    main.approve_review(prediction.transaction_id, main.AdminReviewRequest(reason="Admin review verified"), db=database, current_admin=admin)
    with pytest.raises(HTTPException) as error:
        main.create_order(order_request(prediction.transaction_id), db=database, current_user=user)
    assert error.value.status_code == 403
    verify_order_code(database, user, prediction.transaction_id, monkeypatch)
    order = main.create_order(order_request(prediction.transaction_id), db=database, current_user=user)
    assert order["transaction_id"] == prediction.transaction_id
    assert database.query(Order).count() == 1


def test_order_otp_requires_current_explicit_address_confirmation(database, monkeypatch):
    user = make_user(database, "address-confirmation-required@example.test")
    prediction = run_prediction(database, user, monkeypatch, 0.1, checkout_snapshot=valid_checkout_snapshot(user))
    address = main.transaction_shipping_address(
        database.query(Transaction).filter(Transaction.id == prediction.transaction_id).one()
    )
    with pytest.raises(HTTPException) as missing_confirmation:
        main.send_order_verification(
            prediction.transaction_id,
            main.OrderVerificationSendRequest(shipping_address=address),
            db=database,
            current_user=user,
        )
    assert missing_confirmation.value.status_code == 409
    assert database.query(OrderVerification).count() == 0

    sent_codes = []
    monkeypatch.setattr(main.email_otp, "send_code", lambda _email, code: sent_codes.append(code))
    main.send_order_verification(
        prediction.transaction_id,
        main.OrderVerificationSendRequest(shipping_address=address, address_confirmed=True),
        db=database,
        current_user=user,
    )
    challenge = database.query(OrderVerification).one()
    assert challenge.address_confirmed_at is not None
    assert challenge.shipping_address_hash == main.shipping_address_hash(address)
    assert len(sent_codes) == 1


def test_one_attempts_order_otp_cannot_authorize_another_order(database, monkeypatch):
    user = make_user(database, "attempt-scoped@example.test")
    first = run_prediction(database, user, monkeypatch, 0.1, "attempt-one", valid_checkout_snapshot(user))
    second = run_prediction(database, user, monkeypatch, 0.1, "attempt-two", valid_checkout_snapshot(user))
    first_code = verify_order_code(database, user, first.transaction_id, monkeypatch)
    with pytest.raises(HTTPException) as error:
        main.verify_order_verification(
            second.transaction_id,
            main.OrderVerificationCodeRequest(code=first_code),
            db=database,
            current_user=user,
        )
    assert error.value.status_code == 409
    admin = Admin(email="admin-one-attempt@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    main.approve_review(second.transaction_id, main.AdminReviewRequest(reason="Admin review verified"), db=database, current_admin=admin)
    with pytest.raises(HTTPException) as no_order_code:
        main.create_order(order_request(second.transaction_id), db=database, current_user=user)
    assert no_order_code.value.status_code == 403


def test_wrong_expired_order_codes_and_attempt_lockout(database, monkeypatch):
    user = make_user(database, "bad-order-code@example.test")
    prediction = run_prediction(database, user, monkeypatch, 0.1, checkout_snapshot=valid_checkout_snapshot(user))
    sent = []
    monkeypatch.setattr(main.email_otp, "send_code", lambda _email, code: sent.append(code))
    main.send_order_verification(
        prediction.transaction_id,
        main.OrderVerificationSendRequest(shipping_address=main.transaction_shipping_address(database.query(Transaction).one()), address_confirmed=True),
        db=database,
        current_user=user,
    )
    for attempt in range(main.ORDER_OTP_MAX_ATTEMPTS):
        with pytest.raises(HTTPException) as error:
            main.verify_order_verification(
                prediction.transaction_id,
                main.OrderVerificationCodeRequest(code="000000" if sent[-1] != "000000" else "000001"),
                db=database,
                current_user=user,
            )
        assert error.value.status_code == (429 if attempt == main.ORDER_OTP_MAX_ATTEMPTS - 1 else 400)
    challenge = database.query(main.OrderVerification).one()
    assert challenge.status == "LOCKED"
    assert challenge.code_hash is None

    # A separately issued code expires server-side and cannot authorize ordering.
    challenge.status = "PENDING"
    challenge.code_hash = main.order_otp_hash(user.id, user.email, prediction.transaction_id, challenge.checkout_attempt_id, sent[-1])
    challenge.expires_at = datetime.utcnow() - timedelta(seconds=1)
    challenge.attempts = 0
    database.commit()
    with pytest.raises(HTTPException) as expired:
        main.verify_order_verification(
            prediction.transaction_id,
            main.OrderVerificationCodeRequest(code=sent[-1]),
            db=database,
            current_user=user,
        )
    assert expired.value.status_code == 410


def test_resend_invalidates_old_code_and_enforces_cooldown(database, monkeypatch):
    user = make_user(database, "resend-order-code@example.test")
    prediction = run_prediction(database, user, monkeypatch, 0.1, checkout_snapshot=valid_checkout_snapshot(user))
    codes = iter(["123456", "654321"])
    monkeypatch.setattr(main.secrets, "randbelow", lambda _maximum: int(next(codes)))
    monkeypatch.setattr(main.email_otp, "send_code", lambda *_args: None)
    request = main.OrderVerificationSendRequest(shipping_address=main.transaction_shipping_address(
        database.query(Transaction).filter(Transaction.id == prediction.transaction_id).one()
    ), address_confirmed=True)
    main.send_order_verification(prediction.transaction_id, request, db=database, current_user=user)
    with pytest.raises(HTTPException) as cooldown:
        main.send_order_verification(prediction.transaction_id, request, db=database, current_user=user)
    assert cooldown.value.status_code == 429
    challenge = database.query(main.OrderVerification).one()
    challenge.resend_after = datetime.utcnow() - timedelta(seconds=1)
    database.commit()
    main.send_order_verification(prediction.transaction_id, request, db=database, current_user=user)
    with pytest.raises(HTTPException) as old_code:
        main.verify_order_verification(
            prediction.transaction_id, main.OrderVerificationCodeRequest(code="123456"), db=database, current_user=user
        )
    assert old_code.value.status_code == 400
    main.verify_order_verification(
        prediction.transaction_id, main.OrderVerificationCodeRequest(code="654321"), db=database, current_user=user
    )


def test_order_challenge_is_private_and_address_changes_require_reconfirmation(database, monkeypatch):
    user = make_user(database, "address-order-code@example.test")
    other = make_user(database, "other-order-code@example.test")
    prediction = run_prediction(database, user, monkeypatch, 0.1, checkout_snapshot=valid_checkout_snapshot(user))
    with pytest.raises(HTTPException) as unauthenticated:
        main.get_current_user(credentials=None, db=database)
    assert unauthenticated.value.status_code == 401
    verify_order_code(database, user, prediction.transaction_id, monkeypatch)
    admin = Admin(email="admin-private-addr@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    main.approve_review(prediction.transaction_id, main.AdminReviewRequest(reason="Admin review verified"), db=database, current_admin=admin)
    with pytest.raises(HTTPException) as other_user:
        main.verify_order_verification(
            prediction.transaction_id, main.OrderVerificationCodeRequest(code="123456"), db=database, current_user=other
        )
    assert other_user.value.status_code == 404
    transaction = database.query(Transaction).filter(Transaction.id == prediction.transaction_id).one()
    transaction.checkout_snapshot["shipping_address"]["line1"] = "2 Changed Road"
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(transaction, "checkout_snapshot")
    database.commit()
    with pytest.raises(HTTPException) as changed:
        main.create_order(order_request(prediction.transaction_id), db=database, current_user=user)
    assert changed.value.status_code == 403
    assert database.query(Order).count() == 0


def test_order_retry_is_idempotent_and_concurrent_submissions_do_not_duplicate(database, monkeypatch):
    user = make_user(database, "concurrent-order@example.test")
    prediction = run_prediction(database, user, monkeypatch, 0.1, checkout_snapshot=valid_checkout_snapshot(user))
    verify_order_code(database, user, prediction.transaction_id, monkeypatch)
    admin = Admin(email="admin-concurrent@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    main.approve_review(prediction.transaction_id, main.AdminReviewRequest(reason="Admin review verified"), db=database, current_admin=admin)
    database.commit()
    database.expire_all()
    request = order_request(prediction.transaction_id)
    sessions = sessionmaker(bind=database.get_bind())
    barrier = Barrier(2)

    def submit_order():
        with sessions() as concurrent_db:
            concurrent_user = concurrent_db.query(User).filter(User.id == user.id).one()
            barrier.wait(timeout=15)
            try:
                return main.create_order(request, db=concurrent_db, current_user=concurrent_user)
            except HTTPException as error:
                return error

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _index: submit_order(), range(2)))
    assert any(isinstance(result, dict) for result in results)
    assert all(not isinstance(result, HTTPException) or result.status_code == 503 for result in results)
    assert database.query(Order).filter(Order.transaction_id == prediction.transaction_id).count() == 1
    retry = main.create_order(request, db=database, current_user=user)
    assert database.query(Order).filter(Order.transaction_id == prediction.transaction_id).one().id == retry["id"]


def test_completed_order_verification_status_exposes_existing_order_for_recovery(database, monkeypatch):
    user = make_user(database, "completed-order-recovery@example.test")
    prediction = run_prediction(
        database, user, monkeypatch, 0.12, "completed-order-recovery-attempt",
        valid_checkout_snapshot(user),
    )
    verify_order_code(database, user, prediction.transaction_id, monkeypatch)
    admin = Admin(email="admin-recovery@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    main.approve_review(prediction.transaction_id, main.AdminReviewRequest(reason="Admin review verified"), db=database, current_admin=admin)
    order = main.create_order(order_request(prediction.transaction_id), db=database, current_user=user)

    status = main.get_order_verification_status(
        prediction.transaction_id,
        db=database,
        current_user=user,
    )
    assert status["status"] == "complete"
    assert status["transaction_id"] == prediction.transaction_id
    assert status["order_id"] == order["id"]
    assert status["transaction_status"] == "ORDERED"
    assert database.query(Order).filter(Order.transaction_id == prediction.transaction_id).count() == 1


def test_backend_checkout_snapshot_survives_review_and_controls_resumed_order(database, monkeypatch):
    user = make_user(database, "snapshot-review@example.test")
    admin = Admin(email="admin-snapshot@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    snapshot_address = {"full_name": "Saved Buyer", "line1": "9 Saved Road", "city": "Saved City", "postal_code": "560002", "country": "India", "address_confirmed": True}
    snapshot = {
        "items": [{"product_id": "p1", "quantity": 1}],
        "payment_method": "PAYPAL",
        "shipping_address": snapshot_address,
        "billing_address": snapshot_address,
    }
    snapshot["verified_email"] = user.email
    prediction = run_prediction(database, user, monkeypatch, 0.5, "snapshot-review-attempt", snapshot)
    transaction = database.query(Transaction).one()
    assert transaction.checkout_snapshot["payment_method"] == snapshot["payment_method"]
    assert transaction.checkout_snapshot["items"][0]["store_category"] == "Audio"
    assert transaction.transaction_data["ProductCD"] == "W"
    assert transaction.transaction_data["DeviceInfo"] == "UNKNOWN"
    assert transaction.transaction_data["P_emaildomain"] == "example.test"
    assert prediction.decision == "REVIEW"

    # The client retry may have stale details; persisted checkout data is authoritative.
    stale_request = order_request(prediction.transaction_id, payment_method="PAYPAL")
    verify_order_code(database, user, prediction.transaction_id, monkeypatch)
    main.approve_review(prediction.transaction_id, main.AdminReviewRequest(reason="Admin review verified"), db=database, current_admin=admin)
    status = main.get_transaction_status(prediction.transaction_id, db=database, current_user=user)
    assert status["transaction_id"] == prediction.transaction_id
    assert status["checkout_snapshot"] == transaction.checkout_snapshot
    assert status["status"] == "REVIEW_APPROVED"
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
    assert len(review_routes) == 4
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


def test_review_database_failure_rolls_back_and_returns_service_error(database, monkeypatch):
    customer = make_user(database, "review-db-error@example.test")
    admin = Admin(email="review-db-error-admin@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    database.refresh(admin)
    prediction = run_prediction(database, customer, monkeypatch, 0.5)

    def fail_commit():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(database, "commit", fail_commit)
    with pytest.raises(HTTPException) as error:
        main.approve_review(
            prediction.transaction_id, main.AdminReviewRequest(), db=database, current_admin=admin
        )

    assert error.value.status_code == 503
    database.expire_all()
    transaction = database.query(Transaction).one()
    assert transaction.status == "REVIEW"
    assert transaction.review_decision is None


def test_medium_verification_can_order_but_blocked_and_rejected_cannot(database, monkeypatch):
    admin = Admin(email="review-decider@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    approved_user = make_user(database, "admin-approved@example.test")
    review = run_prediction(database, approved_user, monkeypatch, 0.5, checkout_snapshot=valid_checkout_snapshot(approved_user))
    assert review.decision == "REVIEW"
    verify_order_code(database, approved_user, review.transaction_id, monkeypatch)
    with pytest.raises(HTTPException) as unapproved_error:
        main.create_order(order_request(review.transaction_id), db=database, current_user=approved_user)
    assert unapproved_error.value.status_code == 409
    main.approve_review(review.transaction_id, main.AdminReviewRequest(reason="Admin review verified"), db=database, current_admin=admin)
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


def test_mixed_code_basket_requires_admin_review_before_idempotent_order(database_with_legacy_orders, monkeypatch):
    database = database_with_legacy_orders
    user = make_user(database, "three-item-review@example.test")
    verified_email(database, user)
    monkeypatch.setattr(main, "baseline_pipeline", FixedProbabilityPipeline(0.5))
    monkeypatch.setattr(main, "artifacts_loaded", True)
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    prediction = main.predict_fraud(
        main.TransactionInput(TransactionAmt=357.5, checkout_attempt_id="three-item-review-attempt", checkout_snapshot=valid_checkout_snapshot(user, items=[{"product_id": "p1", "quantity": 1}, {"product_id": "p2", "quantity": 1}, {"product_id": "p3", "quantity": 1}])),
        db=database,
        current_user=user,
    )
    transaction = database.query(Transaction).filter_by(id=prediction.transaction_id).one()
    assert transaction.transaction_data["ProductCD"] == "UNKNOWN"
    assert prediction.decision == "REVIEW"
    assert transaction.status == "REVIEW"
    with pytest.raises(HTTPException) as held_order:
        main.create_order(
            main.CreateOrderRequest(
                transaction_id=prediction.transaction_id,
                items=[main.OrderItemRequest(product_id="p1", quantity=1), main.OrderItemRequest(product_id="p2", quantity=1), main.OrderItemRequest(product_id="p3", quantity=1)],
                payment_method="CARD",
                shipping_address={"full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City", "postal_code": "560001", "country": "India"},
                billing_address={"full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City", "postal_code": "560001", "country": "India"},
            ),
            db=database,
            current_user=user,
        )
    assert held_order.value.status_code == 409
    admin = Admin(email="mixed-review-admin@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    database.refresh(admin)
    decision = main.approve_review(
        prediction.transaction_id,
        main.AdminReviewRequest(reason="Reviewed mixed-code basket."),
        db=database,
        current_admin=admin,
    )
    assert decision["status"] == "REVIEW_APPROVED"
    verify_order_code(database, user, prediction.transaction_id, monkeypatch)
    request = main.CreateOrderRequest(
        transaction_id=prediction.transaction_id,
        items=[
            main.OrderItemRequest(product_id="p1", quantity=1),
            main.OrderItemRequest(product_id="p2", quantity=1),
            main.OrderItemRequest(product_id="p3", quantity=1),
        ],
        payment_method="CARD",
        shipping_address={"full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City", "postal_code": "560001", "country": "India"},
        billing_address={"full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City", "postal_code": "560001", "country": "India"},
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
    prediction = run_prediction(database, user, monkeypatch, 0.2, checkout_snapshot=valid_checkout_snapshot(user))
    verify_order_code(database, user, prediction.transaction_id, monkeypatch)
    admin = Admin(email="admin-price-mismatch@example.test", hashed_password=hash_password("admin-test-password"))
    database.add(admin)
    database.commit()
    main.approve_review(prediction.transaction_id, main.AdminReviewRequest(reason="Admin review verified"), db=database, current_admin=admin)
    # Server-persisted checkout items are authoritative if a retry sends stale client details.
    created = main.create_order(order_request(prediction.transaction_id, quantity=2), db=database, current_user=user)
    assert created["items"][0]["quantity"] == 1
    assert database.query(Order).count() == 1


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


def test_existing_customer_login_returns_expected_response_and_accepts_normalized_email(database):
    user = make_user(database, "existing-customer@example.test")

    response = main.login_customer(
        main.LoginRequest(email="  EXISTING-CUSTOMER@EXAMPLE.TEST  ", password="test-only-password"),
        db=database,
    )

    assert response.token_type == "bearer"
    assert response.user.id == user.id
    assert response.user.email == user.email
    assert read_access_token(response.access_token) == user.id


@pytest.mark.parametrize("email,password", [
    ("existing-customer@example.test", "wrong-password"),
    ("missing-customer@example.test", "test-only-password"),
])
def test_customer_login_rejects_invalid_credentials(database, email, password):
    make_user(database, "existing-customer@example.test")

    with pytest.raises(HTTPException) as error:
        main.login_customer(main.LoginRequest(email=email, password=password), db=database)

    assert error.value.status_code == 401
    assert error.value.detail == "Invalid email or password"


def test_registration_response_can_be_used_to_login_without_recreating_account(database):
    registration = main.register_customer(
        main.RegisterRequest(name="New Customer", email="new-customer@example.test", password="new-test-password"),
        db=database,
    )

    login = main.login_customer(
        main.LoginRequest(email="new-customer@example.test", password="new-test-password"),
        db=database,
    )

    assert registration.user.id == login.user.id
    assert registration.user.email == login.user.email
    assert read_access_token(login.access_token) == registration.user.id


def test_admin_login_response_still_uses_admin_token_format(database):
    admin = Admin(email="login-admin@example.test", hashed_password=hash_password("test-admin-password"))
    database.add(admin)
    database.commit()
    database.refresh(admin)

    response = main.login_admin(
        main.LoginRequest(email=admin.email, password="test-admin-password"),
        db=database,
    )

    assert response.admin.id == admin.id
    assert read_admin_access_token(response.access_token) == admin.id



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
    assert {"review_decision", "reviewed_by_admin_id", "reviewed_at", "review_reason", "risk_reassessment"}.issubset(transaction_columns)
    assert "score_based_decision" in {column["name"] for column in inspector.get_columns("fraud_predictions")}
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
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")

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
    assert "authenticated account email" in explanation["feature_provenance"]["P_emaildomain"]
    assert "not independently verified" in explanation["feature_provenance"]["DeviceInfo"]
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


def test_predict_fraud_stores_server_validated_amount_and_features(database, monkeypatch):
    user = make_user(database, "verified.customer@gmail.com")
    verified_email(database, user)
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    monkeypatch.setattr(main, "baseline_pipeline", FixedProbabilityPipeline(0.12))
    monkeypatch.setattr(main, "artifacts_loaded", True)

    snapshot = {
        "verified_email": user.email,
        "items": [
            {"product_id": "p1", "name": "Headphones", "price": 129.0, "quantity": 1}
        ],
        "shipping_address": {"full_name": "Buyer", "line1": "1 Road", "city": "City", "postal_code": "560001", "country": "India", "address_confirmed": True},
        "billing_address": {"full_name": "Buyer", "line1": "1 Road", "city": "City", "postal_code": "560001", "country": "India"},
    }
    # Client sends slightly rounded amount 129.0001, trusted catalog total is 129.0
    request = main.TransactionInput(
        TransactionAmt=129.0001,
        ProductCD="Audio",
        checkout_attempt_id="chk-trusted-amt-test-1",
        checkout_snapshot=snapshot,
    )
    response = main.predict_fraud(request, db=database, current_user=user)

    stored_tx = database.query(Transaction).filter(Transaction.id == response.transaction_id).first()
    assert stored_tx is not None
    assert stored_tx.amount == 129.0
    assert stored_tx.transaction_data["TransactionAmt"] == 129.0
    assert stored_tx.transaction_data["P_emaildomain"] == "gmail.com"
    assert stored_tx.transaction_data["ProductCD"] == "W"
    assert stored_tx.transaction_data["DeviceInfo"] == "UNKNOWN"
    assert stored_tx.transaction_data["DeviceType"] in {"desktop", "mobile", "UNKNOWN"}
    assert response.decision == "REVIEW"
    assert response.score_based_decision == "APPROVE"
    assert "all checkout transactions require mandatory administrator review" in response.review_reason
def test_logistic_regression_uses_trusted_catalog_product_code(database, monkeypatch):
    """The fitted baseline scores the catalog-derived W code using the existing score policy."""
    user = make_user(database, "customer@gmail.com")
    verified_email(database, user)
    admin = Admin(email="auditor@example.test", hashed_password=hash_password("audit-pass-123"), is_active=True)
    database.add(admin)
    database.commit()

    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    assert main.artifacts_loaded is True

    snapshot = {
        "verified_email": user.email,
        "items": [{"product_id": "p1", "quantity": 1}],
        "shipping_address": {"full_name": "Buyer", "line1": "1 Road", "city": "City", "postal_code": "560001", "country": "India", "address_confirmed": True},
        "billing_address": {"full_name": "Buyer", "line1": "1 Road", "city": "City", "postal_code": "560001", "country": "India"},
    }
    request = main.TransactionInput(
        TransactionAmt=129.0,
        ProductCD="S",
        DeviceType="desktop",
        checkout_attempt_id="chk-7381-regression-1",
        checkout_snapshot=snapshot,
    )
    response = main.predict_fraud(request, db=database, current_user=user)

    assert response.fraud_probability == pytest.approx(0.6184, abs=0.0001)
    assert response.risk_level == "MEDIUM"
    assert response.decision == "REVIEW"
    assert response.score_based_decision == "REVIEW"
    assert response.model_used == "LogisticRegression_Baseline"
    stored = database.query(Transaction).filter_by(id=response.transaction_id).one()
    assert stored.transaction_data["ProductCD"] == "W"
    assert stored.status == "REVIEW"

    # 3. Admin explanation verification
    explanation = main.get_admin_transaction_explanation(
        response.transaction_id, db=database, current_admin=admin
    )
    assert explanation["score_reproduced"] is True
    assert explanation["risk_score"] == response.fraud_probability
    assert explanation["risk_category"] == "MEDIUM"
    assert explanation["automated_score_decision"] == "REVIEW"
    assert explanation["model_decision"] == "REVIEW"
    admin_row = next(row for row in main.get_admin_transactions(db=database, current_admin=admin) if row["transaction_id"] == response.transaction_id)
    assert admin_row["fraud_prediction"]["fraud_probability"] == response.fraud_probability
    assert admin_row["fraud_prediction"]["risk_level"] == "MEDIUM"
    assert admin_row["fraud_prediction"]["decision"] == "REVIEW"
    assert explanation["attribution_available"] is True
    assert explanation.get("calibration_notice") is not None
    assert "class_weight='balanced'" in explanation["calibration_notice"]

    # Verify log-odds contributions
    contribs = {item["name"]: item["contribution_log_odds"] for item in explanation["feature_contributions"]}
    assert contribs["ProductCD"] != 0.0
    assert contribs["P_emaildomain"] > 1.2
    assert contribs["DeviceInfo"] > 0.5
    assert contribs["DeviceType"] > 0.1
    assert np.isclose(
        explanation["baseline_log_odds"] + sum(contribs.values()),
        explanation["model_log_odds"],
        atol=1e-5,
    )


def test_logistic_regression_low_score_can_approve_verified_checkout(database, monkeypatch):
    """A low score can approve when the required independent verifications are recorded."""
    user = make_user(database, "test.buyer@yahoo.com")
    verified_email(database, user)
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    monkeypatch.setattr(main, "baseline_pipeline", FixedProbabilityPipeline(0.08))
    monkeypatch.setattr(main, "artifacts_loaded", True)

    snapshot = {
        "verified_email": user.email,
        "items": [
            {"product_id": "p1", "name": "Headphones", "price": 129.0, "quantity": 1}
        ],
        "shipping_address": {"full_name": "Buyer", "line1": "1 Road", "city": "City", "postal_code": "560001", "country": "India", "address_confirmed": True},
        "billing_address": {"full_name": "Buyer", "line1": "1 Road", "city": "City", "postal_code": "560001", "country": "India"},
    }
    request = main.TransactionInput(
        TransactionAmt=129.0,
        ProductCD="Audio",
        checkout_attempt_id="chk-low-score-safeguard-1",
        checkout_snapshot=snapshot,
    )
    response = main.predict_fraud(request, db=database, current_user=user)

    # Raw score would normally classify as LOW / APPROVE
    assert response.fraud_probability == 0.08
    assert response.risk_level == "LOW"
    assert response.decision == "REVIEW"
    assert response.score_based_decision == "APPROVE"
    assert response.review_reason is not None


def test_high_risk_checkout_requires_reassessment_explicit_decision_and_order_otp(database, monkeypatch):
    user = make_user(database, "high-review-path@example.test")
    admin = Admin(email="high-review-admin@example.test", hashed_password=hash_password("admin-password"))
    database.add(admin)
    database.commit()
    database.refresh(admin)
    prediction = run_prediction(
        database, user, monkeypatch, 0.91,
        attempt_id="high-review-path-attempt",
        checkout_snapshot=valid_checkout_snapshot(user),
    )
    transaction = database.query(Transaction).filter(Transaction.id == prediction.transaction_id).one()
    stored_prediction = database.query(FraudPrediction).filter(FraudPrediction.transaction_id == transaction.id).one()
    assert prediction.risk_level == "HIGH"
    assert prediction.score_based_decision == "BLOCK"
    assert prediction.decision == "REVIEW"
    assert transaction.status == "REVIEW"
    assert stored_prediction.score_based_decision == "BLOCK"
    assert transaction.risk_reassessment is None

    with pytest.raises(HTTPException) as direct_order:
        main.create_order(order_request(transaction.id), db=database, current_user=user)
    with pytest.raises(HTTPException) as direct_admin_approval:
        main.approve_review(transaction.id, main.AdminReviewRequest(reason="Try to bypass checks"), db=database, current_admin=admin)
    with pytest.raises(HTTPException) as direct_order_otp:
        main.send_order_verification(
            transaction.id,
            main.OrderVerificationSendRequest(
                shipping_address=main.transaction_shipping_address(transaction),
                address_confirmed=True,
            ),
            db=database,
            current_user=user,
        )
    assert direct_order.value.status_code == 409
    assert direct_admin_approval.value.status_code == 409
    assert direct_order_otp.value.status_code == 409
    assert database.query(Order).count() == 0
    assert transaction.status == "REVIEW"

    reassessment = main.reassess_high_risk_transaction(transaction.id, db=database, current_admin=admin)
    findings = reassessment["risk_reassessment"]
    assert findings["ready_for_admin_decision"] is True
    assert findings["score_based_decision"] == "BLOCK"
    assert findings["operational_decision"] == "REVIEW"
    assert findings["automatic_decision_changed"] is False
    assert findings["address_account_checks"]["address_check"]["format_valid"] is True
    assert findings["graph_relationship_check"]["status"] == "NOT_USED_BY_SCORING_MODEL"
    assert transaction.status == "REVIEW"
    assert transaction.review_decision is None

    with pytest.raises(HTTPException) as missing_reason:
        main.approve_review(transaction.id, main.AdminReviewRequest(), db=database, current_admin=admin)
    assert missing_reason.value.status_code == 422
    assert transaction.status == "REVIEW"

    decision = main.approve_review(
        transaction.id,
        main.AdminReviewRequest(reason="Reviewed score, confirmed address and account history"),
        db=database,
        current_admin=admin,
    )
    assert decision["status"] == "REVIEW_APPROVED"
    assert decision["review_decision"] == "APPROVE"
    assert decision["score_based_decision"] == "BLOCK"
    assert decision["risk_reassessment"]["administrator_decision"]["decision"] == "APPROVE"

    verify_order_code(database, user, transaction.id, monkeypatch)
    created = main.create_order(order_request(transaction.id), db=database, current_user=user)
    retried = main.create_order(order_request(transaction.id), db=database, current_user=user)
    assert created["id"] == retried["id"]
    assert database.query(Order).filter(Order.transaction_id == transaction.id).count() == 1
    assert database.query(OrderVerification).filter(OrderVerification.transaction_id == transaction.id).one().status == "USED"


@pytest.mark.parametrize(("action", "expected_status", "expected_operational"), [
    ("approve", "REVIEW_APPROVED", "ADMIN_APPROVE"),
    ("reject", "REJECTED", "ADMIN_REJECT"),
])
def test_high_risk_customer_status_preserves_score_and_reports_current_admin_decision(
    database, monkeypatch, action, expected_status, expected_operational,
):
    user = make_user(database, f"high-status-{action}@example.test")
    admin = Admin(email=f"high-status-admin-{action}@example.test", hashed_password=hash_password("admin-password"))
    database.add(admin)
    database.commit()
    prediction = run_prediction(
        database, user, monkeypatch, 0.92,
        f"high-status-attempt-{action}", valid_checkout_snapshot(user),
    )
    main.reassess_high_risk_transaction(prediction.transaction_id, db=database, current_admin=admin)
    handler = main.approve_review if action == "approve" else main.reject_review
    reason = f"Reviewed high-risk case and recorded {action} rationale."
    handler(
        prediction.transaction_id,
        main.AdminReviewRequest(reason=reason),
        db=database,
        current_admin=admin,
    )

    status = main.get_transaction_status(prediction.transaction_id, db=database, current_user=user)
    assert status["status"] == expected_status
    assert status["operational_decision"] == expected_operational
    assert status["review_decision"] == action.upper()
    assert status["review_reason"] == reason
    assert status["fraud_prediction"]["decision"] == "REVIEW"
    assert status["fraud_prediction"]["operational_decision"] == expected_operational
    assert status["fraud_prediction"]["score_based_decision"] == "BLOCK"
    assert status["fraud_prediction"]["manual_decision"] == action.upper()
    assert status["fraud_prediction"]["administrator_reason"] == reason
    assert status["fraud_prediction"]["fraud_probability"] == 0.92


def test_address_change_invalidates_high_risk_reassessment(database, monkeypatch):
    user = make_user(database, "stale-address-assessment@example.test")
    admin = Admin(email="stale-address-admin@example.test", hashed_password=hash_password("admin-password"))
    database.add(admin)
    database.commit()
    prediction = run_prediction(
        database, user, monkeypatch, 0.92,
        attempt_id="stale-address-attempt",
        checkout_snapshot=valid_checkout_snapshot(user),
    )
    main.reassess_high_risk_transaction(prediction.transaction_id, db=database, current_admin=admin)

    transaction = database.query(Transaction).filter(Transaction.id == prediction.transaction_id).one()
    transaction.checkout_snapshot["shipping_address"]["line1"] = "2 Changed Road"
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(transaction, "checkout_snapshot")
    database.commit()

    with pytest.raises(HTTPException) as stale_assessment:
        main.approve_review(
            prediction.transaction_id,
            main.AdminReviewRequest(reason="Address changed after reassessment"),
            db=database,
            current_admin=admin,
        )
    assert stale_assessment.value.status_code == 409
    assert transaction.status == "REVIEW"
    assert transaction.review_decision is None


def test_high_risk_graph_assessment_keeps_incomplete_deviceinfo_evidence_visible_and_requires_ack(database, monkeypatch):
    user = make_user(database, "graph-high-review@example.test")
    admin = Admin(email="graph-high-review-admin@example.test", hashed_password=hash_password("admin-password"))
    database.add(admin)
    database.commit()
    snapshot = valid_checkout_snapshot(user)
    prediction = run_graph_prediction(database, user, monkeypatch, 0.88, snapshot)
    incomplete_context = {
        "training_topology": "P_emaildomain, DeviceInfo",
        "live_topology": "P_emaildomain",
        "missing_edge_features": ["DeviceInfo"],
        "connected_neighbors": 2,
        "topology_validation_status": "UNVALIDATED_INSUFFICIENT_DATA",
        "topology_note": "DeviceInfo links are unavailable because live DeviceInfo is UNKNOWN.",
    }
    monkeypatch.setattr(main, "_build_live_gnn_graph", lambda *_args, **_kwargs: (None, incomplete_context))
    findings = main.reassess_high_risk_transaction(prediction.transaction_id, db=database, current_admin=admin)["risk_reassessment"]
    graph = findings["graph_relationship_check"]
    assert graph["status"] == "INCOMPLETE_EVIDENCE"
    assert graph["topology_validation_status"] == "UNVALIDATED_INSUFFICIENT_DATA"
    assert graph["training_edge_features"] == ["P_emaildomain", "DeviceInfo"]
    assert graph["live_edge_features"] == ["P_emaildomain"]
    assert graph["missing_edge_features"] == ["DeviceInfo"]
    assert database.query(Transaction).filter(Transaction.id == prediction.transaction_id).one().status == "REVIEW"

    with pytest.raises(HTTPException) as unacknowledged:
        main.approve_review(
            prediction.transaction_id,
            main.AdminReviewRequest(reason="Inspected available edges"),
            db=database,
            current_admin=admin,
        )
    assert unacknowledged.value.status_code == 422
    approved = main.approve_review(
        prediction.transaction_id,
        main.AdminReviewRequest(
            reason="Manual review accepts remaining DeviceInfo limitation",
            acknowledge_incomplete_graph_evidence=True,
        ),
        db=database,
        current_admin=admin,
    )
    assert approved["risk_reassessment"]["graph_relationship_check"]["status"] == "INCOMPLETE_EVIDENCE"
    assert approved["risk_reassessment"]["administrator_decision"]["acknowledge_incomplete_graph_evidence"] is True


def test_high_risk_reassessment_records_shared_address_and_available_delivery_history(database, monkeypatch):
    user = make_user(database, "address-history-high@example.test")
    admin = Admin(email="address-history-admin@example.test", hashed_password=hash_password("admin-password"))
    database.add(admin)
    database.commit()
    address = {
        "full_name": "Primary Buyer", "line1": "42 Shared Road", "locality": "Central",
        "city": "Sample City", "state": "Karnataka", "postal_code": "560001",
        "country": "India", "address_confirmed": True,
    }
    prediction = run_prediction(
        database, user, monkeypatch, 0.9,
        checkout_snapshot=valid_checkout_snapshot(user, address=address),
    )
    other_user = make_user(database, "new-shared-address@example.test")
    other_snapshot = valid_checkout_snapshot(other_user, address={**address, "full_name": "Different Recipient"})
    other_tx = Transaction(
        user_id=other_user.id,
        checkout_attempt_id="other-address-history-attempt",
        checkout_snapshot=other_snapshot,
        transaction_data={"TransactionAmt": 129.0},
        amount=129.0,
        currency="USD",
        status="ORDERED",
    )
    database.add(other_tx)
    database.flush()
    other_order = Order(
        user_id=other_user.id,
        transaction_id=other_tx.id,
        items=[{"product_id": "p1", "quantity": 1}],
        shipping_address={key: value for key, value in other_snapshot["shipping_address"].items() if key != "address_confirmed"},
        billing_address=other_snapshot["billing_address"],
        amount=129.0,
        currency="USD",
        status="DELIVERY_REFUSED",
        payment_status="SIMULATED",
        payment_method="CARD",
    )
    database.add(other_order)
    database.commit()

    reassessment = main.reassess_high_risk_transaction(prediction.transaction_id, db=database, current_admin=admin)["risk_reassessment"]
    history = reassessment["address_account_checks"]["account_history"]
    assert history["matching_address_orders_last_30_days"] == 1
    assert history["other_accounts_with_matching_checkout_address_last_30_days"] == 1
    assert history["other_new_accounts_with_matching_checkout_address_last_30_days"] == 1
    assert history["recorded_cancellation_or_delivery_failure_status_counts"] == {"DELIVERY_REFUSED": 1}
    assert history["delivery_refusal_history_available"] is True
    assert history["shared_address_is_informational_only"] is True
    assert reassessment["risk_level"] == "HIGH"
    assert reassessment["score_based_decision"] == "BLOCK"
    assert reassessment["automatic_decision_changed"] is False


def test_graphsage_explanation_field_separation_and_topology_limitation(database, monkeypatch):
    """Test GraphSAGE explanation keeps stored score, model name, reproduction, score-based outcome,

    and operational decision as separate fields, hides linear attribution, and displays topology limitation.
    """
    user = make_user(database, "graphsage-explain@example.test")
    admin = Admin(email="admin-gnn@example.test", hashed_password=hash_password("admin-secret"))
    database.add(admin)

    # Simulate TXN-10000031 with GraphSAGE, high score, and unvalidated topology safeguard
    transaction = Transaction(
        user_id=user.id,
        amount=98.0,
        currency="USD",
        status="REVIEW",
        review_reason=(
        "GraphSAGE uses its saved P_emaildomain and DeviceInfo edge schema. Checkout currently "
        "has no trustworthy DeviceInfo source, so graph context may be incomplete and must be reviewed."
        ),
        transaction_data={
            "TransactionAmt": 98.0,
            "ProductCD": "UNKNOWN",
            "P_emaildomain": "gmail.com",
            "DeviceType": "desktop",
            "DeviceInfo": "UNKNOWN",
        },
    )
    database.add(transaction)
    database.commit()
    database.refresh(transaction)

    prediction = FraudPrediction(
        transaction_id=transaction.id,
        fraud_probability=0.8350,
        risk_level="HIGH",
        decision="REVIEW",
        model_used="GraphSAGE",
    )
    database.add(prediction)
    database.commit()

    # Mock reproduce_stored_prediction_score to return reproduction match
    monkeypatch.setattr(
        main,
        "reproduce_stored_prediction_score",
        lambda txn, pred, db: (True, 0.8350, 1, "GraphSAGE causal subgraph reproduction verified match (0.8350 vs 0.8350)"),
    )

    explanation = main.get_admin_transaction_explanation(
        transaction.id, db=database, current_admin=admin
    )

    # 1. Distinct, unconflated fields
    assert explanation["risk_score"] == 0.8350
    assert explanation["model_name"] == "GraphSAGE"
    assert explanation["score_reproduced"] is True
    assert explanation["automated_score_decision"] == "BLOCK"
    assert explanation["model_decision"] == "REVIEW"
    assert explanation["risk_category"] == "HIGH"
    assert explanation["checkout_evidence"]["product_cd"] == "UNKNOWN"
    assert explanation["checkout_evidence"]["product_cd_validated"] is False
    assert explanation["checkout_evidence"]["order_otp_status"] == "NOT_STARTED"
    assert explanation["checkout_evidence"]["device_type"] == "desktop"
    assert explanation["checkout_evidence"]["device_info"] == "UNKNOWN"

    # 2. Linear feature attribution is hidden/inapplicable
    assert explanation["attribution_available"] is False
    assert explanation["feature_contributions"] == []
    assert "baseline_log_odds" not in explanation
    assert "model_log_odds" not in explanation
    assert "Linear feature attribution is mathematically inapplicable" in explanation["attribution_note"]

    # 3. Scientific limitation notice on graph topology mismatch
    assert "graph_context" in explanation
    graph_ctx = explanation["graph_context"]
    assert graph_ctx["edge_type"] == "No connected historical edges"
    assert "DeviceInfo" in graph_ctx["training_topology"]
    assert graph_ctx["topology_validation_status"] == "UNVALIDATED_INSUFFICIENT_DATA"
    assert "DeviceInfo" in graph_ctx["topology_note"]


def test_admin_review_workflow_and_persistence(database):
    """Test admin approval and rejection persist in the database with timestamps and admin ID."""
    user = make_user(database, "review-customer@example.test")
    admin = Admin(email="admin-reviewer@example.test", hashed_password=hash_password("admin-secret"))
    database.add(admin)

    # 1. Test Approval Workflow
    txn_approve = Transaction(
        user_id=user.id,
        amount=150.0,
        currency="USD",
        status="REVIEW",
    )
    database.add(txn_approve)
    database.commit()
    database.refresh(txn_approve)

    pred_approve = FraudPrediction(
        transaction_id=txn_approve.id,
        fraud_probability=0.55,
        risk_level="MEDIUM",
        decision="REVIEW",
        score_based_decision="REVIEW",
        model_used="LogisticRegression_Baseline",
    )
    database.add(pred_approve)
    database.commit()

    approval_res = main.approve_review(
        txn_approve.id,
        request=main.AdminReviewRequest(reason="Customer verified by phone call"),
        db=database,
        current_admin=admin,
    )

    assert approval_res["status"] == "REVIEW_APPROVED"
    assert approval_res["review_decision"] == "APPROVE"
    assert approval_res["reviewed_by_admin_id"] == admin.id
    assert approval_res["reviewed_at"] is not None
    assert approval_res["review_reason"] == "Customer verified by phone call"

    # Verify persistence in database
    db_txn = database.query(Transaction).filter(Transaction.id == txn_approve.id).one()
    assert db_txn.status == "REVIEW_APPROVED"
    assert db_txn.review_decision == "APPROVE"
    assert db_txn.reviewed_by_admin_id == admin.id
    assert db_txn.reviewed_at is not None

    # Cannot review an already reviewed transaction
    with pytest.raises(HTTPException) as exc:
        main.approve_review(
            txn_approve.id,
            request=main.AdminReviewRequest(reason="Duplicate"),
            db=database,
            current_admin=admin,
        )
    assert exc.value.status_code == 409

    # 2. Test Rejection Workflow
    txn_reject = Transaction(
        user_id=user.id,
        amount=500.0,
        currency="USD",
        status="REVIEW",
    )
    database.add(txn_reject)
    database.commit()
    database.refresh(txn_reject)

    pred_reject = FraudPrediction(
        transaction_id=txn_reject.id,
        fraud_probability=0.55,
        risk_level="MEDIUM",
        decision="REVIEW",
        score_based_decision="REVIEW",
        model_used="LogisticRegression_Baseline",
    )
    database.add(pred_reject)
    database.commit()

    reject_res = main.reject_review(
        txn_reject.id,
        request=main.AdminReviewRequest(reason="Mismatched billing identity"),
        db=database,
        current_admin=admin,
    )

    assert reject_res["status"] == "REJECTED"
    assert reject_res["review_decision"] == "REJECT"
    assert reject_res["reviewed_by_admin_id"] == admin.id
    assert reject_res["reviewed_at"] is not None

    db_reject = database.query(Transaction).filter(Transaction.id == txn_reject.id).one()
    assert db_reject.status == "REJECTED"
    assert db_reject.review_decision == "REJECT"


def test_customer_review_status_reflection_and_unauthorized_isolation(database):
    """Test customer status polling reflects admin decision and blocks access by other users."""
    user = make_user(database, "status-user@example.test")
    other_user = make_user(database, "eavesdropper@example.test")
    admin = Admin(email="admin-sec@example.test", hashed_password=hash_password("admin-secret"))
    database.add(admin)

    txn = Transaction(
        user_id=user.id,
        amount=120.0,
        currency="USD",
        status="REVIEW",
    )
    database.add(txn)
    database.commit()
    database.refresh(txn)

    pred = FraudPrediction(
        transaction_id=txn.id,
        fraud_probability=0.50,
        risk_level="MEDIUM",
        decision="REVIEW",
        score_based_decision="REVIEW",
        model_used="LogisticRegression_Baseline",
    )
    database.add(pred)
    database.commit()

    # Before admin review: status is REVIEW
    status_before = main.get_transaction_status(txn.id, db=database, current_user=user)
    assert status_before["status"] == "REVIEW"
    assert status_before["review_decision"] is None

    # Admin approves review
    main.approve_review(
        txn.id,
        request=main.AdminReviewRequest(reason="Approved by admin"),
        db=database,
        current_admin=admin,
    )

    # Customer polls status: reflected immediately
    status_after = main.get_transaction_status(txn.id, db=database, current_user=user)
    assert status_after["status"] == "REVIEW_APPROVED"
    assert status_after["review_decision"] == "APPROVE"

    # Another user cannot inspect this transaction
    with pytest.raises(HTTPException) as exc:
        main.get_transaction_status(txn.id, db=database, current_user=other_user)
    assert exc.value.status_code == 404


def test_customer_cannot_bypass_pending_review_to_place_order(database, monkeypatch):
    """Verify that a customer cannot bypass a pending review by directly calling create_order."""
    user = make_user(database, "bypass-test@example.test")
    verified_email(database, user)
    admin = Admin(email="admin-bypass@example.test", hashed_password=hash_password("admin-secret"))
    database.add(admin)

    snapshot = {
        "verified_email": user.email,
        "items": [
            {"product_id": "p1", "name": "Watch", "price": 129.0, "quantity": 1}
        ],
        "shipping_address": {"full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City", "postal_code": "560001", "country": "India", "address_confirmed": True},
        "billing_address": {"full_name": "Test Buyer", "line1": "1 Example Road", "city": "Example City", "postal_code": "560001", "country": "India"},
        "payment_method": "CARD",
    }
    txn = Transaction(
        user_id=user.id,
        amount=129.0,
        currency="USD",
        status="REVIEW",
        checkout_snapshot=snapshot,
    )
    database.add(txn)
    database.commit()
    database.refresh(txn)

    pred = FraudPrediction(
        transaction_id=txn.id,
        fraud_probability=0.8350,
        risk_level="HIGH",
        decision="REVIEW",
        score_based_decision="BLOCK",
        model_used="LogisticRegression_Baseline",
    )
    database.add(pred)
    database.commit()

    order_req = order_request(txn.id, product_id="p1", quantity=1)

    # Attempt to bypass review and place order while in REVIEW -> MUST BE REJECTED WITH 409
    with pytest.raises(HTTPException) as exc:
        main.create_order(order_req, db=database, current_user=user)
    assert exc.value.status_code == 409
    assert "not approved for payment" in exc.value.detail.lower()

    # Now admin approves the review
    main.reassess_high_risk_transaction(txn.id, db=database, current_admin=admin)
    main.approve_review(
        txn.id,
        request=main.AdminReviewRequest(reason="Admin approved"),
        db=database,
        current_admin=admin,
    )

    # After approval, create_order succeeds
    verify_order_code(database, user, txn.id, monkeypatch)
    order = main.create_order(order_req, db=database, current_user=user)
    assert order["status"] == "PROCESSING"
    assert order["transaction_id"] == txn.id
    assert order["amount"] == 129.0
