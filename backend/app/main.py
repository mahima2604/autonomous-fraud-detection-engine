from fastapi import FastAPI, HTTPException, Depends, Query
from pydantic import BaseModel, Field, ValidationError, validator
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
from sqlalchemy.exc import IntegrityError
import hashlib
import hmac
import secrets

# Ensure backend directory is in sys.path if not running module properly 
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.session import engine, Base, get_db
from app.models.fraud_prediction import FraudPrediction
from app.models.transaction import Transaction
from app.models.user import User
from app.models.admin import Admin
from app.models.order import Order
from app.models.email_verification import EmailVerification
from app.services import email_otp
from app.catalog import SAMPLE_CATALOG, get_product
from app.services.auth import (
    create_access_token, create_admin_access_token, get_current_admin, get_current_user,
    hash_password, verify_password, TOKEN_SECRET,
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


def build_prediction_explanation(transaction, prediction, db=None):
    """Describe stored model inputs, verify score reproduction, and provide truthful explanation."""
    return explain_prediction(transaction, prediction, db=db)


# Load artifacts at startup
try:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    MODELS_DIR = os.path.join(BASE_DIR, "models")
    baseline_pipeline = joblib.load(os.path.join(MODELS_DIR, "baseline_pipeline.pkl"))
    if list(getattr(baseline_pipeline, "feature_names_in_", [])) != list(BASELINE_FEATURES):
        raise ValueError("Logistic Regression artifact feature schema does not match checkout inputs")
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
    if gnn_metadata.get("numerical_features") != ["TransactionAmt"]:
        raise ValueError("GraphSAGE numerical feature schema is incompatible")
    expected_categorical = expected_features[1:]
    if gnn_metadata.get("categorical_features") != expected_categorical:
        raise ValueError("GraphSAGE categorical feature schema is incompatible")
    if int(gnn_metadata.get("in_channels", -1)) != len(expected_features):
        raise ValueError("GraphSAGE input dimension does not match checkout features")
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
    cardinalities = gnn_metadata.get("categorical_cardinalities", [])
    if len(cardinalities) != len(expected_categorical):
        raise ValueError("GraphSAGE categorical dimensions do not match checkout encoders")
    if any(
        column not in gnn_encoders
        or len(gnn_encoders[column].classes_) != cardinality
        or "UNKNOWN" not in gnn_encoders[column].classes_
        for column, cardinality in zip(expected_categorical, cardinalities)
    ):
        raise ValueError("GraphSAGE encoder artifacts do not match model embeddings")
    if "TransactionAmt" not in gnn_scalers:
        raise ValueError("GraphSAGE amount scaler is missing")
    unknown_counts = gnn_metadata.get("categorical_unknown_training_counts", {})
    if int(unknown_counts.get("ProductCD", 0)) == 0:
        # Older metadata does not record sentinel counts. The local training
        # data confirms ProductCD had no missing rows, so its reserved UNKNOWN
        # embedding was never trained; neutralize it without altering artifacts.
        product_index = expected_categorical.index("ProductCD")
        unknown_index = list(gnn_encoders["ProductCD"].classes_).index("UNKNOWN")
        with torch.no_grad():
            gnn_model.embeddings[product_index].weight[unknown_index].zero_()
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
    review_reason: Optional[str] = None

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


class VerifyEmailRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)

    @validator("code")
    def validate_code(cls, value):
        if not value.isdigit():
            raise ValueError("OTP must contain digits only")
        return value


def validate_checkout_items(items):
    """Validate catalog items and calculate a trusted checkout total."""
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        raise HTTPException(status_code=422, detail="Checkout must contain between 1 and 20 products")
    try:
        validated_items = [item if isinstance(item, OrderItemRequest) else OrderItemRequest(**item) for item in items]
    except (TypeError, ValueError, ValidationError) as error:
        raise HTTPException(status_code=422, detail="Checkout contains invalid product details") from error
    product_ids = [item.product_id for item in validated_items]
    if len(product_ids) != len(set(product_ids)):
        raise HTTPException(status_code=422, detail="Each product may appear only once")

    priced_items = []
    total = 0.0
    for requested_item in validated_items:
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
            "category": product["category"],
            "quantity": requested_item.quantity,
            "unit_price": product["price"],
            "line_total": line_total,
        })
    return validated_items, priced_items, round(total, 2)


OTP_TTL = datetime.timedelta(minutes=10)
OTP_RESEND_COOLDOWN = datetime.timedelta(seconds=30)
OTP_SEND_WINDOW = datetime.timedelta(minutes=30)
OTP_MAX_SENDS = 3
OTP_MAX_ATTEMPTS = 5


