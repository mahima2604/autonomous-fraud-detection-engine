from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field, validator
from typing import Optional
import joblib
import pandas as pd
import os
import sys
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text, func

# Ensure backend directory is in sys.path if not running module properly 
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ml.preprocessing import select_features_and_preprocess
from app.database.session import engine, Base, get_db, SessionLocal
from app.models.fraud_prediction import FraudPrediction
from app.models.transaction import Transaction
from app.models.user import User
from app.models.admin import Admin
from app.services.auth import (
    create_access_token, create_admin_access_token, get_current_admin, get_current_user,
    hash_password, verify_password,
)

# Create tables and add the customer name column to existing databases without recreating data.
Base.metadata.create_all(bind=engine)
if "name" not in {column["name"] for column in inspect(engine).get_columns("users")}:
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE users ADD COLUMN name VARCHAR"))


def ensure_demo_admin():
    email = os.getenv("ADMIN_EMAIL", "admin@securecart.com").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "Admin@123")
    db = SessionLocal()
    try:
        admin = db.query(Admin).filter(Admin.email == email).first()
        if admin is None:
            db.add(Admin(email=email, hashed_password=hash_password(password)))
            db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


ensure_demo_admin()

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
    baseline_pipeline = joblib.load(os.path.join(MODELS_DIR, "baseline_pipeline.pkl"))
    scalers = joblib.load(os.path.join(MODELS_DIR, "scalers.pkl"))
    encoders = joblib.load(os.path.join(MODELS_DIR, "encoders.pkl"))
    artifacts_loaded = True
except Exception as e:
    print(f"Warning: Failed to load model artifacts. {e}")
    artifacts_loaded = False

class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str
    password: str = Field(..., min_length=6, max_length=256)

    @validator("name")
    def normalize_name(cls, value):
        normalized = value.strip()
        if not normalized:
            raise ValueError("Name is required")
        return normalized

    @validator("email")
    def normalize_email(cls, value):
        normalized = value.strip().lower()
        if len(normalized) > 320 or "@" not in normalized:
            raise ValueError("Enter a valid email address")
        local, domain = normalized.rsplit("@", 1)
        if not local or "." not in domain or domain.startswith(".") or domain.endswith("."):
            raise ValueError("Enter a valid email address")
        return normalized

class LoginRequest(BaseModel):
    email: str
    password: str = Field(..., min_length=1, max_length=256)

    @validator("email")
    def normalize_email(cls, value):
        normalized = value.strip().lower()
        if len(normalized) > 320 or "@" not in normalized:
            raise ValueError("Enter a valid email address")
        return normalized

class UserResponse(BaseModel):
    id: int
    name: str
    email: str

class AdminResponse(BaseModel):
    id: int
    email: str
    is_active: bool

class AdminAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin: AdminResponse

class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class TransactionInput(BaseModel):
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
    transaction_id: int
    fraud_probability: float
    risk_level: str
    decision: str
    model_used: str

@app.get("/")
def read_root():
    return {"message": "Fraud Detection Backend is running"}

@app.post("/api/auth/register", response_model=AuthResponse, status_code=201)
def register_customer(request: RegisterRequest, db: Session = Depends(get_db)):
    email = request.email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(name=request.name.strip(), email=email, hashed_password=hash_password(request.password))
    db.add(user)
    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    return AuthResponse(access_token=create_access_token(user.id), user=UserResponse(id=user.id, name=user.name or "", email=user.email))

@app.post("/api/auth/login", response_model=AuthResponse)
def login_customer(request: LoginRequest, db: Session = Depends(get_db)):
    email = request.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None or not verify_password(request.password, user.hashed_password or ""):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="This account is inactive")
    return AuthResponse(access_token=create_access_token(user.id), user=UserResponse(id=user.id, name=user.name or "", email=user.email))

