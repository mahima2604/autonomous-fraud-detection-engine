from fastapi import FastAPI, HTTPException, Depends, Query
from pydantic import BaseModel, Field, validator
from typing import List, Optional
import joblib
import logging
import datetime
from contextlib import asynccontextmanager
import math
import os
import pandas as pd
import sys
import torch
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text, func, and_, or_

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
from app.cors import install_global_cors
from app.ml.model import GraphSAGE
from app.graph.graph_builder import build_homogeneous_transaction_graph
from app.ml.preprocessing import select_features_and_preprocess

logger = logging.getLogger(__name__)

def _add_missing_order_columns(database_engine):
    """Add columns missing from an older orders table without rebuilding it."""
    table_name = Order.__table__.name
    quoted_table = database_engine.dialect.identifier_preparer.quote(table_name)
    with database_engine.begin() as connection:
        existing_columns = {
            column["name"]
            for column in inspect(connection).get_columns(table_name)
        }
        for column in Order.__table__.columns:
            if column.name in existing_columns:
                continue
            if column.primary_key:
                raise RuntimeError(
                    f"Cannot add missing primary key column {table_name}.{column.name} safely"
                )
            quoted_column = database_engine.dialect.identifier_preparer.quote(column.name)
            column_type = column.type.compile(dialect=database_engine.dialect)
            # Existing rows need to remain valid; SQLite cannot add a NOT NULL
            # column without a default, and no truthful value can be inferred.
            connection.execute(text(
                f"ALTER TABLE {quoted_table} ADD COLUMN {quoted_column} {column_type}"
            ))


def initialize_database(database_engine=None):
    """Create missing tables and apply the existing additive schema migrations."""
    database_engine = database_engine or engine
    Base.metadata.create_all(bind=database_engine)
    if "name" not in {column["name"] for column in inspect(database_engine).get_columns("users")}:
        with database_engine.begin() as connection:
            connection.execute(text("ALTER TABLE users ADD COLUMN name VARCHAR"))
    transaction_columns = {column["name"] for column in inspect(database_engine).get_columns("transactions")}
    if "checkout_attempt_id" not in transaction_columns:
        with database_engine.begin() as connection:
            connection.execute(text("ALTER TABLE transactions ADD COLUMN checkout_attempt_id VARCHAR(64)"))
    if "checkout_snapshot" not in transaction_columns:
        with database_engine.begin() as connection:
            connection.execute(text("ALTER TABLE transactions ADD COLUMN checkout_snapshot JSON"))
    review_columns = {
        "review_decision": "VARCHAR",
        "reviewed_by_admin_id": "INTEGER REFERENCES admins(id)",
        "reviewed_at": "DATETIME",
        "review_reason": "VARCHAR",
    }
    for column_name, column_type in review_columns.items():
        if column_name not in transaction_columns:
            with database_engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE transactions ADD COLUMN {column_name} {column_type}"))
    _add_missing_order_columns(database_engine)
    with database_engine.begin() as connection:
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_checkout_attempt_id ON transactions (checkout_attempt_id)"))


from app.admin_provisioning import bootstrap_demo_admin

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


BASELINE_FEATURES = (
    "TransactionAmt",
    "ProductCD",
    "P_emaildomain",
    "DeviceType",
    "DeviceInfo",
)


