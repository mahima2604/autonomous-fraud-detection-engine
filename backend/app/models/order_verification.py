import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String

from app.database.session import Base


class OrderVerification(Base):
    """Single-use email challenge and address confirmation for one assessed order attempt."""

    __tablename__ = "order_verifications"

    transaction_id = Column(Integer, ForeignKey("transactions.id"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    checkout_attempt_id = Column(String(64), nullable=False, unique=True)
    email_address = Column(String(320), nullable=False)
    code_hash = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False, default="ADDRESS_CONFIRMED")
    shipping_address_hash = Column(String(64), nullable=False)
    address_confirmed_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    resend_after = Column(DateTime, nullable=False)
    attempts = Column(Integer, nullable=False, default=0)
    sends_in_window = Column(Integer, nullable=False, default=0)
    window_started_at = Column(DateTime, nullable=False)
    verified_at = Column(DateTime, nullable=True)
    used_at = Column(DateTime, nullable=True)


Index("uq_order_verifications_attempt_id", OrderVerification.checkout_attempt_id, unique=True)