def otp_hash(user_id, email_address, code):
    payload = f"{user_id}:{email_address.strip().lower()}:{code}".encode("utf-8")
    return hmac.new(TOKEN_SECRET, payload, hashlib.sha256).hexdigest()


def require_verified_email(db, user):
    record = db.query(EmailVerification).filter(EmailVerification.user_id == user.id).first()
    now = datetime.datetime.utcnow()
    email_address = (user.email or "").strip().lower()
    if (record is None or record.status != "VERIFIED" or record.email_address != email_address
            or record.verified_at is None or record.verified_at + datetime.timedelta(hours=24) <= now):
        raise HTTPException(status_code=403, detail="Verify your account email before continuing checkout")
    return record


@app.post("/api/email-verification/send")
def send_email_verification(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.datetime.utcnow()
    email_address = (current_user.email or "").strip().lower()
    if not email_address:
        raise HTTPException(status_code=409, detail="Your account does not have an email address to verify")
    record = db.query(EmailVerification).filter(EmailVerification.user_id == current_user.id).first()
    if record and record.resend_after > now:
        seconds = max(1, int((record.resend_after - now).total_seconds()))
        raise HTTPException(status_code=429, detail=f"Please wait {seconds} seconds before requesting another OTP")
    if record and record.window_started_at + OTP_SEND_WINDOW > now and record.sends_in_window >= OTP_MAX_SENDS:
        raise HTTPException(status_code=429, detail="OTP request limit reached. Try again in 30 minutes")
    email_sends = db.query(EmailVerification).filter(
        EmailVerification.email_address == email_address,
        EmailVerification.created_at >= now - OTP_SEND_WINDOW,
    ).count()
    if email_sends >= OTP_MAX_SENDS:
        raise HTTPException(status_code=429, detail="This email has reached its OTP request limit. Try again in 30 minutes")

    code = f"{secrets.randbelow(1_000_000):06d}"
    if record is None:
        record = EmailVerification(
            user_id=current_user.id, email_address=email_address, code_hash=otp_hash(current_user.id, email_address, code),
            status="PENDING", created_at=now, expires_at=now + OTP_TTL,
            resend_after=now + OTP_RESEND_COOLDOWN, window_started_at=now,
            sends_in_window=1, attempts=0,
        )
        db.add(record)
    else:
        if record.window_started_at + OTP_SEND_WINDOW <= now:
            record.window_started_at = now
            record.sends_in_window = 0
        record.email_address = email_address
        record.code_hash = otp_hash(current_user.id, email_address, code)
        record.status = "PENDING"
        record.created_at = now
        record.expires_at = now + OTP_TTL
        record.resend_after = now + OTP_RESEND_COOLDOWN
        record.sends_in_window += 1
        record.attempts = 0
        record.verified_at = None
    try:
        db.commit()
    except Exception as error:
        db.rollback()
        logger.exception("Email verification challenge persistence failed")
        raise HTTPException(status_code=503, detail="Could not save verification request; please retry") from error

    try:
        email_otp.send_code(email_address, code)
    except Exception as error:
        record.status = "FAILED"
        record.code_hash = None
        db.commit()
        if isinstance(error, email_otp.DeliveryError):
            raise HTTPException(status_code=503, detail=str(error)) from error
        logger.error("Email OTP delivery failed")
        raise HTTPException(status_code=503, detail="Email delivery failed. Check SMTP settings and try again later.") from error
    return {"status": "pending", "email_address": email_address,
            "expires_in_seconds": int(OTP_TTL.total_seconds()),
            "resend_after_seconds": int(OTP_RESEND_COOLDOWN.total_seconds())}


@app.post("/api/email-verification/verify")
def verify_email_address(
    request: VerifyEmailRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = datetime.datetime.utcnow()
    record = db.query(EmailVerification).filter(EmailVerification.user_id == current_user.id).first()
    email_address = (current_user.email or "").strip().lower()
    if (record is None or record.email_address != email_address or record.status != "PENDING"
            or record.code_hash is None):
        raise HTTPException(status_code=409, detail="Request a new OTP for your current account email")
    if record.expires_at <= now:
        record.status = "EXPIRED"
        db.commit()
        raise HTTPException(status_code=410, detail="OTP expired. Request a new OTP")
    if record.attempts >= OTP_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Too many incorrect attempts. Request a new OTP")
    record.attempts += 1
    approved = hmac.compare_digest(record.code_hash, otp_hash(current_user.id, email_address, request.code))
    if approved:
        record.status = "VERIFIED"
        record.verified_at = now
        record.code_hash = None
    try:
        db.commit()
    except Exception as error:
        db.rollback()
        logger.exception("Email verification result persistence failed")
        raise HTTPException(status_code=503, detail="Could not save verification result; please retry") from error
    if not approved:
        raise HTTPException(status_code=400, detail="Invalid OTP. Check the code and try again")
    return {"status": "verified"}


@app.get("/api/email-verification/status")
def email_verification_status(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = db.query(EmailVerification).filter(EmailVerification.user_id == current_user.id).first()
    email_address = (current_user.email or "").strip().lower()
    if record and record.email_address != email_address and record.status != "INVALIDATED":
        record.status = "INVALIDATED"
        record.verified_at = None
        record.code_hash = None
        db.commit()
    try:
        require_verified_email(db, current_user)
    except HTTPException:
        return {"verified": False, "email_address": email_address}
    return {"verified": True, "email_address": email_address}

class AdminReviewRequest(BaseModel):
    reason: Optional[str] = Field(None, max_length=1000)

    @validator("reason")
    def normalize_reason(cls, value):
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


def enrich_checkout_snapshot(checkout_snapshot):
    """Keep trusted storefront categories separate from dataset model features."""
    if not isinstance(checkout_snapshot, dict):
        return checkout_snapshot
    snapshot = dict(checkout_snapshot)
    items = snapshot.get("items")
    if isinstance(items, list):
        enriched_items = []
        for item in items:
            if not isinstance(item, dict):
                enriched_items.append(item)
                continue
            product = get_product(item.get("product_id"))
            enriched_items.append({
                **item,
                **({"store_category": product["category"]} if product else {}),
            })
        snapshot["items"] = enriched_items
    return snapshot


def normalize_device_type(device_type):
    """Validate client device type against model's training schema ('desktop', 'mobile', 'UNKNOWN')."""
    if not device_type or not isinstance(device_type, str):
        return "UNKNOWN"
    normalized = str(device_type).strip().lower()
    if normalized in {"desktop", "mobile"}:
        return normalized
    return "UNKNOWN"


def email_domain_for_model(email):
    """Derive and normalize customer's email domain safely for model preprocessing."""
    if not email or not isinstance(email, str):
        return "UNKNOWN"
    normalized = email.strip().lower()
    parts = normalized.rsplit("@", 1)
    if len(parts) == 2 and parts[1]:
        domain = parts[1].strip()
        if "." in domain and not domain.startswith(".") and not domain.endswith("."):
            return domain
    return "UNKNOWN"


def prepare_checkout_model_features(transaction_data, current_user, checkout_snapshot=None):
    """Normalize storefront inputs to the meanings represented by the artifacts."""
    features = dict(transaction_data)
    user_email = getattr(current_user, "email", None) if current_user else None
    features["P_emaildomain"] = email_domain_for_model(user_email)
    features["DeviceType"] = normalize_device_type(transaction_data.get("DeviceType"))
    # Store categories and browser platform strings are not IEEE-CIS ProductCD
    # codes or device identifiers. Keep the trained model's explicit unknown value.
    features["DeviceInfo"] = "UNKNOWN"
    if checkout_snapshot is not None:
        features["ProductCD"] = "UNKNOWN"
    return features


def checkout_feature_review_reason(transaction_data, model_name=None):
    """Return why this checkout cannot be decided automatically from its features."""
    reasons = []
    product_code = transaction_data.get("ProductCD")
    if product_code is None or not str(product_code).strip() or str(product_code).strip().upper() == "UNKNOWN":
        reasons.append(
            "ProductCD is unavailable: storefront product categories have no verified mapping "
            "to the training dataset's ProductCD values."
        )
    else:
        # UNKNOWN is a reserved encoder fallback, not evidence that the category
        # was represented during training. The fitted GNN encoder is from the
        # same sampled training rows as the baseline pipeline.
        encoder = (gnn_encoders or {}).get("ProductCD")
        supported_values = set(encoder.classes_) - {"UNKNOWN"} if encoder is not None else None
        if supported_values is None and artifacts_loaded:
            try:
                categorical = baseline_pipeline.named_steps["preprocessor"].named_transformers_["cat"]
                one_hot = categorical.named_steps["onehot"]
                supported_values = set(one_hot.categories_[0])
            except (AttributeError, KeyError, IndexError, TypeError):
                supported_values = None
        if supported_values is not None and str(product_code) not in supported_values:
            reasons.append(
                "ProductCD is outside the fitted training categories; the model score is advisory "
                "and requires administrator review."
            )

    if model_name == "GraphSAGE":
        reasons.append(
            "GraphSAGE uses its saved P_emaildomain and DeviceInfo edge schema. Checkout currently "
            "has no trustworthy DeviceInfo source, so graph context may be incomplete and must be reviewed."
        )
    elif model_name and model_name.startswith("LogisticRegression"):
        if product_code is None or not str(product_code).strip() or str(product_code).strip().upper() == "UNKNOWN":
            reasons.append(
                "The Logistic Regression baseline was trained on historical IEEE-CIS data with class-balanced sampling; "
                "its uncalibrated probability is advisory for storefront checkout and requires administrator review."
            )
    return " ".join(reasons) or None


def _build_live_gnn_graph(transaction_data, current_user, db, before_transaction_id=None):
    """Build checkout nodes using the saved GraphSAGE feature and edge schema."""
    if not gnn_metadata:
        raise RuntimeError("GraphSAGE metadata is unavailable")
    edge_features = list(gnn_metadata.get("edge_features", []))
    if edge_features != ["P_emaildomain", "DeviceInfo"]:
        raise RuntimeError("Saved GraphSAGE edge schema is incompatible with checkout graph construction")
    features = list(gnn_metadata["input_features"])
    query = (
        db.query(Transaction, User.email)
        .outerjoin(User, Transaction.user_id == User.id)
        .filter(Transaction.transaction_data.isnot(None))
    )
    if before_transaction_id is not None:
        query = query.filter(Transaction.id < before_transaction_id)
    historical = query.order_by(Transaction.created_at.desc(), Transaction.id.desc()).limit(5000).all()
    rows = []
    edge_rows = []
    for item, customer_email in reversed(historical):
        values = item.transaction_data or {}
        row = {column: values.get(column) for column in features}
        # These are the same sources used for current checkout: account email
        # is backend-authenticated; no client-supplied domain or platform value
        # is treated as an identity key.
        row["P_emaildomain"] = email_domain_for_model(customer_email)
        row["DeviceInfo"] = "UNKNOWN"
        row["created_at"] = item.created_at
        rows.append(row)
        edge_rows.append({column: row.get(column) for column in edge_features} | {"created_at": item.created_at})

    current = {column: transaction_data.get(column) for column in features}
    current["P_emaildomain"] = email_domain_for_model(getattr(current_user, "email", None))
    # Do not substitute navigator.platform for the dataset's DeviceInfo.
    current["DeviceInfo"] = "UNKNOWN"
    current["created_at"] = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    rows.append(current)
    edge_rows.append({column: current.get(column) for column in edge_features} | {"created_at": current["created_at"]})

    raw = pd.DataFrame(rows)
    for column in gnn_metadata["categorical_features"]:
        raw[column] = raw[column].fillna("UNKNOWN").astype(str)
    raw["TransactionAmt"] = pd.to_numeric(raw["TransactionAmt"], errors="coerce").fillna(0.0)
    processed, _, _ = select_features_and_preprocess(
        raw, gnn_metadata["numerical_features"], gnn_metadata["categorical_features"],
        is_train=False, scalers=gnn_scalers, encoders=gnn_encoders,
    )
    graph_frame = raw[["created_at"]].copy()
    for feature in features:
        graph_frame[feature] = processed[feature].to_numpy()
    edge_frame = pd.DataFrame(edge_rows)
    graph = build_homogeneous_transaction_graph(
        graph_frame, features, edge_features,
        max_neighbors=int(gnn_metadata.get("max_neighbors", 10)),
        edge_frame=edge_frame,
    )
    target_idx = len(rows) - 1
    connected_neighbors = (
        int(torch.unique(graph.edge_index[0, graph.edge_index[1] == target_idx]).numel())
        if graph.edge_index.numel() else 0
    )
    target_edge_mask = graph.edge_index[1] == target_idx if graph.edge_index.numel() else torch.zeros(0, dtype=torch.bool)
    connected_edge_types = set(graph.edge_type[target_edge_mask].tolist()) if graph.edge_index.numel() else set()
    live_edge_features = [column for index, column in enumerate(edge_features) if index in connected_edge_types]
    missing_edge_features = [column for index, column in enumerate(edge_features) if index not in connected_edge_types]
    topology_validated = not missing_edge_features and connected_neighbors > 0
    context = {
        "topology": "causal_transaction_graph",
        "edge_type": ", ".join(live_edge_features) if live_edge_features else "No connected historical edges",
        "training_topology": ", ".join(edge_features),
        "live_topology": ", ".join(live_edge_features) if live_edge_features else "No connected historical edges",
        "connected_neighbors": connected_neighbors,
        "topology_validation_status": "VALIDATED" if topology_validated else "UNVALIDATED_INSUFFICIENT_DATA",
        "missing_edge_features": missing_edge_features,
        "feature_order": features,
        "feature_dimensions": int(graph.x.shape[1]),
        "topology_note": (
            "Live inference uses the saved model feature order, fitted encoders/scaler, causal graph builder, "
            "edge columns, and neighbor limit."
            if topology_validated else
            "The live graph uses the saved edge schema where genuine values exist, but full topology validation "
            f"is unavailable: missing relationship data: {', '.join(missing_edge_features) or 'no connected historical transactions'}; "
            f"connected historical transactions: {connected_neighbors}."
        ),
    }
    return graph, context


def predict_with_gnn(transaction_data, current_user, db):
    """Score the new checkout node against a bounded, causal history graph."""
    if not gnn_artifacts_loaded or gnn_model is None:
        raise RuntimeError("GraphSAGE artifacts are unavailable")
    graph, _ = _build_live_gnn_graph(transaction_data, current_user, db)
    with torch.no_grad():
        logits = gnn_model(graph.x, graph.edge_index)
        probability = float(torch.sigmoid(logits[-1]).item())
    return probability


def reproduce_stored_prediction_score(transaction, prediction, db=None):
    """Attempt to reproduce the stored risk score using the original model and inputs."""
    model_name = prediction.model_used or ""
    payload = transaction.transaction_data or {}

    if model_name == "GraphSAGE":
        if not gnn_artifacts_loaded or gnn_model is None:
            return False, None, None, "GraphSAGE model artifacts are not currently loaded"
        if db is None:
            return False, None, None, "Database session was not provided to reconstruct historical graph context"
        try:
            user = db.query(User).filter(User.id == transaction.user_id).first()
            graph, _ = _build_live_gnn_graph(
                payload, user, db, before_transaction_id=transaction.id
            )
            with torch.no_grad():
                logits = gnn_model(graph.x, graph.edge_index)
                recomputed_prob = float(torch.sigmoid(logits[-1]).item())

            target_idx = graph.x.shape[0] - 1
            connected_neighbors = 0
            if graph.edge_index.numel() > 0:
                connected_neighbors = int((graph.edge_index[1] == target_idx).sum().item())

            matches = math.isclose(recomputed_prob, prediction.fraud_probability, abs_tol=0.0001)
            note = (
                "Stored GraphSAGE risk score successfully reproduced from persisted features, historical graph context, and loaded neural network weights."
                if matches
                else f"Recomputed GraphSAGE score ({recomputed_prob:.4f}) does not match stored score ({prediction.fraud_probability:.4f}) within tolerance (0.0001)."
            )
            return matches, recomputed_prob, connected_neighbors, note
        except Exception as error:
            logger.exception("Failed to recompute GraphSAGE score for transaction %s", transaction.id)
            return False, None, None, f"GraphSAGE score recomputation failed: {error}"

    elif model_name.startswith("LogisticRegression"):
        pipeline = baseline_pipeline if artifacts_loaded else None
        if pipeline is None:
            return False, None, None, "Logistic Regression artifact is not loaded"
        try:
            feature_names = list(getattr(pipeline, "feature_names_in_", BASELINE_FEATURES))
            model_input = pd.DataFrame([{name: payload.get(name) for name in feature_names}], columns=feature_names)
            classifier = pipeline.named_steps["classifier"]
            classes = list(classifier.classes_)
            positive_index = classes.index(1) if 1 in classes else 1
            current_probability = float(pipeline.predict_proba(model_input)[0][positive_index])
            matches = math.isclose(current_probability, prediction.fraud_probability, abs_tol=0.0001)
            note = (
                "Stored Logistic Regression risk score successfully reproduced from loaded baseline artifact."
                if matches
                else f"Recomputed Logistic Regression score ({current_probability:.4f}) does not match stored score ({prediction.fraud_probability:.4f}) within tolerance (0.0001)."
            )
            return matches, current_probability, None, note
        except Exception as error:
            return False, None, None, f"Score recomputation failed: {error}"

    return False, None, None, f"No reproduction pipeline available for model '{model_name}'"


def explain_prediction(transaction, prediction, db=None):
    """Describe stored model inputs and, when verifiable, feature attribution or graph context."""
    payload = transaction.transaction_data or {}
    model_name = prediction.model_used or "Unknown"
    is_gnn = model_name == "GraphSAGE"
    is_lr = model_name.startswith("LogisticRegression")

    pipeline = baseline_pipeline if (artifacts_loaded and is_lr) else None
    preprocessor = None
    feature_names = list(BASELINE_FEATURES)
    if is_lr and pipeline is not None:
        try:
            preprocessor = pipeline.named_steps["preprocessor"]
            feature_names = list(preprocessor.feature_names_in_)
        except (AttributeError, KeyError, TypeError):
            preprocessor = None
    elif is_gnn and gnn_metadata is not None:
        feature_names = list(gnn_metadata.get("input_features", BASELINE_FEATURES))

    feature_values = [{"name": name, "value": payload.get(name)} for name in feature_names]
    manual_review_reason = (
        checkout_feature_review_reason(payload, prediction.model_used)
        if prediction.decision == "REVIEW" else None
    )
    try:
        _, score_decision = classify_fraud_score(prediction.fraud_probability)
    except (TypeError, ValueError):
        score_decision = None

    model_version = (
        gnn_metadata.get("model_version", "1")
        if (is_gnn and gnn_metadata)
        else getattr(pipeline, "model_version_", None) if pipeline is not None else None
    )

    matches_score, recomputed_score, connected_neighbors, reproduction_note = reproduce_stored_prediction_score(
        transaction, prediction, db=db
    )

    explanation = {
        "transaction_id": transaction.id,
        "model_name": prediction.model_used,
        "model_version": model_version,
        "risk_score": prediction.fraud_probability,
        "recomputed_risk_score": round(recomputed_score, 4) if recomputed_score is not None else None,
        "score_reproduced": matches_score,
        "reproduction_tolerance": 0.0001,
        "reproduction_note": reproduction_note,
        "risk_category": prediction.risk_level,
        "model_decision": prediction.decision,
        "automated_score_decision": score_decision,
        "manual_review_reason": manual_review_reason,
        "thresholds": {
            "review": FRAUD_REVIEW_THRESHOLD,
            "block": FRAUD_BLOCK_THRESHOLD,
            "applicable_rule": (
                f"manual review required: {manual_review_reason}"
                if manual_review_reason
                else f"score <= {FRAUD_REVIEW_THRESHOLD:.2f}"
                if prediction.decision == "APPROVE"
                else f"{FRAUD_REVIEW_THRESHOLD:.2f} < score <= {FRAUD_BLOCK_THRESHOLD:.2f}"
                if prediction.decision == "REVIEW"
                else f"score > {FRAUD_BLOCK_THRESHOLD:.2f}"
            ),
        },
        "features": feature_values,
        "attribution_available": False,
        "feature_contributions": [],
        "attribution_note": (
            "Linear feature attribution is mathematically inapplicable to Graph Neural Networks. "
            "GraphSAGE generates embeddings via non-linear transformations and neighborhood aggregation over graph edges."
            if is_gnn
            else "Precise feature attribution is unavailable for this stored prediction."
        ),
        "review": {
            "transaction_status": transaction.status,
            "decision": transaction.review_decision,
            "reviewed_at": transaction.reviewed_at,
        },
    }

    if is_gnn:
        try:
            user = db.query(User).filter(User.id == transaction.user_id).first() if db is not None else None
            if db is None:
                raise RuntimeError("Database session was not provided")
            _, graph_context = _build_live_gnn_graph(payload, user, db, before_transaction_id=transaction.id)
            graph_context["stored_score_reproduced"] = matches_score
            if not matches_score:
                graph_context["topology_validation_status"] = "UNVALIDATED_STORED_SCORE_MISMATCH"
                graph_context["topology_note"] += (
                    " The reconstructed graph does not reproduce this stored score, so the original "
                    "prediction's exact inference graph cannot be validated from persisted data."
                )
        except Exception as error:
            graph_context = {
                "topology": "causal_transaction_graph",
                "edge_type": "Unavailable",
                "training_topology": ", ".join(gnn_metadata.get("edge_features", [])) if gnn_metadata else "Unavailable",
                "live_topology": "Unavailable",
                "connected_neighbors": connected_neighbors,
                "topology_validation_status": "UNVALIDATED",
                "missing_edge_features": [],
                "topology_note": f"Live graph context could not be reconstructed: {error}",
            }
        explanation["graph_context"] = graph_context
        return explanation

    if not is_lr or pipeline is None or preprocessor is None:
        return explanation

    if not matches_score:
        explanation["attribution_note"] = (
            "The currently loaded model does not reproduce the stored score within tolerance (0.0001), "
            "so feature attribution is unavailable."
        )
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
        explanation["calibration_notice"] = (
            "The Logistic Regression probability reflects training on an artificially downsampled IEEE-CIS "
            "dataset with class_weight='balanced'. It must not be interpreted as a true probability of fraud "
            "on this storefront channel. The raw score is retained for diagnostic inspection; manual review is required."
        )
        explanation["attribution_note"] = (
            "Contributions are to the Logistic Regression log-odds relative to its intercept; "
            "they describe model association, not causation. Categorical one-hot contributions are grouped by input feature. "
            "Notice: Probabilities are uncalibrated for storefront transactions."
        )
    except Exception:
        return explanation

    return explanation


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

@app.get("/health")
@app.get("/api/health")
def health_check(db: Session = Depends(get_db)):
    db_healthy = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_healthy = False
    active_loaded = gnn_artifacts_loaded if PRIMARY_FRAUD_MODEL == "gnn" else artifacts_loaded
    overall_status = "healthy" if db_healthy and active_loaded else "degraded"
    return {
        "status": overall_status,
        "database": "connected" if db_healthy else "disconnected",
        "active_model": PRIMARY_FRAUD_MODEL,
        "active_model_loaded": active_loaded,
        "gnn_artifacts_loaded": gnn_artifacts_loaded,
        "baseline_artifacts_loaded": artifacts_loaded,
        "version": "1.0.0",
    }

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
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="An account with this email already exists") from error
    except Exception as error:
        db.rollback()
        logger.exception("Customer registration persistence failed")
        raise HTTPException(status_code=503, detail="Account could not be created; please retry") from error
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
        checkout_snapshot = enrich_checkout_snapshot(transaction.checkout_snapshot)
        if checkout_snapshot is not None and "items" in checkout_snapshot:
            require_verified_email(db, current_user)
            checkout_snapshot["verified_email"] = (current_user.email or "").strip().lower()
        elif checkout_snapshot and checkout_snapshot.get("verified_email"):
            require_verified_email(db, current_user)
            checkout_snapshot["verified_email"] = (current_user.email or "").strip().lower()
        transaction_data = prepare_checkout_model_features(
            transaction_data, current_user,
            checkout_snapshot if checkout_snapshot and "items" in checkout_snapshot else None,
        )
        if checkout_snapshot is not None and "items" in checkout_snapshot:
            _, _, trusted_total = validate_checkout_items(checkout_snapshot.get("items"))
            if not math.isclose(trusted_total, round(transaction.TransactionAmt, 2), abs_tol=0.01):
                raise HTTPException(status_code=409, detail="Cart total changed; restart fraud verification")
            transaction_data["TransactionAmt"] = trusted_total
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
                    review_reason=(
                        checkout_feature_review_reason(existing.transaction_data or {}, existing_prediction.model_used)
                        if existing_prediction.decision == "REVIEW" else None
                    ),
                )
        fraud_prob, model_name = score_transaction(transaction_data, current_user, db)
        risk_level, score_decision = classify_fraud_score(fraud_prob)
        review_reason = checkout_feature_review_reason(transaction_data, model_name)
        decision = "REVIEW" if review_reason else score_decision
            
        # Store in database
        db_tx = Transaction(
            user_id=current_user.id,
            amount=transaction_data["TransactionAmt"],
            transaction_data=transaction_data,
            checkout_snapshot=checkout_snapshot,
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
            model_used=model_name,
            review_reason=review_reason,
        )
        
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError:
        db.rollback()
        if transaction.checkout_attempt_id:
            existing = db.query(Transaction).filter(
                Transaction.checkout_attempt_id == transaction.checkout_attempt_id
            ).first()
            if existing is not None and existing.user_id == current_user.id:
                existing_prediction = db.query(FraudPrediction).filter(
                    FraudPrediction.transaction_id == existing.id
                ).order_by(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()).first()
                if existing_prediction is not None:
                    return PredictionResponse(
                        transaction_id=existing.id,
                        fraud_probability=existing_prediction.fraud_probability,
                        risk_level=existing_prediction.risk_level,
                        decision=existing_prediction.decision,
                        model_used=existing_prediction.model_used,
                        review_reason=(
                            checkout_feature_review_reason(existing.transaction_data or {}, existing_prediction.model_used)
                            if existing_prediction.decision == "REVIEW" else None
                        ),
                    )
        raise HTTPException(status_code=409, detail="Checkout attempt conflicts with an existing transaction")
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
    transaction = db.query(Transaction).filter(
        Transaction.id == request.transaction_id, Transaction.user_id == current_user.id
    ).first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    existing = db.query(Order).filter(Order.transaction_id == request.transaction_id).first()
    if existing is not None:
        if existing.user_id != current_user.id:
            raise HTTPException(status_code=404, detail="Transaction not found")
        return serialize_order(existing)

    verified_email = (transaction.checkout_snapshot or {}).get("verified_email")
    current_email = (current_user.email or "").strip().lower()
    if not verified_email or verified_email != current_email:
        raise HTTPException(status_code=403, detail="Email verification is required before ordering")
    require_verified_email(db, current_user)

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
    if snapshot and "items" in snapshot:
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

    items, priced_items, total = validate_checkout_items(items)
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
    except IntegrityError as error:
        db.rollback()
        # Concurrent retries can race after the initial idempotency lookup.
        persisted = db.query(Order).filter(Order.transaction_id == transaction.id).first()
        if persisted is not None:
            if persisted.user_id == current_user.id:
                return serialize_order(persisted)
            raise HTTPException(status_code=404, detail="Transaction not found") from error
        logger.exception("Order persistence failed")
        raise HTTPException(status_code=503, detail="Order could not be saved; please retry") from error
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
                "review_reason": (
                    checkout_feature_review_reason(transaction.transaction_data or {}, prediction.model_used)
                    if prediction.decision == "REVIEW" else None
                ),
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
            "review_reason": (
                checkout_feature_review_reason(transaction.transaction_data or {}, pred.model_used)
                if pred.decision == "REVIEW" else transaction.review_reason
            ),
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
    
    active_serving_model = "GraphSAGE" if PRIMARY_FRAUD_MODEL == "gnn" else "Logistic Regression"
    return {
        "total_predictions": total,
        "risk_breakdown": {
            "LOW": counts.get("LOW", 0),
            "MEDIUM": counts.get("MEDIUM", 0),
            "HIGH": counts.get("HIGH", 0)
        },
        "active_model": active_serving_model,
        "primary_model": PRIMARY_FRAUD_MODEL,
        "gnn_loaded": gnn_artifacts_loaded,
    }


@app.get("/api/admin/benchmark/evaluation")
def get_benchmark_evaluation(
    force_refresh: bool = False,
    current_admin: Admin = Depends(get_current_admin),
):
    """Reproducible held-out benchmark evaluation on IEEE-CIS dataset for GraphSAGE and Logistic Regression."""
    try:
        from app.ml.benchmark_eval import get_or_run_benchmark
        return get_or_run_benchmark(force_refresh=force_refresh)
    except FileNotFoundError as fnf_err:
        logger.exception("Benchmark files or artifacts not found")
        raise HTTPException(status_code=404, detail=str(fnf_err))
    except Exception as exc:
        logger.exception("Failed to run benchmark evaluation")
        raise HTTPException(status_code=500, detail=f"Benchmark evaluation failed: {str(exc)}")


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
            "review_reason": transaction.review_reason,
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
                "review_reason": (
                    checkout_feature_review_reason(transaction.transaction_data or {}, model_used)
                    if decision == "REVIEW" else transaction.review_reason
                ),
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
    return build_prediction_explanation(transaction, prediction, db=db)


def serialize_review_transaction(transaction, customer, prediction):
    return {
        "transaction_id": transaction.id,
        "amount": transaction.amount,
        "currency": transaction.currency,
        "status": transaction.status,
        "review_decision": transaction.review_decision,
        "reviewed_at": transaction.reviewed_at,
        "review_reason": transaction.review_reason,
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
            "review_reason": (
                checkout_feature_review_reason(transaction.transaction_data or {}, prediction.model_used)
                if prediction.decision == "REVIEW" else transaction.review_reason
            ),
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
    try:
        db.commit()
    except Exception as error:
        db.rollback()
        logger.exception("Administrator review persistence failed")
        raise HTTPException(status_code=503, detail="Review decision could not be saved; please retry") from error
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
                        "review_reason": (
                            checkout_feature_review_reason(
                                transaction.transaction_data or {}, prediction.model_used
                            )
                            if prediction.decision == "REVIEW" else None
                        ),
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
