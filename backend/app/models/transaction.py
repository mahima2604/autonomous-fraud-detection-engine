from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
import datetime
from app.database.session import Base

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Store the transaction fields as JSON to keep it flexible and avoid mapping 394 columns
    transaction_data = Column(JSON) 
    
    amount = Column(Float)
    currency = Column(String, default="USD")
    status = Column(String, default="PENDING")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    user = relationship("User", back_populates="transactions")
    prediction = relationship("FraudPrediction", back_populates="transaction", uselist=False)
