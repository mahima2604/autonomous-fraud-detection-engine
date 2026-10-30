import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("AUTH_TOKEN_SECRET", "test-only-signing-key-for-checkout-tests")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main
from app.database.session import Base
from app.models.email_verification import EmailVerification
from app.models.transaction import Transaction
from app.models.user import User
from app.services import email_otp


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'otp.sqlite'}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def customer(db, email):
    user = User(email=email, hashed_password="test")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_send_verify_invalid_expired_cooldown_attempts_and_user_isolation(database, monkeypatch):
    user = customer(database, "otp-one@example.test")
    other = customer(database, "otp-two@example.test")
    sent = []
    monkeypatch.setattr(main.email_otp, "send_code", lambda email, code: sent.append((email, code)) or True)

    sent_response = main.send_email_verification(database, user)
    assert sent_response["status"] == "pending"
    assert "code" not in sent_response
    assert "otp" not in sent_response
    assert sent[0][0] == user.email
    assert len(sent[0][1]) == 6
    invalid_code = "000000" if sent[0][1] != "000000" else "000001"
    with pytest.raises(HTTPException) as cooldown:
        main.send_email_verification(database, user)
    assert cooldown.value.status_code == 429

    with pytest.raises(HTTPException) as invalid:
        main.verify_email_address(main.VerifyEmailRequest(code=invalid_code), database, user)
    assert invalid.value.status_code == 400
    with pytest.raises(HTTPException) as other_user:
        main.verify_email_address(main.VerifyEmailRequest(code="654321"), database, other)
    assert other_user.value.status_code == 409

    record = database.query(EmailVerification).filter_by(user_id=user.id).one()
    record.resend_after = datetime.utcnow() - timedelta(seconds=1)
    database.commit()
    verified = main.verify_email_address(main.VerifyEmailRequest(code=sent[0][1]), database, user)
    assert verified["status"] == "verified"
    assert record.code_hash is None
    with pytest.raises(HTTPException) as reused:
        main.verify_email_address(main.VerifyEmailRequest(code=sent[0][1]), database, user)
    assert reused.value.status_code == 409
    assert main.email_verification_status(database, user)["verified"] is True
    assert main.email_verification_status(database, other)["verified"] is False

    record.resend_after = datetime.utcnow() - timedelta(seconds=1)
    database.commit()
    user.email = "otp-one-updated@example.test"
    database.commit()
    assert main.email_verification_status(database, user)["verified"] is False
    main.send_email_verification(database, user)

    # A new challenge can only follow the cooldown; five bad codes lock the pending challenge.
    record.resend_after = datetime.utcnow() - timedelta(seconds=1)
    record.sends_in_window = main.OTP_MAX_SENDS
    database.commit()
    with pytest.raises(HTTPException) as send_limit:
        main.send_email_verification(database, user)
    assert send_limit.value.status_code == 429

    record.status = "PENDING"
    record.verified_at = None
    record.expires_at = datetime.utcnow() + timedelta(minutes=10)
    record.attempts = main.OTP_MAX_ATTEMPTS
    database.commit()
    invalid_updated_code = "000000" if sent[-1][1] != "000000" else "000001"
    with pytest.raises(HTTPException) as limited:
        main.verify_email_address(main.VerifyEmailRequest(code=invalid_updated_code), database, user)
    assert limited.value.status_code == 429

    record.attempts = 0
    record.expires_at = datetime.utcnow() - timedelta(seconds=1)
    database.commit()
    with pytest.raises(HTTPException) as expired:
        main.verify_email_address(main.VerifyEmailRequest(code="654321"), database, user)
    assert expired.value.status_code == 410


def test_unverified_email_blocks_fraud_checkout_and_direct_order_submission(database, monkeypatch):
    user = customer(database, "otp-order@example.test")
    monkeypatch.setattr(main, "PRIMARY_FRAUD_MODEL", "logistic_regression")
    monkeypatch.setattr(main, "artifacts_loaded", True)
    with pytest.raises(HTTPException) as prediction_blocked:
        main.predict_fraud(
            main.TransactionInput(TransactionAmt=129, checkout_snapshot={"items": [{"product_id": "p1", "quantity": 1}]}),
            database, user,
        )
    assert prediction_blocked.value.status_code == 403

    txn = Transaction(user_id=user.id, amount=1, currency="USD", status="APPROVED", checkout_snapshot={"verified_email": user.email})
    database.add(txn)
    database.commit()
    request = main.CreateOrderRequest(
        transaction_id=txn.id, items=[{"product_id": "p1", "quantity": 1}], payment_method="CARD",
        shipping_address={"full_name": "A", "line1": "B", "city": "C", "postal_code": "D", "country": "E"},
        billing_address={"full_name": "A", "line1": "B", "city": "C", "postal_code": "D", "country": "E"},
    )
    with pytest.raises(HTTPException) as blocked:
        main.create_order(request, database, user)
    assert blocked.value.status_code == 403


def test_smtp_delivery_failure_is_not_reported_as_sent(database, monkeypatch):
    user = customer(database, "otp-delivery@example.test")

    def fail_delivery(_email, _code):
        raise email_otp.DeliveryError("mail server unavailable")

    monkeypatch.setattr(main.email_otp, "send_code", fail_delivery)
    with pytest.raises(HTTPException) as error:
        main.send_email_verification(database, user)
    assert error.value.status_code == 503
    record = database.query(EmailVerification).one()
    assert record.status == "FAILED"
    assert record.code_hash is None


def test_missing_smtp_configuration_never_reports_sent_or_verified(database, monkeypatch):
    user = customer(database, "otp-provider@example.test")
    for name in ("SMTP_HOST", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(HTTPException) as error:
        main.send_email_verification(database, user)
    assert error.value.status_code == 503
    record = database.query(EmailVerification).one()
    assert record.status == "FAILED"
    assert record.code_hash is None


def test_smtp_adapter_sends_code_with_tls_and_reports_delivery(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USERNAME", "sender@example.test")
    monkeypatch.setenv("SMTP_PASSWORD", "test-app-password")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "sender@example.test")
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            assert (host, port, timeout) == ("smtp.gmail.com", 587, 12)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def ehlo(self):
            return None

        def starttls(self, context):
            assert context

        def login(self, username, password):
            assert username == "sender@example.test"
            assert password == "test-app-password"

        def send_message(self, message):
            sent.append(message)
            return {}

    monkeypatch.setattr(email_otp.smtplib, "SMTP", FakeSMTP)
    assert email_otp.send_code("customer@example.test", "482019") is True
    assert sent[0]["To"] == "customer@example.test"
    assert "482019" in sent[0].get_content()
