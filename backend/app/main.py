from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel, Field, validator
from typing import List, Optional
import joblib
import logging
from contextlib import asynccontextmanager
import math
import os
import pandas as pd
import sys
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text, func

# Ensure backend directory is in sys.path if not running module properly 
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.session import engine, Base, get_db
from app.models.fraud_prediction import FraudPrediction
from app.models.transaction import Transaction
from app.models.user import User
from app.models.admin import Admin
from app.models.order import Order
from app.catalog import SAMPLE_CATALOG, get_product
from app.services.auth import (
    create_access_token, create_admin_access_token, get_current_admin, get_current_user,
    hash_password, verify_password,
)

logger = logging.getLogger(__name__)

def initialize_database():
    """Create missing tables and apply the existing additive schema migrations."""
    Base.metadata.create_all(bind=engine)
    if "name" not in {column["name"] for column in inspect(engine).get_columns("users")}:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN name VARCHAR"))
    transaction_columns = {column["name"] for column in inspect(engine).get_columns("transactions")}
    if "checkout_attempt_id" not in transaction_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE transactions ADD COLUMN checkout_attempt_id VARCHAR(64)"))
    review_columns = {
        "review_decision": "VARCHAR",
        "reviewed_by_admin_id": "INTEGER REFERENCES admins(id)",
        "reviewed_at": "DATETIME",
        "review_reason": "VARCHAR",
    }
    for column_name, column_type in review_columns.items():
        if column_name not in transaction_columns:
            with engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE transactions ADD COLUMN {column_name} {column_type}"))
    with engine.begin() as connection:
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_checkout_attempt_id ON transactions (checkout_attempt_id)"))


from app.admin_provisioning import bootstrap_demo_admin
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(_app):
    initialize_database()
    bootstrap_demo_admin()
    yield