@app.post("/api/admin/auth/login", response_model=AdminAuthResponse)
def login_admin(request: LoginRequest, db: Session = Depends(get_db)):
    email = request.email.strip().lower()
    admin = db.query(Admin).filter(Admin.email == email).first()
    if admin is None or not verify_password(request.password, admin.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not admin.is_active:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return AdminAuthResponse(
        access_token=create_admin_access_token(admin.id),
        admin=AdminResponse(id=admin.id, email=admin.email, is_active=admin.is_active),
    )

@app.post("/api/fraud/predict", response_model=PredictionResponse)
def predict_fraud(transaction: TransactionInput, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if not artifacts_loaded:
        raise HTTPException(status_code=500, detail="Model artifacts are not loaded.")
        
    try:
        # Convert to DataFrame
        transaction_data = transaction.dict(exclude={"TransactionID"})
        df = pd.DataFrame([transaction_data])
        
        # Preprocess
        df_proc, _, _ = select_features_and_preprocess(
            df, 
            NUMERICAL_COLS, 
            CATEGORICAL_COLS, 
            is_train=False, 
            scalers=scalers, 
            encoders=encoders
        )
        
        # Predict using Logistic Regression Baseline (Pipeline handles preprocessing internally)
        fraud_prob = float(baseline_pipeline.predict_proba(df)[0, 1])
        
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
        db_tx = Transaction(
            user_id=current_user.id,
            amount=transaction.TransactionAmt,
            transaction_data=transaction_data
        )
        db.add(db_tx)
        db.flush()
            
        db_pred = FraudPrediction(
            transaction_id=db_tx.id,
            fraud_probability=round(fraud_prob, 4),
            risk_level=risk_level,
            decision=decision,
            model_used="LogisticRegression_Baseline"
        )
        db.add(db_pred)
        db.commit()
            
        return PredictionResponse(
            transaction_id=db_tx.id,
            fraud_probability=round(fraud_prob, 4),
            risk_level=risk_level,
            decision=decision,
            model_used="LogisticRegression_Baseline"
        )
        
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Prediction error: {str(e)}")

@app.get("/api/admin/fraud/recent")
def get_recent_predictions(limit: int = 10, db: Session = Depends(get_db), current_admin: Admin = Depends(get_current_admin)):
    from sqlalchemy.orm import aliased

    ranked_predictions = (
        db.query(
            FraudPrediction.id.label("id"),
            FraudPrediction.transaction_id.label("transaction_id"),
            FraudPrediction.fraud_probability.label("fraud_probability"),
            FraudPrediction.risk_level.label("risk_level"),
            FraudPrediction.decision.label("decision"),
            FraudPrediction.model_used.label("model_used"),
            FraudPrediction.created_at.label("created_at"),
            func.row_number().over(
                partition_by=FraudPrediction.transaction_id,
                order_by=(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()),
            ).label("row_number"),
        )
        .subquery()
    )
    LatestPrediction = aliased(FraudPrediction, ranked_predictions)
    rows = (
        db.query(LatestPrediction, Transaction)
        .join(Transaction, LatestPrediction.transaction_id == Transaction.id)
        .filter(ranked_predictions.c.row_number == 1)
        .order_by(LatestPrediction.created_at.desc(), LatestPrediction.id.desc())
        .limit(limit)
        .all()
    )
    
    results = []
    for pred, transaction in rows:
        results.append({
            "id": pred.id,
            "transaction_id": pred.transaction_id,
            "fraud_probability": pred.fraud_probability,
            "risk_level": pred.risk_level,
            "decision": pred.decision,
            "model_used": pred.model_used,
            "created_at": pred.created_at,
            "amount": transaction.amount
        })
    return results

@app.get("/api/admin/fraud/summary")
def get_fraud_summary(db: Session = Depends(get_db), current_admin: Admin = Depends(get_current_admin)):
    ranked_predictions = (
        db.query(
            FraudPrediction.id.label("id"),
            FraudPrediction.transaction_id.label("transaction_id"),
            FraudPrediction.risk_level.label("risk_level"),
            func.row_number().over(
                partition_by=FraudPrediction.transaction_id,
                order_by=(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()),
            ).label("row_number"),
        )
        .subquery()
    )
    latest_predictions = db.query(ranked_predictions).filter(ranked_predictions.c.row_number == 1).subquery()
    counts = dict(
        db.query(latest_predictions.c.risk_level, func.count(latest_predictions.c.id))
        .group_by(latest_predictions.c.risk_level)
        .all()
    )
    total = sum(counts.values())
    
    return {
        "total_predictions": total,
        "risk_breakdown": {
            "LOW": counts.get("LOW", 0),
            "MEDIUM": counts.get("MEDIUM", 0),
            "HIGH": counts.get("HIGH", 0)
        }
    }


@app.get("/api/admin/transactions")
def get_admin_transactions(db: Session = Depends(get_db), current_admin: Admin = Depends(get_current_admin)):
    from sqlalchemy.orm import aliased

    # Rank predictions explicitly because the database permits multiple rows
    # per transaction while the ORM relationship is configured as one-to-one.
    ranked_predictions = (
        db.query(
            FraudPrediction.id.label("id"),
            FraudPrediction.transaction_id.label("transaction_id"),
            FraudPrediction.fraud_probability.label("fraud_probability"),
            FraudPrediction.risk_level.label("risk_level"),
            FraudPrediction.decision.label("decision"),
            FraudPrediction.model_used.label("model_used"),
            FraudPrediction.created_at.label("created_at"),
            func.row_number().over(
                partition_by=FraudPrediction.transaction_id,
                order_by=(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()),
            ).label("row_number"),
        )
        .subquery()
    )

    LatestPrediction = aliased(FraudPrediction, ranked_predictions)
    rows = (
        db.query(Transaction, User, LatestPrediction)
        .outerjoin(User, Transaction.user_id == User.id)
        .outerjoin(
            ranked_predictions,
            (LatestPrediction.transaction_id == Transaction.id)
            & (ranked_predictions.c.row_number == 1),
        )
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .all()
    )

    return [
        {
            "transaction_id": transaction.id,
            "amount": transaction.amount,
            "currency": transaction.currency,
            "status": transaction.status,
            "created_at": transaction.created_at,
            "customer": (
                {"user_id": customer.id, "name": customer.name, "email": customer.email}
                if customer is not None else None
            ),
            "fraud_prediction": (
                {
                    "fraud_probability": prediction.fraud_probability,
                    "risk_level": prediction.risk_level,
                    "decision": prediction.decision,
                    "model_used": prediction.model_used,
                    "prediction_created_at": prediction.created_at,
                }
                if prediction.id is not None else None
            ),
        }
        for transaction, customer, prediction in rows
    ]


@app.get("/api/admin/customers")
def get_admin_customers(db: Session = Depends(get_db), current_admin: Admin = Depends(get_current_admin)):
    customers = db.query(User).order_by(User.created_at.desc(), User.id.desc()).all()
    return [
        {
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "is_active": customer.is_active,
            "created_at": customer.created_at,
        }
        for customer in customers
    ]


@app.get("/api/admin/customers/{customer_id}")
def get_admin_customer_details(
    customer_id: int,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    from fastapi import HTTPException

    customer = db.query(User).filter(User.id == customer_id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    from sqlalchemy.orm import aliased

    ranked_predictions = (
        db.query(
            FraudPrediction.id.label("id"),
            FraudPrediction.transaction_id.label("transaction_id"),
            FraudPrediction.fraud_probability.label("fraud_probability"),
            FraudPrediction.risk_level.label("risk_level"),
            FraudPrediction.decision.label("decision"),
            FraudPrediction.model_used.label("model_used"),
            FraudPrediction.created_at.label("created_at"),
            func.row_number().over(
                partition_by=FraudPrediction.transaction_id,
                order_by=(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()),
            ).label("row_number"),
        )
        .subquery()
    )
    LatestPrediction = aliased(FraudPrediction, ranked_predictions)
    transactions = (
        db.query(Transaction, LatestPrediction)
        .outerjoin(
            ranked_predictions,
            (LatestPrediction.transaction_id == Transaction.id)
            & (ranked_predictions.c.row_number == 1),
        )
        .filter(Transaction.user_id == customer.id)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .all()
    )
    return {
        "customer": {
            "id": customer.id,
            "name": customer.name,
            "email": customer.email,
            "is_active": customer.is_active,
            "created_at": customer.created_at,
        },
        "transactions": [
            {
                "transaction_id": transaction.id,
                "amount": transaction.amount,
                "status": transaction.status,
                "created_at": transaction.created_at,
                "fraud_prediction": (
                    {
                        "fraud_probability": prediction.fraud_probability,
                        "risk_level": prediction.risk_level,
                        "decision": prediction.decision,
                        "model_used": prediction.model_used,
                        "created_at": prediction.created_at,
                    }
                    if prediction is not None and prediction.id is not None
                    else None
                ),
            }
            for transaction, prediction in transactions
        ],
    }