def build_prediction_explanation(transaction, prediction):
    """Describe stored model inputs and, when verifiable, linear log-odds contributions."""
    payload = transaction.transaction_data or {}
    pipeline = baseline_pipeline if artifacts_loaded else None
    preprocessor = None
    feature_names = list(BASELINE_FEATURES)
    if pipeline is not None:
        try:
            preprocessor = pipeline.named_steps["preprocessor"]
            feature_names = list(preprocessor.feature_names_in_)
        except (AttributeError, KeyError, TypeError):
            preprocessor = None

    feature_values = [{"name": name, "value": payload.get(name)} for name in feature_names]
    explanation = {
        "transaction_id": transaction.id,
        "model_name": prediction.model_used,
        "model_version": getattr(pipeline, "model_version_", None) if pipeline is not None else None,
        "risk_score": prediction.fraud_probability,
        "risk_category": prediction.risk_level,
        "model_decision": prediction.decision,
        "thresholds": {
            "review": FRAUD_REVIEW_THRESHOLD,
            "block": FRAUD_BLOCK_THRESHOLD,
            "applicable_rule": (
                f"score <= {FRAUD_REVIEW_THRESHOLD:.2f}"
                if prediction.decision == "APPROVE"
                else f"{FRAUD_REVIEW_THRESHOLD:.2f} < score <= {FRAUD_BLOCK_THRESHOLD:.2f}"
                if prediction.decision == "REVIEW"
                else f"score > {FRAUD_BLOCK_THRESHOLD:.2f}"
            ),
        },
        "features": feature_values,
        "attribution_available": False,
        "feature_contributions": [],
        "attribution_note": "Precise feature attribution is unavailable for this stored prediction.",
        "review": {
            "transaction_status": transaction.status,
            "decision": transaction.review_decision,
            "reviewed_at": transaction.reviewed_at,
        },
    }

    if pipeline is None or preprocessor is None:
        return explanation

    try:
        classifier = pipeline.named_steps["classifier"]
        if len(classifier.classes_) != 2 or 1 not in classifier.classes_:
            return explanation

        model_input = pd.DataFrame([{name: payload.get(name) for name in feature_names}], columns=feature_names)
        transformed = preprocessor.transform(model_input)
        if hasattr(transformed, "toarray"):
            transformed = transformed.toarray()
        transformed = transformed[0]
        output_names = list(preprocessor.get_feature_names_out())
        if len(output_names) != len(transformed):
            return explanation

        classes = list(classifier.classes_)
        positive_index = classes.index(1)
        coefficient_index = 0 if len(classes) == 2 else positive_index
        coefficients = classifier.coef_[coefficient_index]
        intercept = float(classifier.intercept_[coefficient_index])
        linear_score = float(intercept + sum(float(value) * float(weight) for value, weight in zip(transformed, coefficients)))
        current_probability = float(pipeline.predict_proba(model_input)[0][positive_index])
        if not math.isclose(current_probability, prediction.fraud_probability, abs_tol=0.000051):
            explanation["attribution_note"] = (
                "The currently loaded model does not reproduce the stored score, so feature attribution is unavailable."
            )
            return explanation

        grouped = {name: 0.0 for name in feature_names}
        sorted_features = sorted(feature_names, key=len, reverse=True)
        for output_name, value, coefficient in zip(output_names, transformed, coefficients):
            encoded_name = output_name.split("__", 1)[-1]
            source = next(
                (name for name in sorted_features if encoded_name == name or encoded_name.startswith(f"{name}_")),
                None,
            )
            if source is None:
                return explanation
            grouped[source] += float(value) * float(coefficient)

        explanation["attribution_available"] = True
        explanation["feature_contributions"] = [
            {
                "name": name,
                "contribution_log_odds": round(grouped[name], 6),
                "direction": "increases" if grouped[name] > 0 else "decreases" if grouped[name] < 0 else "no change",
            }
            for name in feature_names
        ]
        explanation["baseline_log_odds"] = round(intercept, 6)
        explanation["model_log_odds"] = round(linear_score, 6)
        explanation["attribution_note"] = (
            "Contributions are to the Logistic Regression log-odds relative to its intercept; "
            "they describe model association, not causation. Categorical one-hot contributions are grouped by input feature."
        )
    except Exception:
        # Keep the factual stored score and inputs available if a future artifact
        # no longer exposes the fitted linear pipeline used for this prediction.
        return explanation

    return explanation

# Load artifacts at startup
try:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    MODELS_DIR = os.path.join(BASE_DIR, "models")
    baseline_pipeline = joblib.load(os.path.join(MODELS_DIR, "baseline_pipeline.pkl"))
    artifacts_loaded = True
except Exception:
    logger.exception("Failed to load the Logistic Regression baseline artifact")
    artifacts_loaded = False

# The Logistic Regression model remains available as an explicit selection or
# explicitly configured failure fallback. A broken GNN never falls back silently.
PRIMARY_FRAUD_MODEL = os.getenv("FRAUD_PRIMARY_MODEL", "gnn").strip().lower()
FALLBACK_FRAUD_MODEL = os.getenv("FRAUD_FALLBACK_MODEL", "").strip().lower()
if PRIMARY_FRAUD_MODEL not in {"gnn", "logistic_regression"}:
    raise RuntimeError("FRAUD_PRIMARY_MODEL must be gnn or logistic_regression")
if FALLBACK_FRAUD_MODEL not in {"", "logistic_regression"}:
    raise RuntimeError("FRAUD_FALLBACK_MODEL must be empty or logistic_regression")

