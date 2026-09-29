from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
import joblib
import pandas as pd
import os
import sys
from sqlalchemy.orm import Session

# Ensure backend directory is in sys.path if not running module properly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ml.preprocessing import select_features_and_preprocess
from app.database.session import engine, Base, get_db
from app.models.fraud_prediction import FraudPrediction
from app.models.transaction import Transaction
from app.models.user import User

# Create tables
Base.metadata.create_all(bind=engine)

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Autonomous Fraud Detection API",
    description="Backend API for e-commerce fraud detection",
    version="1.0.0"
)

# Enable CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, restrict this to the frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants for Features
NUMERICAL_COLS = ['TransactionAmt', 'dist1', 'dist2', 'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8', 'C9', 'C10', 'C11', 'C12', 'C13', 'C14']
CATEGORICAL_COLS = ['ProductCD', 'card1', 'card2', 'card3', 'card4', 'card5', 'card6', 'addr1', 'addr2', 'P_emaildomain', 'R_emaildomain', 'DeviceType', 'DeviceInfo']

# Load artifacts at startup
try:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    MODELS_DIR = os.path.join(BASE_DIR, "models")
    clf_model = joblib.load(os.path.join(MODELS_DIR, "logistic_regression.pkl"))
    scalers = joblib.load(os.path.join(MODELS_DIR, "scalers.pkl"))
    encoders = joblib.load(os.path.join(MODELS_DIR, "encoders.pkl"))
    artifacts_loaded = True
except Exception as e:
    print(f"Warning: Failed to load model artifacts. {e}")
    artifacts_loaded = False

class TransactionInput(BaseModel):
    TransactionID: int
    TransactionAmt: float
    dist1: Optional[float] = None
    dist2: Optional[float] = None
    C1: Optional[float] = None
    C2: Optional[float] = None
    C3: Optional[float] = None
    C4: Optional[float] = None
    C5: Optional[float] = None
    C6: Optional[float] = None
    C7: Optional[float] = None
    C8: Optional[float] = None
    C9: Optional[float] = None
    C10: Optional[float] = None
    C11: Optional[float] = None
    C12: Optional[float] = None
    C13: Optional[float] = None
    C14: Optional[float] = None
    ProductCD: Optional[str] = None
    card1: Optional[float] = None
    card2: Optional[float] = None
    card3: Optional[float] = None
    card4: Optional[str] = None
    card5: Optional[float] = None
    card6: Optional[str] = None
    addr1: Optional[float] = None
    addr2: Optional[float] = None
    P_emaildomain: Optional[str] = None
    R_emaildomain: Optional[str] = None
    DeviceType: Optional[str] = None
    DeviceInfo: Optional[str] = None

class PredictionResponse(BaseModel):
    fraud_probability: float
    risk_level: str
    decision: str
    model_used: str

@app.get("/")
def read_root():
    return {"message": "Fraud Detection Backend is running"}

@app.post("/api/fraud/predict", response_model=PredictionResponse)
def predict_fraud(transaction: TransactionInput, db: Session = Depends(get_db)):
    if not artifacts_loaded:
        raise HTTPException(status_code=500, detail="Model artifacts are not loaded.")
        
    try:
        # Convert to DataFrame
        df = pd.DataFrame([transaction.dict()])
        
        # Preprocess
        df_proc, _, _ = select_features_and_preprocess(
            df, 
            NUMERICAL_COLS, 
            CATEGORICAL_COLS, 
            is_train=False, 
            scalers=scalers, 
            encoders=encoders
        )
        
        # Predict using Logistic Regression Baseline
        features = NUMERICAL_COLS + CATEGORICAL_COLS
        X = df_proc[features].values
        
        # fraud probability is the probability of class 1
        fraud_prob = float(clf_model.predict_proba(X)[0, 1])
        
        # Determine risk level and decision
        if fraud_prob <= 0.30:
            risk_level = "LOW"
            decision = "APPROVE"
        elif fraud_prob <= 0.70:
            risk_level = "MEDIUM"
            decision = "REVIEW"
        else:
            risk_level = "HIGH"
            decision = "BLOCK"
            
        # Store in database
        db_tx = db.query(Transaction).filter(Transaction.id == transaction.TransactionID).first()
        if not db_tx:
            db_tx = Transaction(
                id=transaction.TransactionID,
                amount=transaction.TransactionAmt,
                transaction_data=transaction.dict()
            )
            db.add(db_tx)
            db.commit()
            
        db_pred = FraudPrediction(
            transaction_id=transaction.TransactionID,
            fraud_probability=round(fraud_prob, 4),
            risk_level=risk_level,
            decision=decision,
            model_used="LogisticRegression_Baseline"
        )
        db.add(db_pred)
        db.commit()
            
        return PredictionResponse(
            fraud_probability=round(fraud_prob, 4),
            risk_level=risk_level,
            decision=decision,
            model_used="LogisticRegression_Baseline"
        )
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Prediction error: {str(e)}")

@app.get("/api/admin/fraud/recent")
def get_recent_predictions(limit: int = 10, db: Session = Depends(get_db)):
    from sqlalchemy.orm import joinedload
    preds = db.query(FraudPrediction).options(joinedload(FraudPrediction.transaction)).order_by(FraudPrediction.created_at.desc()).limit(limit).all()
    
    results = []
    for pred in preds:
        results.append({
            "id": pred.id,
            "transaction_id": pred.transaction_id,
            "fraud_probability": pred.fraud_probability,
            "risk_level": pred.risk_level,
            "decision": pred.decision,
            "model_used": pred.model_used,
            "created_at": pred.created_at,
            "amount": pred.transaction.amount if pred.transaction else 0.0
        })
    return results

@app.get("/api/admin/fraud/summary")
def get_fraud_summary(db: Session = Depends(get_db)):
    total = db.query(FraudPrediction).count()
    low = db.query(FraudPrediction).filter(FraudPrediction.risk_level == 'LOW').count()
    medium = db.query(FraudPrediction).filter(FraudPrediction.risk_level == 'MEDIUM').count()
    high = db.query(FraudPrediction).filter(FraudPrediction.risk_level == 'HIGH').count()
    
    return {
        "total_predictions": total,
        "risk_breakdown": {
            "LOW": low,
            "MEDIUM": medium,
            "HIGH": high
        }
    }