app = FastAPI(
    title="Autonomous Fraud Detection API",
    description="Backend API for e-commerce fraud detection",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable CORS for the frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRAUD_REVIEW_THRESHOLD = float(os.getenv("FRAUD_REVIEW_THRESHOLD", "0.30"))
FRAUD_BLOCK_THRESHOLD = float(os.getenv("FRAUD_BLOCK_THRESHOLD", "0.70"))
if not (0 < FRAUD_REVIEW_THRESHOLD < FRAUD_BLOCK_THRESHOLD < 1):
    raise RuntimeError("Fraud thresholds must satisfy 0 < review < block < 1")

def classify_fraud_score(score):
    if not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("The fraud model returned an invalid probability")
    if score <= FRAUD_REVIEW_THRESHOLD:
        return "LOW", "APPROVE"
    if score <= FRAUD_BLOCK_THRESHOLD:
        return "MEDIUM", "REVIEW"
    return "HIGH", "BLOCK"

# Load artifacts at startup
try:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    MODELS_DIR = os.path.join(BASE_DIR, "models")
    baseline_pipeline = joblib.load(os.path.join(MODELS_DIR, "baseline_pipeline.pkl"))
    artifacts_loaded = True
except Exception:
    logger.exception("Failed to load the Logistic Regression baseline artifact")
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
    TransactionAmt: float = Field(..., gt=0, le=100000000)
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
    checkout_attempt_id: Optional[str] = Field(None, min_length=1, max_length=64)

    @validator("TransactionAmt", "dist1", "dist2", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8", "C9", "C10", "C11", "C12", "C13", "C14", "card1", "card2", "card3", "card5", "addr1", "addr2")
    def reject_non_finite_numbers(cls, value):
        if value is not None and not math.isfinite(value):
            raise ValueError("Numeric transaction features must be finite")
        return value

class PredictionResponse(BaseModel):
    transaction_id: int
    fraud_probability: float
    risk_level: str
    decision: str
    model_used: str

class OrderItemRequest(BaseModel):
    product_id: str = Field(..., min_length=1, max_length=64)
    quantity: int = Field(..., gt=0, le=20)

class OrderAddressInput(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=200)
    line1: str = Field(..., min_length=1, max_length=300)
    city: str = Field(..., min_length=1, max_length=120)
    postal_code: str = Field(..., min_length=1, max_length=32)
    country: str = Field(..., min_length=1, max_length=100)

    @validator("full_name", "line1", "city", "postal_code", "country")
    def trim_address_values(cls, value):
        normalized = value.strip()
        if not normalized:
            raise ValueError("Address fields cannot be blank")
        return normalized

class CreateOrderRequest(BaseModel):
    transaction_id: int = Field(..., gt=0)
    items: List[OrderItemRequest] = Field(..., min_length=1, max_length=20)
    payment_method: str
    shipping_address: OrderAddressInput
    billing_address: OrderAddressInput

    @validator("payment_method")
    def validate_payment_method(cls, value):
        if value not in {"CARD", "PAYPAL", "BANK_TRANSFER"}:
            raise ValueError("Unsupported payment method")
        return value

    @validator("items")
    def reject_duplicate_products(cls, value):
        ids = [item.product_id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Each product may appear only once")
        return value

class AdminReviewRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=1000)

    @validator("reason")
    def normalize_reason(cls, value):
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

@app.get("/")
def read_root():
    return {"message": "Fraud Detection Backend is running"}

@app.get("/api/products")
def get_products():
    return SAMPLE_CATALOG

@app.get("/api/products/{product_id}")
def get_product_by_id(product_id: str):
    product = get_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail="Product not found")
    return product

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
        transaction_data = transaction.model_dump(exclude={"checkout_attempt_id"})
        if transaction.checkout_attempt_id:
            existing = db.query(Transaction).filter(
                Transaction.checkout_attempt_id == transaction.checkout_attempt_id
            ).first()
            if existing is not None:
                if existing.user_id != current_user.id or existing.transaction_data != transaction_data:
                    raise HTTPException(status_code=409, detail="Checkout attempt conflicts with an existing transaction")
                existing_prediction = db.query(FraudPrediction).filter(
                    FraudPrediction.transaction_id == existing.id
                ).order_by(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()).first()
                if existing_prediction is None:
                    raise HTTPException(status_code=503, detail="Fraud assessment is temporarily unavailable")
                return PredictionResponse(
                    transaction_id=existing.id,
                    fraud_probability=existing_prediction.fraud_probability,
                    risk_level=existing_prediction.risk_level,
                    decision=existing_prediction.decision,
                    model_used=existing_prediction.model_used,
                )
        df = pd.DataFrame([transaction_data])
        fraud_prob = float(baseline_pipeline.predict_proba(df)[0, 1])
        risk_level, decision = classify_fraud_score(fraud_prob)
            
        # Store in database
        db_tx = Transaction(
            user_id=current_user.id,
            amount=transaction.TransactionAmt,
            transaction_data=transaction_data,
            checkout_attempt_id=transaction.checkout_attempt_id,
            status={"APPROVE": "APPROVED", "REVIEW": "REVIEW", "BLOCK": "BLOCKED"}[decision],
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
        
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        logger.exception("Fraud prediction failed")
        raise HTTPException(status_code=503, detail="Fraud assessment is temporarily unavailable") from e


def serialize_order(order):
    return {
        "id": order.id,
        "date": order.created_at,
        "created_at": order.created_at,
        "status": order.status,
        "paymentStatus": order.payment_status,
        "payment_status": order.payment_status,
        "paymentMethod": order.payment_method,
        "transactionId": order.transaction_id,
        "transaction_id": order.transaction_id,
        "amount": order.amount,
        "currency": order.currency,
        "items": order.items,
        "shipping_address": order.shipping_address,
        "billing_address": order.billing_address,
    }

@app.post("/api/orders", status_code=201)
def create_order(request: CreateOrderRequest, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    existing = db.query(Order).filter(Order.transaction_id == request.transaction_id).first()
    if existing is not None:
        if existing.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Transaction not found")
        return serialize_order(existing)

    transaction = db.query(Transaction).filter(
        Transaction.id == request.transaction_id, Transaction.user_id == current_user.id
    ).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")

    prediction = db.query(FraudPrediction).filter(
        FraudPrediction.transaction_id == transaction.id
    ).order_by(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()).first()
    if prediction is None:
        raise HTTPException(status_code=409, detail="Fraud assessment is required before ordering")
    model_approved = prediction.decision == "APPROVE" and transaction.status in {"APPROVED", "ORDERED"}
    admin_approved_review = (
        prediction.decision == "REVIEW"
        and transaction.status in {"REVIEW_APPROVED", "ORDERED"}
        and transaction.review_decision == "APPROVE"
    )
    if not (model_approved or admin_approved_review):
        raise HTTPException(status_code=409, detail="This transaction is not approved for payment")

    priced_items = []
    total = 0.0
    for requested_item in request.items:
        product = get_product(requested_item.product_id)
        if product is None:
            raise HTTPException(status_code=422, detail="A selected product is unavailable")
        if requested_item.quantity > product["stock"]:
            raise HTTPException(status_code=409, detail="Requested quantity exceeds available sample stock")
        line_total = round(product["price"] * requested_item.quantity, 2)
        total += line_total
        priced_items.append({
            "product_id": product["id"],
            "name": product["name"],
            "quantity": requested_item.quantity,
            "unit_price": product["price"],
            "line_total": line_total,
        })
    total = round(total, 2)
    if not math.isclose(total, round(transaction.amount, 2), abs_tol=0.01):
        raise HTTPException(status_code=409, detail="Cart total changed; restart fraud verification")

    order = Order(
        user_id=current_user.id,
        transaction_id=transaction.id,
        items=priced_items,
        shipping_address=request.shipping_address.model_dump(),
        billing_address=request.billing_address.model_dump(),
        amount=total,
        currency=transaction.currency or "USD",
        status="PROCESSING",
        payment_status="SIMULATED",
        payment_method=request.payment_method,
    )
    transaction.status = "ORDERED"
    db.add(order)
    try:
        db.commit()
        db.refresh(order)
    except Exception as error:
        db.rollback()
        logger.exception("Order persistence failed")
        raise HTTPException(status_code=503, detail="Order could not be saved; please retry") from error
    return serialize_order(order)

@app.get("/api/orders")
def get_orders(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    orders = db.query(Order).filter(Order.user_id == current_user.id).order_by(Order.created_at.desc(), Order.id.desc()).all()
    return [serialize_order(order) for order in orders]


@app.get("/api/transactions/{transaction_id}/status")
def get_transaction_status(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.user_id == current_user.id,
    ).first()
    if transaction is None:
        # Use the same response for unknown and other customers' transactions.
        raise HTTPException(status_code=404, detail="Transaction not found")

    prediction = db.query(FraudPrediction).filter(
        FraudPrediction.transaction_id == transaction.id
    ).order_by(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()).first()
    return {
        "transaction_id": transaction.id,
        "status": transaction.status,
        "review_decision": transaction.review_decision,
        "reviewed_at": transaction.reviewed_at,
        "fraud_prediction": (
            {
                "fraud_probability": prediction.fraud_probability,
                "risk_level": prediction.risk_level,
                "decision": prediction.decision,
                "model_used": prediction.model_used,
                "created_at": prediction.created_at,
            }
            if prediction is not None else None
        ),
    }

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
        db.query(LatestPrediction, Transaction, User)
        .join(Transaction, LatestPrediction.transaction_id == Transaction.id)
        .outerjoin(User, Transaction.user_id == User.id)
        .filter(ranked_predictions.c.row_number == 1)
        .order_by(LatestPrediction.created_at.desc(), LatestPrediction.id.desc())
        .limit(limit)
        .all()
    )
    
    results = []
    for pred, transaction, customer in rows:
        results.append({
            "id": pred.id,
            "transaction_id": pred.transaction_id,
            "fraud_probability": pred.fraud_probability,
            "risk_level": pred.risk_level,
            "decision": pred.decision,
            "model_used": pred.model_used,
            "created_at": pred.created_at,
            "amount": transaction.amount,
            "customer_name": customer.name if customer is not None else None,
            "customer_email": customer.email if customer is not None else None,
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


def serialize_review_transaction(transaction, customer, prediction):
    return {
        "transaction_id": transaction.id,
        "amount": transaction.amount,
        "currency": transaction.currency,
        "status": transaction.status,
        "created_at": transaction.created_at,
        "customer": (
            {"user_id": customer.id, "name": customer.name, "email": customer.email}
            if customer is not None else None
        ),
        "fraud_prediction": {
            "fraud_probability": prediction.fraud_probability,
            "risk_level": prediction.risk_level,
            "decision": prediction.decision,
            "model_used": prediction.model_used,
            "prediction_created_at": prediction.created_at,
        },
    }


@app.get("/api/admin/reviews/pending")
def get_pending_reviews(
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    from sqlalchemy.orm import aliased

    ranked = (
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
        ).subquery()
    )
    LatestPrediction = aliased(FraudPrediction, ranked)
    rows = (
        db.query(Transaction, User, LatestPrediction)
        .outerjoin(User, Transaction.user_id == User.id)
        .join(ranked, (LatestPrediction.transaction_id == Transaction.id) & (ranked.c.row_number == 1))
        .filter(Transaction.status == "REVIEW", LatestPrediction.decision == "REVIEW")
        .order_by(Transaction.created_at.asc(), Transaction.id.asc())
        .all()
    )
    return [serialize_review_transaction(transaction, customer, prediction) for transaction, customer, prediction in rows]


def decide_review(transaction_id: int, decision: str, request: AdminReviewRequest, db: Session, current_admin: Admin):
    from datetime import datetime

    ranked = (
        db.query(
            FraudPrediction.id.label("id"),
            FraudPrediction.transaction_id.label("transaction_id"),
            FraudPrediction.decision.label("decision"),
            func.row_number().over(
                partition_by=FraudPrediction.transaction_id,
                order_by=(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()),
            ).label("row_number"),
        ).filter(FraudPrediction.transaction_id == transaction_id).subquery()
    )
    latest = db.query(ranked).filter(ranked.c.row_number == 1).first()
    if latest is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if latest.decision != "REVIEW":
        raise HTTPException(status_code=409, detail="Only transactions with a REVIEW prediction can be reviewed")

    final_status = "REVIEW_APPROVED" if decision == "APPROVE" else "REJECTED"
    now = datetime.utcnow()
    updated = (
        db.query(Transaction)
        .filter(Transaction.id == transaction_id, Transaction.status == "REVIEW")
        .update({
            Transaction.status: final_status,
            Transaction.review_decision: decision,
            Transaction.reviewed_by_admin_id: current_admin.id,
            Transaction.reviewed_at: now,
            Transaction.review_reason: request.reason,
        }, synchronize_session=False)
    )
    if updated != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="This transaction has already been reviewed")
    db.commit()
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    return {
        "transaction_id": transaction.id,
        "status": transaction.status,
        "review_decision": transaction.review_decision,
        "reviewed_by_admin_id": transaction.reviewed_by_admin_id,
        "reviewed_at": transaction.reviewed_at,
        "review_reason": transaction.review_reason,
    }


@app.post("/api/admin/reviews/{transaction_id}/approve")
def approve_review(
    transaction_id: int,
    request: AdminReviewRequest = AdminReviewRequest(),
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    return decide_review(transaction_id, "APPROVE", request, db, current_admin)


@app.post("/api/admin/reviews/{transaction_id}/reject")
def reject_review(
    transaction_id: int,
    request: AdminReviewRequest = AdminReviewRequest(),
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    return decide_review(transaction_id, "REJECT", request, db, current_admin)


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