gnn_model = None
gnn_artifacts_loaded = False
gnn_metadata = None
gnn_scalers = None
gnn_encoders = None
try:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    MODELS_DIR = os.path.join(BASE_DIR, "models")
    import json
    with open(os.path.join(MODELS_DIR, "graphsage_metadata.json"), encoding="utf-8") as metadata_file:
        gnn_metadata = json.load(metadata_file)
    expected_features = ["TransactionAmt", "ProductCD", "P_emaildomain", "DeviceType", "DeviceInfo"]
    if gnn_metadata.get("input_features") != expected_features:
        raise ValueError("GraphSAGE feature schema does not match checkout inputs")
    gnn_model = GraphSAGE(
        in_channels=int(gnn_metadata["in_channels"]),
        hidden_channels=int(gnn_metadata["hidden_channels"]),
        num_layers=int(gnn_metadata["num_layers"]),
        dropout=float(gnn_metadata.get("dropout", 0.5)),
        categorical_cardinalities=gnn_metadata["categorical_cardinalities"],
        embedding_dim=int(gnn_metadata["embedding_dim"]),
    )
    gnn_model.load_state_dict(torch.load(os.path.join(MODELS_DIR, "graphsage.pth"), map_location="cpu", weights_only=True))
    gnn_model.eval()
    gnn_scalers = joblib.load(os.path.join(MODELS_DIR, "gnn_scalers.pkl"))
    gnn_encoders = joblib.load(os.path.join(MODELS_DIR, "gnn_encoders.pkl"))
    gnn_artifacts_loaded = True
except Exception:
    logger.exception("Failed to load the GraphSAGE model and preprocessing artifacts")

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
    checkout_snapshot: Optional[dict] = None

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


def derive_checkout_product_category(checkout_snapshot):
    """Use the trusted catalog category as ProductCD for storefront checkouts."""
    categories = {
        product["category"]
        for item in (checkout_snapshot or {}).get("items", [])
        if isinstance(item, dict)
        for product in [get_product(item.get("product_id"))]
        if product is not None and product.get("category")
    }
    if not categories:
        return "UNKNOWN"
    if len(categories) == 1:
        return next(iter(categories))
    return "Mixed"


def predict_with_gnn(transaction_data, current_user, db):
    """Score the new checkout node against a bounded, causal history graph."""
    if not gnn_artifacts_loaded or gnn_model is None:
        raise RuntimeError("GraphSAGE artifacts are unavailable")
    edge_cols = gnn_metadata["edge_features"]
    features = gnn_metadata["input_features"]
    historical = (
        db.query(Transaction)
        .filter(Transaction.transaction_data.isnot(None))
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(5000)
        .all()
    )
    rows = []
    for item in reversed(historical):
        values = item.transaction_data or {}
        row = {column: values.get(column) for column in features}
        row["created_at"] = item.created_at
        rows.append(row)
    current = {column: transaction_data.get(column) for column in features}
    current["created_at"] = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    rows.append(current)
    raw = pd.DataFrame(rows)
    for column in gnn_metadata["categorical_features"]:
        raw[column] = raw[column].fillna("UNKNOWN").astype(str)
    raw["TransactionAmt"] = pd.to_numeric(raw["TransactionAmt"], errors="coerce").fillna(0.0)
    processed, _, _ = select_features_and_preprocess(
        raw,
        gnn_metadata["numerical_features"],
        gnn_metadata["categorical_features"],
        is_train=False,
        scalers=gnn_scalers,
        encoders=gnn_encoders,
    )
    graph_frame = raw[["created_at"]].copy()
    for feature in features:
        graph_frame[feature] = processed[feature].to_numpy()
    graph = build_homogeneous_transaction_graph(
        graph_frame,
        features,
        edge_cols,
        max_neighbors=int(gnn_metadata.get("max_neighbors", 10)),
        edge_frame=raw[[*edge_cols, "created_at"]],
    )
    with torch.no_grad():
        logits = gnn_model(graph.x, graph.edge_index)
        probability = float(torch.sigmoid(logits[-1]).item())
    return probability


