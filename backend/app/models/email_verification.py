from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.database.session import Base


class EmailVerification(Base):
    """Current email OTP challenge and verified state for one customer."""

    __tablename__ = "email_verifications"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    email_address = Column(String(320), nullable=False, index=True)
    code_hash = Column(String(64), nullable=True)
    status = Column(String(16), nullable=False, default="PENDING")
    created_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    resend_after = Column(DateTime, nullable=False)
    window_started_at = Column(DateTime, nullable=False)
    sends_in_window = Column(Integer, nullable=False, default=1)
    attempts = Column(Integer, nullable=False, default=0)
    verified_at = Column(DateTime, nullable=True)
