from sqlalchemy import Column, Index, Integer, String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
import datetime
from app.database.session import Base

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    checkout_attempt_id = Column(String(64), nullable=True)
    
    # Store the transaction fields as JSON to keep it flexible and avoid mapping 394 columns
    transaction_data = Column(JSON) 
    
    amount = Column(Float)
    currency = Column(String, default="USD")
    status = Column(String, default="PENDING")
    # Review metadata is separate from FraudPrediction so the model's original
    # score and decision remain immutable after an administrator acts.
    review_decision = Column(String, nullable=True)  # APPROVE or REJECT
    reviewed_by_admin_id = Column(Integer, ForeignKey("admins.id"), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)
    review_reason = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="transactions")
    prediction = relationship("FraudPrediction", back_populates="transaction", uselist=False)

Index("uq_transactions_checkout_attempt_id", Transaction.checkout_attempt_id, unique=True)
