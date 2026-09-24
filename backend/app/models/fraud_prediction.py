from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
import datetime
from app.database.session import Base

class FraudPrediction(Base):
    __tablename__ = "fraud_predictions"

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id"))
    
    fraud_probability = Column(Float)
    risk_level = Column(String) # LOW, MEDIUM, HIGH
    decision = Column(String)   # APPROVE, REVIEW, BLOCK
    model_used = Column(String)
    
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    transaction = relationship("Transaction", back_populates="prediction")