def score_transaction(transaction_data, current_user, db):
    if PRIMARY_FRAUD_MODEL == "logistic_regression":
        if not artifacts_loaded:
            raise RuntimeError("Logistic Regression artifact is unavailable")
        frame = pd.DataFrame([transaction_data])
        return float(baseline_pipeline.predict_proba(frame)[0, 1]), "LogisticRegression_Baseline"
    try:
        return predict_with_gnn(transaction_data, current_user, db), "GraphSAGE"
    except Exception:
        logger.exception("GraphSAGE prediction failed")
        if FALLBACK_FRAUD_MODEL == "logistic_regression" and artifacts_loaded:
            logger.warning("Using explicitly configured Logistic Regression failure fallback")
            frame = pd.DataFrame([transaction_data])
            return float(baseline_pipeline.predict_proba(frame)[0, 1]), "LogisticRegression_Baseline_Fallback"
        raise

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
    active_model_loaded = gnn_artifacts_loaded if PRIMARY_FRAUD_MODEL == "gnn" else artifacts_loaded
    if not active_model_loaded:
        raise HTTPException(status_code=500, detail="Configured fraud model artifacts are not loaded.")
        
    try:
        transaction_data = transaction.model_dump(exclude={"checkout_attempt_id", "checkout_snapshot"})
        if transaction.checkout_snapshot is not None:
            # ProductCD is derived from the backend catalog, not trusted from the browser.
            transaction_data["ProductCD"] = derive_checkout_product_category(transaction.checkout_snapshot)
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
        fraud_prob, model_name = score_transaction(transaction_data, current_user, db)
        risk_level, decision = classify_fraud_score(fraud_prob)
            
        # Store in database
        db_tx = Transaction(
            user_id=current_user.id,
            amount=transaction.TransactionAmt,
            transaction_data=transaction_data,
            checkout_snapshot=transaction.checkout_snapshot,
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
            model_used=model_name
        )
        db.add(db_pred)
        db.commit()
            
        return PredictionResponse(
            transaction_id=db_tx.id,
            fraud_probability=round(fraud_prob, 4),
            risk_level=risk_level,
            decision=decision,
            model_used=model_name
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

    # Once captured, the backend snapshot is authoritative for resumed checkout.
    # Legacy transactions without snapshots continue to use the validated request.
    snapshot = transaction.checkout_snapshot
    if snapshot:
        try:
            items = [OrderItemRequest(**item) for item in snapshot["items"]]
            shipping_address = OrderAddressInput(**snapshot["shipping_address"])
            billing_address = OrderAddressInput(**snapshot["billing_address"])
            payment_method = snapshot["payment_method"]
            if payment_method not in {"CARD", "PAYPAL", "BANK_TRANSFER"}:
                raise ValueError("Unsupported payment method")
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise HTTPException(status_code=409, detail="Saved checkout details are incomplete; start a new checkout") from error
    else:
        items = request.items
        shipping_address = request.shipping_address
        billing_address = request.billing_address
        payment_method = request.payment_method

    priced_items = []
    total = 0.0
    for requested_item in items:
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
        shipping_address=shipping_address.model_dump(),
        billing_address=billing_address.model_dump(),
        amount=total,
        currency=transaction.currency or "USD",
        status="PROCESSING",
        payment_status="SIMULATED",
        payment_method=payment_method,
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
        "checkout_snapshot": transaction.checkout_snapshot,
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
def get_recent_predictions(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db), current_admin: Admin = Depends(get_current_admin)):
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
        .filter(or_(
            ranked_predictions.c.decision.in_(("REVIEW", "BLOCK")),
            Transaction.status.in_(("REVIEW", "REVIEW_APPROVED", "REJECTED", "BLOCKED")),
        ))
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
            "status": transaction.status,
            "review_decision": transaction.review_decision,
            "reviewed_at": transaction.reviewed_at,
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

    rows = (
        db.query(
            Transaction,
            User,
            ranked_predictions.c.id.label("prediction_id"),
            ranked_predictions.c.fraud_probability,
            ranked_predictions.c.risk_level,
            ranked_predictions.c.decision,
            ranked_predictions.c.model_used,
            ranked_predictions.c.created_at.label("prediction_created_at"),
            Order.id.label("order_id"),
        )
        .outerjoin(User, Transaction.user_id == User.id)
        .outerjoin(ranked_predictions, and_(
            ranked_predictions.c.transaction_id == Transaction.id,
            ranked_predictions.c.row_number == 1,
        ))
        .outerjoin(Order, Order.transaction_id == Transaction.id)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .all()
    )

    results = []
    for transaction, customer, prediction_id, fraud_probability, risk_level, decision, model_used, prediction_created_at, order_id in rows:
        result = {
            "transaction_id": transaction.id,
            "amount": transaction.amount,
            "currency": transaction.currency,
            "status": transaction.status,
            "review_decision": transaction.review_decision,
            "reviewed_at": transaction.reviewed_at,
            "created_at": transaction.created_at,
            "order_id": order_id,
            "customer": (
                {"user_id": customer.id, "name": customer.name, "email": customer.email}
                if customer is not None else None
            ),
        }
        result["fraud_prediction"] = (
            {
                "fraud_probability": fraud_probability,
                "risk_level": risk_level,
                "decision": decision,
                "model_used": model_used,
                "prediction_created_at": prediction_created_at,
            }
            if prediction_id is not None else None
        )
        results.append(result)
    return results


@app.get("/api/admin/transactions/{transaction_id}/explanation")
def get_admin_transaction_explanation(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    prediction = db.query(FraudPrediction).filter(
        FraudPrediction.transaction_id == transaction.id
    ).order_by(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()).first()
    if prediction is None:
        raise HTTPException(status_code=404, detail="No fraud prediction is recorded for this transaction")
    return build_prediction_explanation(transaction, prediction)


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


# Wrap the completed FastAPI stack so CORS headers also cover unhandled 500s.
install_global_cors(app)
