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
from sqlalchemy.orm.exc import NoResultFound
from sqlalchemy import inspect, text, func, and_, or_
from sqlalchemy.exc import IntegrityError
import hashlib
import hmac
import json
import secrets
import statistics

# Ensure backend directory is in sys.path if not running module properly 
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.session import engine, Base, get_db
from app.models.fraud_prediction import FraudPrediction
from app.models.transaction import Transaction
from app.models.user import User
from app.models.admin import Admin
from app.models.order import Order
from app.models.email_verification import EmailVerification
from app.models.order_verification import OrderVerification
from app.services import email_otp
from app.catalog import SAMPLE_CATALOG, FAKESTORE_CATALOG, get_product
from app.services.auth import (
    create_access_token, create_admin_access_token, get_current_admin, get_current_user,
    hash_password, verify_password, TOKEN_SECRET,
)
from app.cors import install_global_cors
from app.ml.model import GraphSAGE
from app.graph.graph_builder import build_homogeneous_transaction_graph
from app.services.risk_policy import (
    FRAUD_REVIEW_THRESHOLD,
    FRAUD_BLOCK_THRESHOLD,
    classify_score as classify_fraud_score,
    checkout_decision as classify_checkout_score,
    medium_requires_targeted_review,
)
from app.ml.preprocessing import select_features_and_preprocess
from app.ml.device_info_v2 import DEVICE_INFO_V2_SOURCE, normalize_browser_platform_hint

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
    user_columns = {column["name"] for column in inspect(database_engine).get_columns("users")}
    user_migrations = {
        "order_otp_window_started_at": "DATETIME",
        "order_otp_sends_in_window": "INTEGER NOT NULL DEFAULT 0",
    }
    for column_name, column_type in user_migrations.items():
        if column_name not in user_columns:
            with database_engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE users ADD COLUMN {column_name} {column_type}"))
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
        "risk_reassessment": "JSON",
    }
    for column_name, column_type in review_columns.items():
        if column_name not in transaction_columns:
            with database_engine.begin() as connection:
                connection.execute(text(f"ALTER TABLE transactions ADD COLUMN {column_name} {column_type}"))
    _add_missing_order_columns(database_engine)
    prediction_columns = {column["name"] for column in inspect(database_engine).get_columns("fraud_predictions")}
    if "score_based_decision" not in prediction_columns:
        with database_engine.begin() as connection:
            connection.execute(text("ALTER TABLE fraud_predictions ADD COLUMN score_based_decision VARCHAR"))
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
baseline_product_cd_values = None
try:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    MODELS_DIR = os.path.join(BASE_DIR, "models")
    baseline_pipeline = joblib.load(os.path.join(MODELS_DIR, "baseline_pipeline.pkl"))
    if list(getattr(baseline_pipeline, "feature_names_in_", [])) != list(BASELINE_FEATURES):
        raise ValueError("Logistic Regression artifact feature schema does not match checkout inputs")
    try:
        categorical = baseline_pipeline.named_steps["preprocessor"].named_transformers_["cat"]
        one_hot = categorical.named_steps["onehot"]
        baseline_product_cd_values = frozenset(one_hot.categories_[0])
    except (AttributeError, KeyError, IndexError, TypeError):
        baseline_product_cd_values = None
    artifacts_loaded = True
except Exception:
    logger.exception("Failed to load the Logistic Regression baseline artifact")
    artifacts_loaded = False

# The Logistic Regression model remains available as an explicit selection or
# explicitly configured failure fallback. A broken GNN never falls back silently.
PRIMARY_FRAUD_MODEL = os.getenv("FRAUD_PRIMARY_MODEL", "gnn_device_v2").strip().lower()
FALLBACK_FRAUD_MODEL = os.getenv("FRAUD_FALLBACK_MODEL", "").strip().lower()
if PRIMARY_FRAUD_MODEL not in {"gnn", "gnn_device_v2", "logistic_regression"}:
    raise RuntimeError("FRAUD_PRIMARY_MODEL must be gnn, gnn_device_v2, or logistic_regression")
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

device_info_v2_model = None
device_info_v2_loaded = False
device_info_v2_metadata = None
device_info_v2_scalers = None
device_info_v2_encoders = None
try:
    DEVICE_INFO_V2_DIR = os.path.join(BASE_DIR, "models", "device_info_v2")
    with open(os.path.join(DEVICE_INFO_V2_DIR, "metadata.json"), encoding="utf-8") as metadata_file:
        device_info_v2_metadata = json.load(metadata_file)
    expected_v2_features = ["TransactionAmt", "ProductCD", "P_emaildomain", "DeviceType", "DeviceInfo"]
    if device_info_v2_metadata.get("model_version") != "2.0-device-platform":
        raise ValueError("DeviceInfo v2 model version is not supported")
    if device_info_v2_metadata.get("input_features") != expected_v2_features:
        raise ValueError("DeviceInfo v2 feature order is incompatible")
    if device_info_v2_metadata.get("edge_features") != ["P_emaildomain"]:
        raise ValueError("DeviceInfo v2 graph must use email-domain edges only")
    device_info_v2_model = GraphSAGE(
        in_channels=int(device_info_v2_metadata["in_channels"]),
        hidden_channels=int(device_info_v2_metadata["hidden_channels"]),
        num_layers=int(device_info_v2_metadata["num_layers"]),
        dropout=float(device_info_v2_metadata.get("dropout", 0.5)),
        categorical_cardinalities=device_info_v2_metadata["categorical_cardinalities"],
        embedding_dim=int(device_info_v2_metadata["embedding_dim"]),
    )
    device_info_v2_model.load_state_dict(torch.load(
        os.path.join(DEVICE_INFO_V2_DIR, "graphsage_device_info_v2.pth"),
        map_location="cpu", weights_only=True,
    ))
    device_info_v2_model.eval()
    device_info_v2_scalers = joblib.load(os.path.join(DEVICE_INFO_V2_DIR, "scalers.pkl"))
    device_info_v2_encoders = joblib.load(os.path.join(DEVICE_INFO_V2_DIR, "encoders.pkl"))
    if any(
        column not in device_info_v2_encoders
        or len(device_info_v2_encoders[column].classes_) != cardinality
        or "UNKNOWN" not in device_info_v2_encoders[column].classes_
        for column, cardinality in zip(expected_v2_features[1:], device_info_v2_metadata["categorical_cardinalities"])
    ):
        raise ValueError("DeviceInfo v2 encoders do not match model embeddings")
    device_info_v2_loaded = True
except FileNotFoundError:
    logger.info("Versioned DeviceInfo v2 artifacts are not installed")
except Exception:
    logger.exception("Failed to load versioned DeviceInfo v2 model artifacts")

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
    DevicePlatformHint: Optional[str] = None
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
    score_based_decision: str
    model_used: str
    review_reason: Optional[str] = None

class OrderItemRequest(BaseModel):
    product_id: str = Field(..., min_length=1, max_length=64)
    quantity: int = Field(..., gt=0, le=20)

class OrderAddressInput(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=200)
    line1: str = Field(..., min_length=1, max_length=300)
    city: str = Field(..., min_length=1, max_length=120)
    locality: Optional[str] = Field("", max_length=120)
    state: Optional[str] = Field("", max_length=120)
    postal_code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")
    country: str = Field(..., min_length=1, max_length=100)
    address_confirmed: bool = False

    @validator("full_name", "line1", "city", "postal_code", "country")
    def trim_address_values(cls, value):
        normalized = value.strip()
        if not normalized:
            raise ValueError("Address fields cannot be blank")
        return normalized

    @validator("locality", "state")
    def trim_optional_address_values(cls, value):
        return value.strip() if isinstance(value, str) else ""

class CreateOrderRequest(BaseModel):
    transaction_id: int = Field(..., gt=0)
    items: List[OrderItemRequest] = Field(..., min_length=1, max_length=20)
    payment_method: str
    shipping_address: OrderAddressInput
    billing_address: OrderAddressInput

    @validator("payment_method")
    def validate_payment_method(cls, value):
        if value not in {"CARD", "PAYPAL", "BANK_TRANSFER", "COD"}:
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


class OrderVerificationSendRequest(BaseModel):
    shipping_address: OrderAddressInput
    address_confirmed: bool = False


class OrderVerificationCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6, pattern=r"^\d{6}$")


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
            "ProductCD": product["ProductCD"],
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
ORDER_OTP_TTL = datetime.timedelta(minutes=10)
ORDER_OTP_RESEND_COOLDOWN = datetime.timedelta(seconds=30)
ORDER_OTP_SEND_WINDOW = datetime.timedelta(minutes=30)
ORDER_OTP_MAX_SENDS_PER_ATTEMPT = 3
ORDER_OTP_MAX_SENDS_PER_USER_WINDOW = 10
ORDER_OTP_MAX_ATTEMPTS = 5


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


def shipping_address_hash(address):
    """Hash the normalized address fields, excluding the client confirmation checkbox."""
    normalized = address if isinstance(address, OrderAddressInput) else OrderAddressInput(**address)
    values = normalized.model_dump(exclude={"address_confirmed"})
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def order_attempt_identifier(transaction):
    return transaction.checkout_attempt_id or f"transaction-{transaction.id}"


def transaction_shipping_address(transaction):
    snapshot = transaction.checkout_snapshot or {}
    if not isinstance(snapshot, dict) or "items" not in snapshot:
        raise HTTPException(status_code=409, detail="This checkout has no saved delivery address; start checkout again")
    try:
        return OrderAddressInput(**snapshot["shipping_address"])
    except (KeyError, TypeError, ValidationError) as error:
        raise HTTPException(status_code=409, detail="The saved delivery address is incomplete; start checkout again") from error


def stable_checkout_snapshot(snapshot):
    if not isinstance(snapshot, dict):
        return snapshot
    return {key: value for key, value in snapshot.items() if key != "verification_signals"}


def transaction_features_hash(transaction):
    payload = json.dumps(transaction.transaction_data or {}, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def current_medium_release_matches(db, transaction, prediction):
    """Validate the saved medium release against the current checkout and OTP."""
    assessment = transaction.risk_reassessment
    release = assessment.get("medium_verification_release") if isinstance(assessment, dict) else None
    if not isinstance(release, dict) or release.get("status") != "RELEASED":
        return False
    try:
        address = transaction_shipping_address(transaction)
        address_hash = shipping_address_hash(address)
    except (HTTPException, ValidationError):
        return False
    attempt_id = order_attempt_identifier(transaction)
    challenge = db.query(OrderVerification).filter(
        OrderVerification.transaction_id == transaction.id,
        OrderVerification.user_id == transaction.user_id,
    ).first()
    now = datetime.datetime.utcnow()
    try:
        medium_score = FRAUD_REVIEW_THRESHOLD < float(prediction.fraud_probability) <= FRAUD_BLOCK_THRESHOLD
    except (TypeError, ValueError):
        medium_score = False
    return bool(
        transaction.status in {"APPROVED", "ORDERED"}
        and prediction.risk_level == "MEDIUM"
        and prediction.decision == "VERIFY"
        and medium_score
        and release.get("checkout_attempt_id") == attempt_id
        and release.get("fraud_prediction_id") == prediction.id
        and release.get("shipping_address_hash") == address_hash
        and release.get("transaction_features_hash") == transaction_features_hash(transaction)
        and release.get("score") == prediction.fraud_probability
        and release.get("score_based_decision") == score_based_decision_for(prediction)
        and address.address_confirmed is True
        and challenge is not None
        and challenge.status in {"VERIFIED", "USED"}
        and challenge.verified_at is not None
        and challenge.expires_at > now
        and challenge.checkout_attempt_id == attempt_id
        and challenge.shipping_address_hash == address_hash
        and challenge.email_address == (release.get("verified_email") or "")
    )


def operational_decision_for(db, transaction, prediction):
    """Return the current workflow decision while preserving model/prediction history."""
    if transaction.review_decision:
        return f"ADMIN_{transaction.review_decision}"
    if transaction.status == "ORDERED":
        return "APPROVE"
    return "REVIEW"


def is_medium_delivery_history_review(transaction, prediction):
    assessment = transaction.risk_reassessment
    medium = assessment.get("medium_verification") if isinstance(assessment, dict) else None
    return bool(
        prediction.risk_level == "MEDIUM"
        and prediction.decision in {"VERIFY", "REVIEW"}
        and isinstance(medium, dict)
        and medium.get("status") == "HELD_FOR_ADMIN_REVIEW"
        and assessment.get("ready_for_admin_decision") is True
    )


def operational_review_reason(transaction, prediction):
    if transaction.review_decision:
        return transaction.review_reason
    if is_medium_delivery_history_review(transaction, prediction):
        medium = (transaction.risk_reassessment or {}).get("medium_verification", {})
        return medium.get("decision_reason")
    return prediction_review_reason(transaction.transaction_data or {}, prediction) or transaction.review_reason


def require_current_medium_review_assessment(transaction, prediction):
    if is_medium_delivery_history_review(transaction, prediction):
        medium = (transaction.risk_reassessment or {}).get("medium_verification", {})
        if (
            not current_reassessment_matches(transaction, prediction)
            or medium.get("transaction_features_hash") != transaction_features_hash(transaction)
        ):
            raise HTTPException(status_code=409, detail="The medium-risk evidence review is stale; reassess this checkout before ordering")


def approved_transaction_prediction(db, transaction, allow_medium_challenge=False):
    prediction = db.query(FraudPrediction).filter(
        FraudPrediction.transaction_id == transaction.id
    ).order_by(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()).first()
    if prediction is None:
        raise HTTPException(status_code=409, detail="Fraud assessment is required before ordering")
    if transaction.status == "REJECTED":
        raise HTTPException(status_code=409, detail="This transaction has been rejected and cannot proceed")
    if allow_medium_challenge:
        require_current_high_risk_reassessment(transaction, prediction)
        require_current_medium_review_assessment(transaction, prediction)
        return prediction
    admin_approved_review = (
        transaction.status in {"REVIEW_APPROVED", "ORDERED"}
        and transaction.review_decision == "APPROVE"
    )
    if not admin_approved_review:
        raise HTTPException(status_code=409, detail="This transaction is not approved for payment")
    require_current_high_risk_reassessment(transaction, prediction)
    return prediction


def score_based_decision_for(prediction):
    if prediction.score_based_decision in {"APPROVE", "REVIEW", "BLOCK"}:
        return prediction.score_based_decision
    try:
        return classify_fraud_score(float(prediction.fraud_probability))[1]
    except (TypeError, ValueError):
        raise HTTPException(status_code=409, detail="The stored fraud score is invalid; administrator review is required")


def score_classification_fields(prediction):
    """Expose current score bands beside the immutable classification stored at assessment time."""
    current_risk, current_outcome = classify_fraud_score(float(prediction.fraud_probability))
    recorded_outcome = prediction.score_based_decision
    consistent = (
        prediction.risk_level == current_risk
        and (recorded_outcome is None or recorded_outcome == current_outcome)
    )
    return {
        "risk_level": current_risk,
        "score_based_decision": current_outcome,
        "recorded_risk_level": prediction.risk_level,
        "recorded_score_based_decision": recorded_outcome,
        "classification_consistent": consistent,
    }


def historical_classification_notice(prediction, classification=None):
    """Explain a stored score/category mismatch without changing its audit record."""
    classification = classification or score_classification_fields(prediction)
    return score_classification_notice(float(prediction.fraud_probability), classification)


def score_classification_notice(fraud_probability, classification):
    if classification["classification_consistent"]:
        return None
    recorded_outcome = classification["recorded_score_based_decision"] or "not recorded"
    return (
        f"Historical assessment mismatch: score {float(fraud_probability):.4f} maps to "
        f"{classification['risk_level']} / {classification['score_based_decision']} under current "
        f"{FRAUD_REVIEW_THRESHOLD:.2f}/{FRAUD_BLOCK_THRESHOLD:.2f} thresholds, but the saved record is "
        f"{classification['recorded_risk_level']} / {recorded_outcome}. The stored assessment and "
        "operational status have not been changed."
    )


def is_high_risk_prediction(prediction):
    return prediction.risk_level == "HIGH" or score_based_decision_for(prediction) == "BLOCK"


def normalized_address_key(address):
    normalized = address if isinstance(address, OrderAddressInput) else OrderAddressInput(**address)
    parts = (
        normalized.line1, normalized.locality or "", normalized.city, normalized.state or "",
        normalized.postal_code, normalized.country,
    )
    return "|".join("".join(character for character in part.casefold() if character.isalnum()) for part in parts)


def _address_key_matches(address, target_address):
    try:
        return normalized_address_key(address) == target_address
    except (TypeError, ValidationError):
        return False


def collect_address_account_history(db, transaction, address):
    now = datetime.datetime.utcnow()
    since_24h = now - datetime.timedelta(hours=24)
    since_30d = now - datetime.timedelta(days=30)
    target_address = normalized_address_key(address)
    scanned_orders = db.query(Order).filter(Order.created_at >= since_30d).order_by(Order.created_at.desc()).limit(5000).all()
    matching_orders = [order for order in scanned_orders if _address_key_matches(order.shipping_address, target_address)]
    customer_orders_24h = db.query(Order).filter(
        Order.user_id == transaction.user_id, Order.created_at >= since_24h
    ).count()
    matching_orders_24h = sum(1 for order in matching_orders if order.created_at >= since_24h)

    recent_transactions = db.query(Transaction).filter(
        Transaction.created_at >= since_30d,
        Transaction.id != transaction.id,
    ).order_by(Transaction.created_at.desc()).limit(5000).all()
    matching_other_transactions = [
        item for item in recent_transactions
        if item.user_id != transaction.user_id
        and isinstance(item.checkout_snapshot, dict)
        and isinstance(item.checkout_snapshot.get("shipping_address"), dict)
        and _address_key_matches(item.checkout_snapshot["shipping_address"], target_address)
    ]
    other_user_ids = {item.user_id for item in matching_other_transactions if item.user_id is not None}
    accounts = db.query(User).filter(User.id.in_(other_user_ids)).all() if other_user_ids else []
    accounts_by_id = {account.id: account for account in accounts}
    new_account_ids = {
        item.user_id for item in matching_other_transactions
        if item.user_id in accounts_by_id
        and accounts_by_id[item.user_id].created_at
        and accounts_by_id[item.user_id].created_at >= since_30d
    }
    status_counts = {}
    for order in matching_orders:
        status = order.status or "UNKNOWN"
        status_counts[status] = status_counts.get(status, 0) + 1
    delivery_outcome_counts = {
        status: count for status, count in status_counts.items()
        if any(marker in status.casefold() for marker in ("cancel", "refus", "failed_delivery", "delivery_failed"))
    }
    checkout_attempts_24h = db.query(Transaction).filter(
        Transaction.user_id == transaction.user_id,
        Transaction.created_at >= since_24h,
        Transaction.id != transaction.id,
    ).count()
    customer_history = db.query(Transaction).filter(
        Transaction.user_id == transaction.user_id,
        Transaction.created_at >= since_30d,
        Transaction.id != transaction.id,
    ).order_by(Transaction.created_at.desc(), Transaction.id.desc()).limit(5000).all()
    previous_same_currency_amounts = [
        float(item.amount) for item in customer_history
        if item.currency == transaction.currency
        and item.amount is not None
        and math.isfinite(float(item.amount))
        and float(item.amount) > 0
    ]
    recorded_device_types = sorted({
        (item.transaction_data or {}).get("DeviceType")
        for item in customer_history
        if (item.transaction_data or {}).get("DeviceType") in {"desktop", "mobile"}
    })
    return {
        "address_check": {
            "format_valid": True,
            "explicit_checkout_confirmation_present": address.address_confirmed is True,
            "normalized_address_key_matches_assessed_checkout": True,
        },
        "account_history": {
            "customer_orders_last_24_hours": customer_orders_24h,
            "customer_other_checkout_attempts_last_24_hours": checkout_attempts_24h,
            "matching_address_orders_last_24_hours": matching_orders_24h,
            "matching_address_orders_last_30_days": len(matching_orders),
            "other_accounts_with_matching_checkout_address_last_30_days": len(other_user_ids),
            "other_new_accounts_with_matching_checkout_address_last_30_days": len(new_account_ids),
            "matching_address_order_status_counts": status_counts,
            "recorded_cancellation_or_delivery_failure_status_counts": delivery_outcome_counts,
            "delivery_refusal_history_available": bool(delivery_outcome_counts),
            "history_scan_limit": 5000,
            "history_scans_truncated_possible": len(scanned_orders) == 5000 or len(recent_transactions) == 5000,
            "shared_address_is_informational_only": True,
            "transaction_amount_context_last_30_days": {
                "currency": transaction.currency or "UNKNOWN",
                "current_amount": round(float(transaction.amount), 2),
                "same_currency_previous_transaction_count": len(previous_same_currency_amounts),
                "previous_minimum": round(min(previous_same_currency_amounts), 2) if previous_same_currency_amounts else None,
                "previous_median": round(statistics.median(previous_same_currency_amounts), 2) if previous_same_currency_amounts else None,
                "previous_maximum": round(max(previous_same_currency_amounts), 2) if previous_same_currency_amounts else None,
                "history_scan_limit": 5000,
                "history_scans_truncated_possible": len(customer_history) == 5000,
                "interpretation": "Same-currency customer context only; no amount cutoff or risk points are applied.",
            },
            "device_type_context_last_30_days": {
                "current_device_type": (transaction.transaction_data or {}).get("DeviceType", "UNKNOWN"),
                "previous_recorded_device_types": recorded_device_types,
                "interpretation": "Coarse account history for context; desktop/mobile changes are not treated as fraud by themselves.",
            },
        },
    }


def collect_graph_relationship_check(db, transaction, prediction):
    if not str(prediction.model_used or "").startswith("GraphSAGE"):
        return {
            "status": "NOT_USED_BY_SCORING_MODEL",
            "check_performed": True,
            "training_edge_features": [],
            "live_edge_features": [],
            "missing_edge_features": [],
            "connected_neighbors": 0,
            "topology_validation_status": "NOT_APPLICABLE",
            "note": "This transaction was scored by a non-graph model; no graph relationship evidence was used for its score.",
        }
    user = db.query(User).filter(User.id == transaction.user_id).first()
    if user is None:
        raise HTTPException(status_code=409, detail="The checkout account is unavailable for graph reassessment")
    try:
        _, context = _build_graph_for_prediction(
            transaction.transaction_data or {}, user, db,
            prediction=prediction,
            before_transaction_id=transaction.id,
        )
    except Exception as error:
        logger.exception("Graph relationship reassessment failed for transaction %s", transaction.id)
        raise HTTPException(status_code=503, detail="Graph relationship checks are temporarily unavailable; transaction remains on hold") from error
    return {
        "status": "VALIDATED" if context["topology_validation_status"] == "VALIDATED" else "INCOMPLETE_EVIDENCE",
        "check_performed": True,
        "training_edge_features": context["training_topology"].split(", ") if context["training_topology"] else [],
        "live_edge_features": context["live_topology"].split(", ") if context["live_topology"] != "No connected historical edges" else [],
        "missing_edge_features": context["missing_edge_features"],
        "connected_neighbors": context["connected_neighbors"],
        "topology_validation_status": context["topology_validation_status"],
        "note": context["topology_note"],
    }


def current_reassessment_matches(transaction, prediction):
    assessment = transaction.risk_reassessment
    if not isinstance(assessment, dict) or assessment.get("ready_for_admin_decision") is not True:
        return False
    try:
        current_address_hash = shipping_address_hash(transaction_shipping_address(transaction))
    except (HTTPException, ValidationError):
        return False
    return (
        assessment.get("checkout_attempt_id") == order_attempt_identifier(transaction)
        and assessment.get("fraud_prediction_id") == prediction.id
        and assessment.get("shipping_address_hash") == current_address_hash
        and assessment.get("score_based_decision") == score_based_decision_for(prediction)
        and assessment.get("address_account_checks", {}).get("address_check", {}).get("format_valid") is True
        and assessment.get("graph_relationship_check", {}).get("check_performed") is True
    )


def require_current_high_risk_reassessment(transaction, prediction):
    if not is_high_risk_prediction(prediction):
        return
    if not current_reassessment_matches(transaction, prediction):
        raise HTTPException(status_code=409, detail="High-risk reassessment is required and must match the confirmed checkout address before payment")
    assessment = transaction.risk_reassessment
    admin_decision = assessment.get("administrator_decision") or {}
    if (
        transaction.review_decision != "APPROVE"
        or admin_decision.get("decision") != "APPROVE"
        or admin_decision.get("reviewed_by_admin_id") != transaction.reviewed_by_admin_id
    ):
        raise HTTPException(status_code=409, detail="An explicit administrator approval after reassessment is required before payment")
    if (
        assessment.get("graph_relationship_check", {}).get("status") == "INCOMPLETE_EVIDENCE"
        and admin_decision.get("acknowledge_incomplete_graph_evidence") is not True
    ):
        raise HTTPException(status_code=409, detail="The administrator must explicitly acknowledge incomplete graph evidence before payment")


def order_otp_hash(user_id, email_address, transaction_id, attempt_id, code):
    payload = f"order:{user_id}:{email_address.strip().lower()}:{transaction_id}:{attempt_id}:{code}".encode("utf-8")
    return hmac.new(TOKEN_SECRET, payload, hashlib.sha256).hexdigest()


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
    acknowledge_incomplete_graph_evidence: bool = False

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


SUPPORTED_DEVICE_INFOS = frozenset({"Windows", "MacOS", "iOS Device", "Linux x86_64", "Android 7.0"})


def normalize_device_info(raw_info, device_type=None):
    """Normalize an observed supported value without inventing a device identity."""
    if not raw_info or not isinstance(raw_info, str):
        return "UNKNOWN"
    cleaned = raw_info.strip()
    if cleaned in SUPPORTED_DEVICE_INFOS:
        return cleaned
    lowered = cleaned.lower()
    if "win" in lowered:
        return "Windows"
    if "mac" in lowered:
        return "MacOS"
    if "ios" in lowered or "iphone" in lowered or "ipad" in lowered:
        return "iOS Device"
    if "android" in lowered:
        return "Android 7.0"
    if "linux" in lowered:
        return "Linux x86_64"
    return "UNKNOWN"


def prepare_checkout_model_features(transaction_data, current_user, checkout_snapshot=None):
    """Normalize storefront inputs to the meanings represented by the artifacts."""
    features = dict(transaction_data)
    user_email = getattr(current_user, "email", None) if current_user else None
    features["P_emaildomain"] = email_domain_for_model(user_email)
    device_type = normalize_device_type(transaction_data.get("DeviceType"))
    features["DeviceType"] = device_type
    # Browser/platform hints do not identify a device and must not become
    # shared-device graph edges for storefront checkouts.
    features["DeviceInfo"] = "UNKNOWN"
    if checkout_snapshot is not None:
        features["ProductCD"] = "UNKNOWN"
    return features


def product_cd_review_reason(transaction_data, model_name=None):
    """Return a review safeguard reason when ProductCD is unavailable or unsupported."""
    product_code = transaction_data.get("ProductCD")
    if product_code is None or not str(product_code).strip() or str(product_code).strip().upper() == "UNKNOWN":
        return "ProductCD is unavailable: no single backend-validated dataset code is available for this transaction."

    # UNKNOWN is a reserved encoder fallback, not a supported dataset value.
    if model_name and model_name.startswith("LogisticRegression"):
        supported_values = baseline_product_cd_values
        if supported_values is None:
            try:
                if artifacts_loaded:
                    categorical = baseline_pipeline.named_steps["preprocessor"].named_transformers_["cat"]
                    one_hot = categorical.named_steps["onehot"]
                    supported_values = set(one_hot.categories_[0])
            except (AttributeError, KeyError, IndexError, TypeError):
                supported_values = None
    elif model_name == "GraphSAGE_DeviceInfo_v2":
        encoder = (device_info_v2_encoders or {}).get("ProductCD")
        supported_values = set(encoder.classes_) - {"UNKNOWN"} if encoder is not None else None
    else:
        encoder = (gnn_encoders or {}).get("ProductCD")
        supported_values = set(encoder.classes_) - {"UNKNOWN"} if encoder is not None else None
    if supported_values is None:
        return "ProductCD could not be validated against the loaded model's fitted categories; administrator review is required."
    if str(product_code) not in supported_values:
        return "ProductCD is outside the fitted training categories; administrator review is required."
    return None


def checkout_feature_review_reason(transaction_data, model_name=None):
    """Describe model-input limitations without changing the score-based action."""
    reasons = []
    product_reason = product_cd_review_reason(transaction_data, model_name)
    if product_reason:
        reasons.append(product_reason)

    if model_name == "GraphSAGE":
        device_val = transaction_data.get("DeviceInfo")
        if not device_val or device_val == "UNKNOWN":
            reasons.append(
                "GraphSAGE uses its saved P_emaildomain and DeviceInfo edge schema. Checkout currently "
                "has no trustworthy DeviceInfo source, so graph topology remains unvalidated and must not be presented as validated."
            )
    elif model_name == "GraphSAGE_DeviceInfo_v2" and transaction_data.get("DeviceInfo") == "UNKNOWN":
        reasons.append(
            "The browser platform hint was missing or unsupported; DeviceInfo v2 uses UNKNOWN and creates no platform relationship edges."
        )
    elif model_name and model_name.startswith("LogisticRegression"):
        if transaction_data.get("ProductCD") is None or not str(transaction_data.get("ProductCD")).strip() or str(transaction_data.get("ProductCD")).strip().upper() == "UNKNOWN":
            reasons.append(
                "The Logistic Regression baseline was trained on historical IEEE-CIS data with class-balanced sampling; "
                "its uncalibrated probability is advisory for storefront checkout and requires administrator review."
            )
    return " ".join(reasons) or None


def prediction_review_reason(transaction_data, prediction):
    """Return the policy hold reason without presenting it as a model explanation."""
    classification = score_classification_fields(prediction)
    mismatch_notice = historical_classification_notice(prediction, classification)
    if mismatch_notice and prediction.decision == "REVIEW":
        return mismatch_notice
    if prediction.decision == "VERIFY" and classification["risk_level"] == "MEDIUM":
        return "Additional order-specific email verification is required before this transaction can continue."
    if prediction.decision != "REVIEW":
        return None
    risk_level = classification["risk_level"]
    prob = float(prediction.fraud_probability)
    reasons = []
    if risk_level == "HIGH":
        reasons.append(
            f"High-risk score ({prob:.4f}) exceeded the configured {FRAUD_BLOCK_THRESHOLD:.2f} block threshold; "
            "payment is held for administrator review."
        )
    elif risk_level == "MEDIUM":
        reasons.append(
            f"Medium-risk score ({prob:.4f} is in the medium-risk band {FRAUD_REVIEW_THRESHOLD:.2f}–{FRAUD_BLOCK_THRESHOLD:.2f}); "
            "mandatory administrator review is required before order release."
        )
    else:
        reasons.append(
            f"Low-risk score ({prob:.4f} <= {FRAUD_REVIEW_THRESHOLD:.2f}), "
            "but all checkout transactions require mandatory administrator review."
        )
    feature_safeguards = checkout_feature_review_reason(transaction_data, prediction.model_used)
    if feature_safeguards:
        reasons.append(feature_safeguards)
    return " ".join(reasons)


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
        # Storefront history has no verified device identifier provenance.
        # Do not reconstruct shared-device edges from browser/platform hints.
        row["DeviceInfo"] = "UNKNOWN"
        row["created_at"] = item.created_at
        rows.append(row)
        edge_rows.append({column: row.get(column) for column in edge_features} | {"created_at": item.created_at})

    current = {column: transaction_data.get(column) for column in features}
    current["P_emaildomain"] = email_domain_for_model(getattr(current_user, "email", None))
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


def _build_live_device_info_v2_graph(transaction_data, current_user, db, before_transaction_id=None):
    """Build v2 nodes with a coarse platform feature and no platform graph edges."""
    if not device_info_v2_loaded or not device_info_v2_metadata:
        raise RuntimeError("Versioned DeviceInfo v2 artifacts are unavailable")
    features = list(device_info_v2_metadata["input_features"])
    query = (
        db.query(Transaction, User.email)
        .outerjoin(User, Transaction.user_id == User.id)
        .filter(Transaction.transaction_data.isnot(None))
    )
    if before_transaction_id is not None:
        query = query.filter(Transaction.id < before_transaction_id)
    historical = query.order_by(Transaction.created_at.desc(), Transaction.id.desc()).limit(5000).all()
    rows, edge_rows = [], []
    for item, customer_email in reversed(historical):
        values = item.transaction_data or {}
        row = {column: values.get(column) for column in features}
        row["P_emaildomain"] = email_domain_for_model(customer_email)
        # Legacy values have no v2 source marker and are never reinterpreted.
        if values.get("DeviceInfoSource") == DEVICE_INFO_V2_SOURCE:
            row["DeviceInfo"] = normalize_browser_platform_hint(values.get("DeviceInfo"))
        else:
            row["DeviceInfo"] = "UNKNOWN"
        row["created_at"] = item.created_at
        rows.append(row)
        edge_rows.append({"P_emaildomain": row["P_emaildomain"], "created_at": row["created_at"]})

    current = {column: transaction_data.get(column) for column in features}
    current["P_emaildomain"] = email_domain_for_model(getattr(current_user, "email", None))
    current["DeviceInfo"] = normalize_browser_platform_hint(current.get("DeviceInfo"))
    current["created_at"] = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    rows.append(current)
    edge_rows.append({"P_emaildomain": current["P_emaildomain"], "created_at": current["created_at"]})

    raw = pd.DataFrame(rows)
    for column in device_info_v2_metadata["categorical_features"]:
        raw[column] = raw[column].fillna("UNKNOWN").astype(str)
    raw["TransactionAmt"] = pd.to_numeric(raw["TransactionAmt"], errors="coerce").fillna(0.0)
    processed, _, _ = select_features_and_preprocess(
        raw,
        device_info_v2_metadata["numerical_features"],
        device_info_v2_metadata["categorical_features"],
        is_train=False,
        scalers=device_info_v2_scalers,
        encoders=device_info_v2_encoders,
    )
    graph_frame = raw[["created_at"]].copy()
    for feature in features:
        graph_frame[feature] = processed[feature].to_numpy()
    graph = build_homogeneous_transaction_graph(
        graph_frame,
        features,
        ["P_emaildomain"],
        max_neighbors=int(device_info_v2_metadata.get("max_neighbors", 10)),
        edge_frame=pd.DataFrame(edge_rows),
    )
    target_idx = len(rows) - 1
    connected_neighbors = (
        int(torch.unique(graph.edge_index[0, graph.edge_index[1] == target_idx]).numel())
        if graph.edge_index.numel() else 0
    )
    validated = connected_neighbors > 0
    context = {
        "topology": "causal_transaction_graph",
        "edge_type": "P_emaildomain" if validated else "No connected historical edges",
        "training_topology": "P_emaildomain",
        "live_topology": "P_emaildomain" if validated else "No connected historical edges",
        "connected_neighbors": connected_neighbors,
        "topology_validation_status": "VALIDATED" if validated else "UNVALIDATED_INSUFFICIENT_DATA",
        "missing_edge_features": [] if validated else ["P_emaildomain"],
        "feature_order": features,
        "feature_dimensions": int(graph.x.shape[1]),
        "topology_note": (
            "DeviceInfo v2 uses the platform family as a categorical feature only. Graph edges use authenticated-account email domain; platform values never create relationships."
            if validated else
            "DeviceInfo v2 uses the platform family as a categorical feature only. No matching historical email-domain edge is available; platform values do not create relationships."
        ),
    }
    return graph, context


def _build_graph_for_prediction(transaction_data, current_user, db, prediction=None, before_transaction_id=None):
    if prediction is not None and prediction.model_used == "GraphSAGE_DeviceInfo_v2":
        return _build_live_device_info_v2_graph(
            transaction_data, current_user, db, before_transaction_id=before_transaction_id
        )
    return _build_live_gnn_graph(
        transaction_data, current_user, db, before_transaction_id=before_transaction_id
    )


def predict_with_gnn(transaction_data, current_user, db):
    """Score the new checkout node against a bounded, causal history graph."""
    if not gnn_artifacts_loaded or gnn_model is None:
        raise RuntimeError("GraphSAGE artifacts are unavailable")
    graph, _ = _build_live_gnn_graph(transaction_data, current_user, db)
    with torch.no_grad():
        logits = gnn_model(graph.x, graph.edge_index)
        probability = float(torch.sigmoid(logits[-1]).item())
    return probability


def predict_with_device_info_v2(transaction_data, current_user, db):
    if not device_info_v2_loaded or device_info_v2_model is None:
        raise RuntimeError("Versioned DeviceInfo v2 artifacts are unavailable")
    graph, _ = _build_live_device_info_v2_graph(transaction_data, current_user, db)
    with torch.no_grad():
        logits = device_info_v2_model(graph.x, graph.edge_index)
        return float(torch.sigmoid(logits[-1]).item())


def reproduce_stored_prediction_score(transaction, prediction, db=None):
    """Attempt to reproduce the stored risk score using the original model and inputs."""
    model_name = prediction.model_used or ""
    payload = transaction.transaction_data or {}

    if model_name in {"GraphSAGE", "GraphSAGE_DeviceInfo_v2"}:
        active_model = gnn_model if model_name == "GraphSAGE" else device_info_v2_model
        active_loaded = gnn_artifacts_loaded if model_name == "GraphSAGE" else device_info_v2_loaded
        if not active_loaded or active_model is None:
            return False, None, None, "The matching GraphSAGE model artifacts are not currently loaded"
        if db is None:
            return False, None, None, "Database session was not provided to reconstruct historical graph context"
        try:
            user = db.query(User).filter(User.id == transaction.user_id).first()
            graph, _ = _build_graph_for_prediction(
                payload, user, db, prediction=prediction,
                before_transaction_id=transaction.id,
            )
            with torch.no_grad():
                logits = active_model(graph.x, graph.edge_index)
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
    is_gnn = model_name.startswith("GraphSAGE")
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
    elif is_gnn:
        metadata = device_info_v2_metadata if model_name == "GraphSAGE_DeviceInfo_v2" else gnn_metadata
        if metadata is not None:
            feature_names = list(metadata.get("input_features", BASELINE_FEATURES))

    feature_values = [{"name": name, "value": payload.get(name)} for name in feature_names]
    snapshot = transaction.checkout_snapshot if isinstance(transaction.checkout_snapshot, dict) else {}
    signals = snapshot.get("verification_signals") or {}
    shipping_address = snapshot.get("shipping_address") or {}
    address_valid = False
    if shipping_address:
        try:
            OrderAddressInput(**shipping_address)
            address_valid = True
        except (TypeError, ValueError, ValidationError):
            pass
    order_challenge = None
    if db is not None:
        order_challenge = db.query(OrderVerification).filter(
            OrderVerification.transaction_id == transaction.id,
            OrderVerification.user_id == transaction.user_id,
        ).first()
    product_code = payload.get("ProductCD")
    product_warning = product_cd_review_reason(payload, prediction.model_used)
    checkout_evidence = {
        "products": snapshot.get("items", []),
        "product_cd": product_code or "UNKNOWN",
        "product_cd_validated": not bool(product_warning),
        "product_cd_warning": product_warning,
        "account_email_otp_verified": signals.get("email_otp_verified") is True,
        "address_confirmed": shipping_address.get("address_confirmed") is True,
        "address_validated": address_valid,
        "order_otp_status": order_challenge.status if order_challenge else "NOT_STARTED",
        "order_otp_verified_at": order_challenge.verified_at if order_challenge else None,
        "device_type": payload.get("DeviceType") or "UNKNOWN",
        "device_info": payload.get("DeviceInfo") or "UNKNOWN",
    }
    manual_review_reason = operational_review_reason(transaction, prediction)
    try:
        score_classification = score_classification_fields(prediction)
        score_decision = score_classification["score_based_decision"]
    except (TypeError, ValueError):
        score_classification = None
        score_decision = None

    model_version = (
        (device_info_v2_metadata if model_name == "GraphSAGE_DeviceInfo_v2" else gnn_metadata).get("model_version", "1")
        if is_gnn and (device_info_v2_metadata if model_name == "GraphSAGE_DeviceInfo_v2" else gnn_metadata)
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
        "risk_category": score_classification["risk_level"] if score_classification else prediction.risk_level,
        "recorded_risk_category": prediction.risk_level,
        "classification_consistent": score_classification["classification_consistent"] if score_classification else False,
        "model_decision": prediction.decision,
        "automated_score_decision": score_decision,
        "score_based_decision": score_decision,
        "recorded_score_based_decision": prediction.score_based_decision,
        "historical_classification_notice": historical_classification_notice(prediction, score_classification) if score_classification else None,
        "risk_reassessment": transaction.risk_reassessment,
        "checkout_evidence": checkout_evidence,
        "manual_review_reason": manual_review_reason,
        "thresholds": {
            "review": FRAUD_REVIEW_THRESHOLD,
            "block": FRAUD_BLOCK_THRESHOLD,
            "applicable_rule": (
                f"score <= {FRAUD_REVIEW_THRESHOLD:.2f}; score-based ALLOW/APPROVE"
                if score_decision == "APPROVE"
                else f"{FRAUD_REVIEW_THRESHOLD:.2f} < score <= {FRAUD_BLOCK_THRESHOLD:.2f}; score-based REVIEW"
                if score_decision == "REVIEW"
                else f"score > {FRAUD_BLOCK_THRESHOLD:.2f}; score-based BLOCK"
            ),
        },
        "features": feature_values,
        "feature_provenance": {
            "TransactionAmt": (
                "Server-validated catalogue total for storefront checkout."
                if isinstance(transaction.checkout_snapshot, dict) and "items" in transaction.checkout_snapshot
                else "Value supplied in the transaction request."
            ),
            "ProductCD": (
                "UNKNOWN: the checkout has no single backend-validated ProductCD code."
                if payload.get("ProductCD") == "UNKNOWN"
                else "Validated product category code mapped from the checkout catalog."
            ),
            "P_emaildomain": "Derived by the backend from the authenticated account email; not trusted from the client request.",
            "DeviceType": "Coarse desktop/mobile value from the checkout client and normalized by the backend; not a unique device identity.",
            "DeviceInfo": (
                "DeviceInfo v2 is a coarse, client-reported OS-family hint. It is a categorical input only and never creates graph edges or proves device identity."
                if model_name == "GraphSAGE_DeviceInfo_v2" and payload.get("DeviceInfo") != "UNKNOWN"
                else "UNKNOWN: the browser platform hint was unavailable or unsupported; no platform relationship edge is inferred."
                if model_name == "GraphSAGE_DeviceInfo_v2"
                else "UNKNOWN: no trustworthy value compatible with the original training feature is collected; no relationship edge is inferred."
                if payload.get("DeviceInfo") == "UNKNOWN"
                else "The stored value is not independently verified and is not used to establish a live device identity."
            ),
        },
        "operational_decision": operational_decision_for(db, transaction, prediction),
        "original_operational_decision": prediction.decision,
        "manual_decision": transaction.review_decision,
        "reviewed_at": transaction.reviewed_at,
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
            "reviewed_by_admin_id": transaction.reviewed_by_admin_id,
            "reviewed_at": transaction.reviewed_at,
            "reason": transaction.review_reason,
            "risk_reassessment": transaction.risk_reassessment,
        },
    }

    if is_gnn:
        try:
            user = db.query(User).filter(User.id == transaction.user_id).first() if db is not None else None
            if db is None:
                raise RuntimeError("Database session was not provided")
            _, graph_context = _build_graph_for_prediction(
                payload, user, db, prediction=prediction,
                before_transaction_id=transaction.id,
            )
            graph_context["stored_score_reproduced"] = matches_score
            if not matches_score:
                graph_context["topology_validation_status"] = "UNVALIDATED_STORED_SCORE_MISMATCH"
                graph_context["topology_note"] += (
                    " The reconstructed graph does not reproduce this stored score, so the original "
                    "prediction's exact inference graph cannot be validated from persisted data."
                )
        except Exception as error:
            error_text = str(error)
            topology_mismatch = "schema" in error_text.lower() or "incompatible" in error_text.lower()
            graph_context = {
                "topology": "causal_transaction_graph",
                "edge_type": "Unavailable",
                "training_topology": ", ".join(
                    (device_info_v2_metadata if model_name == "GraphSAGE_DeviceInfo_v2" else gnn_metadata).get("edge_features", [])
                ) if (device_info_v2_metadata if model_name == "GraphSAGE_DeviceInfo_v2" else gnn_metadata) else "Unavailable",
                "live_topology": "Unavailable",
                "connected_neighbors": None,
                "topology_validation_status": "UNVALIDATED_TOPOLOGY_MISMATCH" if topology_mismatch else "UNVALIDATED_VALIDATION_ERROR",
                "missing_edge_features": [],
                "topology_note": f"Live graph context could not be reconstructed: {error_text}",
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
        if PRIMARY_FRAUD_MODEL == "gnn_device_v2":
            return predict_with_device_info_v2(transaction_data, current_user, db), "GraphSAGE_DeviceInfo_v2"
        return predict_with_gnn(transaction_data, current_user, db), "GraphSAGE"
    except Exception:
        logger.exception("Configured GraphSAGE prediction failed")
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
    active_loaded = (
        gnn_artifacts_loaded if PRIMARY_FRAUD_MODEL == "gnn"
        else device_info_v2_loaded if PRIMARY_FRAUD_MODEL == "gnn_device_v2"
        else artifacts_loaded
    )
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
    return FAKESTORE_CATALOG + SAMPLE_CATALOG

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
    active_model_loaded = (
        gnn_artifacts_loaded if PRIMARY_FRAUD_MODEL == "gnn"
        else device_info_v2_loaded if PRIMARY_FRAUD_MODEL == "gnn_device_v2"
        else artifacts_loaded
    )
    if not active_model_loaded:
        raise HTTPException(status_code=500, detail="Configured fraud model artifacts are not loaded.")
        
    try:
        transaction_data = transaction.model_dump(exclude={"checkout_attempt_id", "checkout_snapshot"})
        device_platform_hint = transaction_data.pop("DevicePlatformHint", None)
        checkout_snapshot = enrich_checkout_snapshot(transaction.checkout_snapshot)
        email_verification = None
        if checkout_snapshot is not None and "items" in checkout_snapshot:
            email_verification = require_verified_email(db, current_user)
            checkout_snapshot["verified_email"] = (current_user.email or "").strip().lower()
        elif checkout_snapshot and checkout_snapshot.get("verified_email"):
            require_verified_email(db, current_user)
            checkout_snapshot["verified_email"] = (current_user.email or "").strip().lower()
        transaction_data = prepare_checkout_model_features(
            transaction_data, current_user,
            checkout_snapshot if checkout_snapshot and "items" in checkout_snapshot else None,
        )
        if PRIMARY_FRAUD_MODEL == "gnn_device_v2":
            normalized_platform = normalize_browser_platform_hint(device_platform_hint)
            transaction_data["DeviceInfo"] = normalized_platform
            transaction_data["DeviceInfoSource"] = (
                DEVICE_INFO_V2_SOURCE if normalized_platform != "UNKNOWN" else "unknown"
            )
        if checkout_snapshot is not None and "items" in checkout_snapshot:
            _, priced_items, trusted_total = validate_checkout_items(checkout_snapshot.get("items"))
            trusted_product_codes = {item["ProductCD"] for item in priced_items}
            if len(trusted_product_codes) == 1:
                single_code = next(iter(trusted_product_codes))
                transaction_data["ProductCD"] = single_code if single_code in {"C", "H", "R", "S", "W"} else "UNKNOWN"
            else:
                transaction_data["ProductCD"] = "UNKNOWN"
            if not math.isclose(trusted_total, round(transaction.TransactionAmt, 2), abs_tol=0.01):
                raise HTTPException(status_code=409, detail="Cart total changed; restart fraud verification")
            try:
                shipping_address = checkout_snapshot.get("shipping_address", {})
                OrderAddressInput(**shipping_address)
                OrderAddressInput(**checkout_snapshot.get("billing_address", {}))
            except ValidationError as error:
                raise HTTPException(status_code=422, detail="Complete both checkout addresses with valid six-digit Indian PIN codes") from error
            if shipping_address.get("address_confirmed") is not True:
                raise HTTPException(status_code=422, detail="Confirm the delivery address before fraud assessment")
            checkout_snapshot["verification_signals"] = {
                "email_otp_verified": bool(email_verification and email_verification.verified_at),
                "email_verified_at": email_verification.verified_at.isoformat() if email_verification and email_verification.verified_at else None,
                "delivery_address_confirmed": True,
            }
            transaction_data["TransactionAmt"] = trusted_total
        if transaction.checkout_attempt_id:
            existing = db.query(Transaction).filter(
                Transaction.checkout_attempt_id == transaction.checkout_attempt_id
            ).first()
            if existing is not None:
                if (
                    existing.user_id != current_user.id
                    or existing.transaction_data != transaction_data
                    or stable_checkout_snapshot(existing.checkout_snapshot) != stable_checkout_snapshot(checkout_snapshot)
                ):
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
                    score_based_decision=score_based_decision_for(existing_prediction),
                    model_used=existing_prediction.model_used,
                    review_reason=(
                        prediction_review_reason(existing.transaction_data or {}, existing_prediction)
                    ),
                )
        fraud_prob, model_name = score_transaction(transaction_data, current_user, db)
        score_based_decision = classify_fraud_score(fraud_prob)[1]
        verification_signals = (checkout_snapshot or {}).get("verification_signals", {})
        risk_level, score_decision = (
            classify_checkout_score(fraud_prob, verification_signals)
            if checkout_snapshot is not None and "items" in checkout_snapshot
            else classify_fraud_score(fraud_prob)
        )
        product_review_reason = product_cd_review_reason(transaction_data, model_name)
        fallback_review_reason = (
            "GraphSAGE inference failed and the configured Logistic Regression fallback was used; "
            "administrator review is required."
            if model_name.endswith("_Fallback") else None
        )
        fail_closed_reason = product_review_reason or fallback_review_reason
        feature_safeguards = checkout_feature_review_reason(transaction_data, model_name)
        decision = "REVIEW"

        reasons = []
        if risk_level == "HIGH":
            reasons.append(
                f"High-risk score ({round(fraud_prob, 4):.4f}) exceeded the configured {FRAUD_BLOCK_THRESHOLD:.2f} block threshold; "
                "payment is held for administrator review."
            )
        elif risk_level == "MEDIUM":
            reasons.append(
                f"Medium-risk score ({round(fraud_prob, 4):.4f} is in the medium-risk band {FRAUD_REVIEW_THRESHOLD:.2f}–{FRAUD_BLOCK_THRESHOLD:.2f}); "
                "mandatory administrator review is required before order release."
            )
        else:
            reasons.append(
                f"Low-risk score ({round(fraud_prob, 4):.4f} <= {FRAUD_REVIEW_THRESHOLD:.2f}), "
                "but all checkout transactions require mandatory administrator review."
            )

        if fail_closed_reason:
            reasons.append(fail_closed_reason)
        elif feature_safeguards:
            reasons.append(feature_safeguards)

        review_reason = " ".join(reasons)

        # Store in database
        db_tx = Transaction(
            user_id=current_user.id,
            amount=transaction_data["TransactionAmt"],
            transaction_data=transaction_data,
            checkout_snapshot=checkout_snapshot,
            checkout_attempt_id=transaction.checkout_attempt_id,
            status="REVIEW",
        )
        db.add(db_tx)
        db.flush()

        db_pred = FraudPrediction(
            transaction_id=db_tx.id,
            fraud_probability=fraud_prob,
            risk_level=risk_level,
            decision=decision,
            score_based_decision=score_based_decision,
            model_used=model_name,
        )
        db.add(db_pred)
        db.flush()
        db.commit()

        return PredictionResponse(
            transaction_id=db_tx.id,
            fraud_probability=fraud_prob,
            risk_level=risk_level,
            decision=decision,
            score_based_decision=score_based_decision,
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
                        score_based_decision=score_based_decision_for(existing_prediction),
                        model_used=existing_prediction.model_used,
                        review_reason=(
                            prediction_review_reason(existing.transaction_data or {}, existing_prediction)
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
        "payment_method": order.payment_method,
        "transactionId": order.transaction_id,
        "transaction_id": order.transaction_id,
        "amount": order.amount,
        "currency": order.currency,
        "items": order.items,
        "shipping_address": order.shipping_address,
        "billing_address": order.billing_address,
    }


def get_owned_order_transaction(transaction_id, db, current_user):
    transaction = db.query(Transaction).filter(
        Transaction.id == transaction_id,
        Transaction.user_id == current_user.id,
    ).with_for_update().first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return transaction


@app.get("/api/orders/{transaction_id}/verification")
def get_order_verification_status(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    transaction = get_owned_order_transaction(transaction_id, db, current_user)
    existing_order = db.query(Order).filter(Order.transaction_id == transaction.id).first()
    if existing_order is not None:
        prediction = db.query(FraudPrediction).filter(
            FraudPrediction.transaction_id == transaction.id
        ).order_by(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()).first()
        return {
            "status": "complete",
            "transaction_id": transaction.id,
            "order_id": existing_order.id,
            "address_confirmed": True,
            "verified": True,
            "transaction_status": transaction.status,
            "review_decision": transaction.review_decision,
            "operational_decision": operational_decision_for(db, transaction, prediction) if prediction else None,
        }

    challenge = db.query(OrderVerification).filter(
        OrderVerification.transaction_id == transaction.id,
        OrderVerification.user_id == current_user.id,
    ).first()
    if challenge is None:
        return {"status": "not_started", "address_confirmed": False, "verified": False}

    now = datetime.datetime.utcnow()
    if challenge.expires_at <= now and challenge.status in {"PENDING", "VERIFIED"}:
        challenge.status = "EXPIRED"
        challenge.code_hash = None
        db.commit()
    try:
        current_address_hash = shipping_address_hash(transaction_shipping_address(transaction))
    except (HTTPException, ValidationError):
        current_address_hash = None
    address_confirmed = bool(
        challenge.address_confirmed_at
        and challenge.shipping_address_hash == current_address_hash
    )
    verified = challenge.status == "VERIFIED" and challenge.expires_at > now and address_confirmed
    prediction = db.query(FraudPrediction).filter(
        FraudPrediction.transaction_id == transaction.id
    ).order_by(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()).first()
    admin_approved = bool(
        transaction.status in {"REVIEW_APPROVED", "ORDERED"}
        and transaction.review_decision == "APPROVE"
    )
    checkout_released = bool(admin_approved or (prediction and current_medium_release_matches(db, transaction, prediction)))
    return {
        "status": challenge.status.lower(),
        "address_confirmed": address_confirmed,
        "verified": verified,
        "operational_decision": operational_decision_for(db, transaction, prediction) if prediction else None,
        "transaction_status": transaction.status,
        "review_decision": transaction.review_decision,
        "checkout_released": checkout_released,
        "expires_in_seconds": max(0, int((challenge.expires_at - now).total_seconds())) if challenge.status == "PENDING" else 0,
        "resend_after_seconds": max(0, int((challenge.resend_after - now).total_seconds())),
    }


@app.post("/api/orders/{transaction_id}/verification/send")
def send_order_verification(
    transaction_id: int,
    request: OrderVerificationSendRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    transaction = get_owned_order_transaction(transaction_id, db, current_user)
    if db.query(Order).filter(Order.transaction_id == transaction.id).first() is not None:
        return {"status": "complete"}
    if request.address_confirmed is not True:
        raise HTTPException(status_code=409, detail="Explicitly confirm the delivery address before requesting an order code")
    require_verified_email(db, current_user)
    approved_transaction_prediction(db, transaction, allow_medium_challenge=True)

    snapshot_address = transaction_shipping_address(transaction)
    requested_address_hash = shipping_address_hash(request.shipping_address)
    snapshot_address_hash = shipping_address_hash(snapshot_address)
    if not snapshot_address.address_confirmed or requested_address_hash != snapshot_address_hash:
        raise HTTPException(status_code=409, detail="The address differs from the assessed checkout. Return to checkout and reassess the address before ordering.")

    # Locking the user row serializes the account-wide send limit across distinct checkout attempts.
    locked_user = db.query(User).filter(User.id == current_user.id).with_for_update().one()
    email_address = (locked_user.email or "").strip().lower()
    attempt_id = order_attempt_identifier(transaction)
    now = datetime.datetime.utcnow()
    challenge = db.query(OrderVerification).filter(
        OrderVerification.transaction_id == transaction.id
    ).with_for_update().first()

    if challenge is not None and (
        challenge.user_id != locked_user.id
        or challenge.checkout_attempt_id != attempt_id
        or challenge.email_address != email_address
        or challenge.shipping_address_hash != snapshot_address_hash
    ):
        raise HTTPException(status_code=409, detail="Order verification does not match this checkout; restart checkout")
    prediction = db.query(FraudPrediction).filter(
        FraudPrediction.transaction_id == transaction.id
    ).order_by(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()).first()
    medium_reverification = bool(
        prediction
        and prediction.risk_level == "MEDIUM"
        and prediction.decision == "VERIFY"
        and transaction.status == "APPROVED"
        and not current_medium_release_matches(db, transaction, prediction)
    )
    if challenge is not None and challenge.status == "VERIFIED" and challenge.expires_at > now and not medium_reverification:
        return {"status": "verified", "expires_in_seconds": int((challenge.expires_at - now).total_seconds())}
    if challenge is not None and challenge.status == "PENDING" and challenge.expires_at > now and challenge.resend_after > now:
        seconds = max(1, int((challenge.resend_after - now).total_seconds()))
        raise HTTPException(status_code=429, detail=f"Please wait {seconds} seconds before requesting another order code")

    if locked_user.order_otp_window_started_at is None or locked_user.order_otp_window_started_at + ORDER_OTP_SEND_WINDOW <= now:
        locked_user.order_otp_window_started_at = now
        locked_user.order_otp_sends_in_window = 0
    if locked_user.order_otp_sends_in_window >= ORDER_OTP_MAX_SENDS_PER_USER_WINDOW:
        raise HTTPException(status_code=429, detail="Order verification email limit reached. Try again later")

    if challenge is not None and challenge.window_started_at + ORDER_OTP_SEND_WINDOW <= now:
        challenge.window_started_at = now
        challenge.sends_in_window = 0
    if challenge is not None and challenge.sends_in_window >= ORDER_OTP_MAX_SENDS_PER_ATTEMPT:
        raise HTTPException(status_code=429, detail="Order verification resend limit reached. Restart checkout to try again")

    code = f"{secrets.randbelow(1_000_000):06d}"
    if medium_reverification:
        transaction.status = "VERIFY"
        reassessment = dict(transaction.risk_reassessment or {})
        reassessment.pop("medium_verification_release", None)
        medium_state = dict(reassessment.get("medium_verification") or {})
        medium_state.update({"status": "REQUIRED", "reverification_started_at": now.isoformat()})
        reassessment["medium_verification"] = medium_state
        transaction.risk_reassessment = reassessment
    if challenge is None:
        challenge = OrderVerification(
            transaction_id=transaction.id,
            user_id=locked_user.id,
            checkout_attempt_id=attempt_id,
            email_address=email_address,
            shipping_address_hash=snapshot_address_hash,
            address_confirmed_at=now,
            code_hash=order_otp_hash(locked_user.id, email_address, transaction.id, attempt_id, code),
            status="PENDING",
            created_at=now,
            expires_at=now + ORDER_OTP_TTL,
            resend_after=now + ORDER_OTP_RESEND_COOLDOWN,
            attempts=0,
            sends_in_window=1,
            window_started_at=now,
        )
        db.add(challenge)
    else:
        challenge.email_address = email_address
        challenge.shipping_address_hash = snapshot_address_hash
        challenge.address_confirmed_at = now
        challenge.code_hash = order_otp_hash(locked_user.id, email_address, transaction.id, attempt_id, code)
        challenge.status = "PENDING"
        challenge.created_at = now
        challenge.expires_at = now + ORDER_OTP_TTL
        challenge.resend_after = now + ORDER_OTP_RESEND_COOLDOWN
        challenge.sends_in_window += 1
        challenge.attempts = 0
        challenge.verified_at = None
        challenge.used_at = None
    locked_user.order_otp_sends_in_window = (locked_user.order_otp_sends_in_window or 0) + 1
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(status_code=409, detail="An order verification request is already being processed") from error
    except Exception as error:
        db.rollback()
        logger.exception("Order verification challenge persistence failed")
        raise HTTPException(status_code=503, detail="Could not start order verification; please retry") from error

    try:
        email_otp.send_code(email_address, code)
    except Exception as error:
        challenge.status = "FAILED"
        challenge.code_hash = None
        try:
            db.commit()
        except Exception:
            db.rollback()
            logger.error("Could not invalidate an undelivered order verification challenge")
        if isinstance(error, email_otp.DeliveryError):
            raise HTTPException(status_code=503, detail=str(error)) from error
        logger.error("Order verification email delivery failed")
        raise HTTPException(status_code=503, detail="Order verification email delivery failed. Try again later") from error
    return {
        "status": "pending",
        "expires_in_seconds": int(ORDER_OTP_TTL.total_seconds()),
        "resend_after_seconds": int(ORDER_OTP_RESEND_COOLDOWN.total_seconds()),
    }


def reassess_medium_after_order_otp(db, transaction, challenge):
    """Re-evaluate policy gates after order OTP without changing the stored model score."""
    prediction = db.query(FraudPrediction).filter(
        FraudPrediction.transaction_id == transaction.id
    ).order_by(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()).first()
    if prediction is None:
        raise HTTPException(status_code=409, detail="Fraud assessment is required before continuing")
    if prediction.decision not in {"REVIEW", "VERIFY"}:
        return {
            "status": "verified",
            "checkout_released": False,
            "operational_decision": prediction.decision,
        }
    admin_approved_review = (
        transaction.status in {"REVIEW_APPROVED", "ORDERED"}
        and transaction.review_decision == "APPROVE"
    )
    if transaction.status not in {"REVIEW", "VERIFY"} and not admin_approved_review:
        raise HTTPException(status_code=409, detail="This checkout is no longer awaiting verification")

    now = datetime.datetime.utcnow()
    attempt_id = order_attempt_identifier(transaction)
    address = transaction_shipping_address(transaction)
    address_hash = shipping_address_hash(address)
    verified_email = (transaction.checkout_snapshot or {}).get("verified_email", "")
    if (
        address.address_confirmed is not True
        or challenge.status != "VERIFIED"
        or challenge.verified_at is None
        or challenge.expires_at <= now
        or challenge.checkout_attempt_id != attempt_id
        or challenge.shipping_address_hash != address_hash
        or challenge.email_address != verified_email
    ):
        raise HTTPException(status_code=409, detail="Fresh order verification and the confirmed delivery address are required")
    account = db.query(User).filter(User.id == transaction.user_id).first()
    if account is None or verified_email != (account.email or "").strip().lower():
        raise HTTPException(status_code=409, detail="The verified account email no longer matches this checkout")
    require_verified_email(db, account)

    try:
        risk_level, score_outcome = classify_fraud_score(float(prediction.fraud_probability))
    except (TypeError, ValueError):
        raise HTTPException(status_code=409, detail="The stored fraud score is invalid; checkout remains held")
    if (
        prediction.risk_level != risk_level
        or score_outcome != score_based_decision_for(prediction)
    ):
        raise HTTPException(status_code=409, detail="The stored assessment no longer matches the configured risk policy")

    if admin_approved_review:
        return {
            "status": "verified",
            "checkout_released": True,
            "operational_decision": "ADMIN_APPROVE",
            "transaction_status": transaction.status,
            "risk_level": prediction.risk_level,
            "fraud_probability": prediction.fraud_probability,
            "score_based_decision": score_based_decision_for(prediction),
        }

    address_checks = collect_address_account_history(db, transaction, address)
    graph_check = collect_graph_relationship_check(db, transaction, prediction)
    delivery_history_hold = medium_requires_targeted_review(address_checks)
    failure_statuses = (
        address_checks.get("account_history", {}).get("recorded_cancellation_or_delivery_failure_status_counts", {})
    )
    if delivery_history_hold:
        hold_detail = ", ".join(
            f"{status} ({count})" for status, count in sorted(failure_statuses.items())
            if type(count) is int and count > 0
        )
        decision_reason = (
            f"Matching-address delivery outcome history requires administrator review: {hold_detail}. "
            "This history is contextual evidence and is not proof of fraud."
        )
    else:
        decision_reason = (
            "The original model score remains unchanged; required account, address, order OTP, "
            "and available evidence checks completed. Mandatory administrator review is required."
        )
    assessment = dict(transaction.risk_reassessment or {})
    assessment["medium_verification"] = {
        **(assessment.get("medium_verification") or {}),
        "status": "HELD_FOR_ADMIN_REVIEW" if delivery_history_hold else "COMPLETED",
        "required_check": "ORDER_SPECIFIC_EMAIL_OTP_AND_EVIDENCE_REASSESSMENT",
        "checkout_attempt_id": attempt_id,
        "shipping_address_hash": address_hash,
        "transaction_features_hash": transaction_features_hash(transaction),
        "fraud_prediction_id": prediction.id,
        "score": prediction.fraud_probability,
        "score_based_decision": score_based_decision_for(prediction),
        "original_operational_decision": prediction.decision,
        "reassessed_at": now.isoformat(),
        "order_otp_verified_at": challenge.verified_at.isoformat(),
        "address_account_checks": address_checks,
        "graph_relationship_check": graph_check,
        "score_adjustment": None,
        "decision_reason": decision_reason,
    }
    assessment.update({
        "version": 1,
        "ready_for_admin_decision": True,
        "assessed_at": now.isoformat(),
        "assessed_by_admin_id": None,
        "checkout_attempt_id": attempt_id,
        "shipping_address_hash": address_hash,
        "fraud_prediction_id": prediction.id,
        "score": prediction.fraud_probability,
        "score_based_decision": score_based_decision_for(prediction),
        "operational_decision": "REVIEW",
        "risk_level": prediction.risk_level,
        "model_used": prediction.model_used,
        "thresholds": {"review": FRAUD_REVIEW_THRESHOLD, "block": FRAUD_BLOCK_THRESHOLD},
        "address_account_checks": address_checks,
        "graph_relationship_check": graph_check,
        "automatic_decision_changed": False,
    })
    assessment.pop("medium_verification_release", None)
    transaction.risk_reassessment = assessment
    transaction.status = "REVIEW"
    try:
        db.commit()
    except Exception as error:
        db.rollback()
        logger.exception("Medium-risk reassessment persistence failed")
        raise HTTPException(status_code=503, detail="Verification was received but reassessment could not be saved; checkout remains held") from error
    return {
        "status": "verified",
        "checkout_released": False,
        "review_required": True,
        "operational_decision": "REVIEW",
        "transaction_status": "REVIEW",
        "risk_level": prediction.risk_level,
        "fraud_probability": prediction.fraud_probability,
        "score_based_decision": score_based_decision_for(prediction),
    }


@app.post("/api/orders/{transaction_id}/verification/verify")
def verify_order_verification(
    transaction_id: int,
    request: OrderVerificationCodeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    transaction = get_owned_order_transaction(transaction_id, db, current_user)
    if db.query(Order).filter(Order.transaction_id == transaction.id).first() is not None:
        return {"status": "complete"}
    challenge = db.query(OrderVerification).filter(
        OrderVerification.transaction_id == transaction.id,
        OrderVerification.user_id == current_user.id,
    ).with_for_update().first()
    now = datetime.datetime.utcnow()
    attempt_id = order_attempt_identifier(transaction)
    email_address = (current_user.email or "").strip().lower()
    if challenge is None or challenge.checkout_attempt_id != attempt_id or challenge.email_address != email_address:
        raise HTTPException(status_code=409, detail="Request an order verification code for this checkout")
    try:
        current_address_hash = shipping_address_hash(transaction_shipping_address(transaction))
    except (HTTPException, ValidationError):
        current_address_hash = None
    if not challenge.address_confirmed_at or challenge.shipping_address_hash != current_address_hash:
        challenge.status = "ADDRESS_CHANGED"
        challenge.code_hash = None
        db.commit()
        raise HTTPException(status_code=409, detail="The delivery address changed. Reassess checkout and request a new order code")
    if challenge.status == "VERIFIED" and challenge.expires_at > now:
        return reassess_medium_after_order_otp(db, transaction, challenge)
    if challenge.status != "PENDING" or challenge.code_hash is None:
        raise HTTPException(status_code=409, detail="Request a new order verification code")
    if challenge.expires_at <= now:
        challenge.status = "EXPIRED"
        challenge.code_hash = None
        db.commit()
        raise HTTPException(status_code=410, detail="Order verification code expired. Request a new code")
    if challenge.attempts >= ORDER_OTP_MAX_ATTEMPTS:
        challenge.status = "LOCKED"
        challenge.code_hash = None
        db.commit()
        raise HTTPException(status_code=429, detail="Too many incorrect order codes. Request a new code")

    challenge.attempts += 1
    approved = hmac.compare_digest(
        challenge.code_hash,
        order_otp_hash(current_user.id, email_address, transaction.id, attempt_id, request.code),
    )
    if approved:
        challenge.status = "VERIFIED"
        challenge.verified_at = now
        challenge.code_hash = None
    elif challenge.attempts >= ORDER_OTP_MAX_ATTEMPTS:
        challenge.status = "LOCKED"
        challenge.code_hash = None
    try:
        db.commit()
    except Exception as error:
        db.rollback()
        logger.exception("Order verification result persistence failed")
        raise HTTPException(status_code=503, detail="Could not save order verification; please retry") from error
    if not approved:
        if challenge.status == "LOCKED":
            raise HTTPException(status_code=429, detail="Too many incorrect order codes. Request a new code")
        raise HTTPException(status_code=400, detail="Invalid order verification code. Check the code and try again")
    return reassess_medium_after_order_otp(db, transaction, challenge)

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
    admin_approved_review = (
        transaction.status in {"REVIEW_APPROVED", "ORDERED"}
        and transaction.review_decision == "APPROVE"
    )
    if not admin_approved_review:
        raise HTTPException(status_code=409, detail="This transaction is not approved for payment")
    require_current_high_risk_reassessment(transaction, prediction)

    # Once captured, the backend snapshot is authoritative for resumed checkout.
    # Legacy transactions without snapshots continue to use the validated request.
    snapshot = transaction.checkout_snapshot
    if snapshot and "items" in snapshot:
        try:
            items = [OrderItemRequest(**item) for item in snapshot["items"]]
            shipping_address = OrderAddressInput(**snapshot["shipping_address"])
            billing_address = OrderAddressInput(**snapshot["billing_address"])
            # Payment methods are selected by the customer and are not fraud
            # model inputs. CreateOrderRequest validates the current selection.
            payment_method = request.payment_method
        except (KeyError, TypeError, ValueError, ValidationError) as error:
            raise HTTPException(status_code=409, detail="Saved checkout details are incomplete; start a new checkout") from error
    else:
        raise HTTPException(status_code=409, detail="Order verification requires a saved checkout address; restart checkout")

    challenge = db.query(OrderVerification).filter(
        OrderVerification.transaction_id == transaction.id,
        OrderVerification.user_id == current_user.id,
    ).with_for_update().first()
    now = datetime.datetime.utcnow()
    attempt_id = order_attempt_identifier(transaction)
    address_hash = shipping_address_hash(shipping_address)
    if (
        challenge is None
        or challenge.status != "VERIFIED"
        or challenge.verified_at is None
        or challenge.expires_at <= now
        or challenge.checkout_attempt_id != attempt_id
        or challenge.email_address != current_email
        or challenge.shipping_address_hash != address_hash
        or challenge.address_confirmed_at is None
    ):
        raise HTTPException(status_code=403, detail="Complete a fresh order email verification for this checkout before ordering")

    items, priced_items, total = validate_checkout_items(items)
    if not math.isclose(total, round(transaction.amount, 2), abs_tol=0.01):
        raise HTTPException(status_code=409, detail="Cart total changed; restart fraud verification")

    snapshot["payment_method"] = payment_method
    transaction.checkout_snapshot = snapshot
    order = Order(
        user_id=current_user.id,
        transaction_id=transaction.id,
        items=priced_items,
        shipping_address=shipping_address.model_dump(exclude_unset=True),
        billing_address=billing_address.model_dump(exclude_unset=True),
        amount=total,
        currency=transaction.currency or "USD",
        status="PROCESSING",
        payment_status="PENDING_CASH_COLLECTION" if payment_method == "COD" else "SIMULATED",
        payment_method=payment_method,
    )
    transaction.status = "ORDERED"
    challenge.status = "USED"
    challenge.used_at = now
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
    current_operational_decision = operational_decision_for(db, transaction, prediction) if prediction else None
    return {
        "transaction_id": transaction.id,
        "status": transaction.status,
        "operational_decision": current_operational_decision,
        "review_decision": transaction.review_decision,
        "reviewed_by_admin_id": transaction.reviewed_by_admin_id,
        "reviewed_at": transaction.reviewed_at,
        "review_reason": transaction.review_reason,
        "checkout_snapshot": transaction.checkout_snapshot,
        "risk_reassessment": transaction.risk_reassessment,
        "fraud_prediction": (
            {
                "fraud_probability": prediction.fraud_probability,
                **score_classification_fields(prediction),
                "decision": prediction.decision,
                "operational_decision": current_operational_decision,
                "manual_decision": transaction.review_decision,
                "model_used": prediction.model_used,
                "review_reason": (
                    historical_classification_notice(prediction)
                    if not score_classification_fields(prediction)["classification_consistent"]
                    and transaction.status == "REVIEW" and not transaction.review_decision
                    else operational_review_reason(transaction, prediction)
                ),
                "administrator_reason": transaction.review_reason,
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
            FraudPrediction.score_based_decision.label("score_based_decision"),
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
        score_classification = score_classification_fields(pred)
        review_reason = operational_review_reason(transaction, pred)
        if not score_classification["classification_consistent"] and transaction.status == "REVIEW" and not transaction.review_decision:
            review_reason = historical_classification_notice(pred, score_classification)
        results.append({
            "id": pred.id,
            "transaction_id": pred.transaction_id,
            "fraud_probability": pred.fraud_probability,
            **score_classification,
            "decision": pred.decision,
            "operational_decision": operational_decision_for(db, transaction, pred),
            "model_used": pred.model_used,
            "created_at": pred.created_at,
            "status": transaction.status,
            "review_decision": transaction.review_decision,
            "reviewed_at": transaction.reviewed_at,
            "risk_reassessment": transaction.risk_reassessment,
            "review_reason": review_reason,
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
            FraudPrediction.fraud_probability.label("fraud_probability"),
            FraudPrediction.decision.label("decision"),
            func.row_number().over(
                partition_by=FraudPrediction.transaction_id,
                order_by=(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()),
            ).label("row_number"),
        )
        .subquery()
    )
    latest_predictions = db.query(ranked_predictions).filter(ranked_predictions.c.row_number == 1).subquery()
    latest_records = (
        db.query(
            latest_predictions.c.fraud_probability,
            latest_predictions.c.decision,
            Transaction.status,
            Transaction.review_decision,
        )
        .join(Transaction, Transaction.id == latest_predictions.c.transaction_id)
        .all()
    )
    risk_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0}
    outcome_counts = {"APPROVE": 0, "REVIEW": 0, "BLOCK": 0}
    status_counts = {
        "approved": 0,
        "pending_review": 0,
        "blocked": 0,
        "admin_rejected": 0,
        "auto_approved": 0,
        "admin_approved": 0,
    }
    for fraud_probability, original_decision, transaction_status, review_decision in latest_records:
        risk_level, score_outcome = classify_fraud_score(float(fraud_probability))
        risk_counts[risk_level] += 1
        outcome_counts[score_outcome] += 1
        if transaction_status in {"APPROVED", "REVIEW_APPROVED", "ORDERED"}:
            status_counts["approved"] += 1
            if review_decision == "APPROVE":
                status_counts["admin_approved"] += 1
            elif original_decision == "APPROVE":
                status_counts["auto_approved"] += 1
        elif transaction_status == "REVIEW" and not review_decision:
            status_counts["pending_review"] += 1
        elif transaction_status == "BLOCKED":
            status_counts["blocked"] += 1
        if transaction_status == "REJECTED" or review_decision == "REJECT":
            status_counts["admin_rejected"] += 1
    total = len(latest_records)
    rates = {
        "auto_approval": status_counts["auto_approved"] / total if total else 0.0,
        "manual_review_queue": status_counts["pending_review"] / total if total else 0.0,
        "automated_prevention": status_counts["blocked"] / total if total else 0.0,
    }
    
    active_serving_model = {
        "gnn": "GraphSAGE v1",
        "gnn_device_v2": "GraphSAGE DeviceInfo v2",
        "logistic_regression": "Logistic Regression",
    }[PRIMARY_FRAUD_MODEL]
    return {
        "total_predictions": total,
        "risk_breakdown": risk_counts,
        "score_outcome_breakdown": outcome_counts,
        "transaction_status_breakdown": status_counts,
        "transaction_status_rates": rates,
        "active_model": active_serving_model,
        "primary_model": PRIMARY_FRAUD_MODEL,
        "gnn_loaded": gnn_artifacts_loaded,
        "device_info_v2_loaded": device_info_v2_loaded,
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
            FraudPrediction.score_based_decision.label("score_based_decision"),
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
        db.query(
            Transaction,
            User,
            LatestPrediction,
            Order.id.label("order_id"),
        )
        .outerjoin(User, Transaction.user_id == User.id)
        .outerjoin(LatestPrediction, and_(
            LatestPrediction.transaction_id == Transaction.id,
            ranked_predictions.c.row_number == 1,
        ))
        .outerjoin(Order, Order.transaction_id == Transaction.id)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .all()
    )

    results = []
    for transaction, customer, prediction, order_id in rows:
        result = {
            "transaction_id": transaction.id,
            "amount": transaction.amount,
            "currency": transaction.currency,
            "status": transaction.status,
            "review_decision": transaction.review_decision,
            "reviewed_at": transaction.reviewed_at,
            "review_reason": transaction.review_reason,
            "risk_reassessment": transaction.risk_reassessment,
            "created_at": transaction.created_at,
            "order_id": order_id,
            "customer": (
                {"user_id": customer.id, "name": customer.name, "email": customer.email}
                if customer is not None else None
            ),
        }
        result["fraud_prediction"] = (
            {
                "fraud_probability": prediction.fraud_probability,
                **score_classification_fields(prediction),
                "decision": prediction.decision,
                "operational_decision": operational_decision_for(db, transaction, prediction),
                "original_operational_decision": prediction.decision,
                "manual_decision": transaction.review_decision,
                "model_used": prediction.model_used,
                "review_reason": operational_review_reason(transaction, prediction),
                "prediction_created_at": prediction.created_at,
            }
            if prediction is not None else None
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


def serialize_review_transaction(transaction, customer, prediction, db):
    return {
        "transaction_id": transaction.id,
        "amount": transaction.amount,
        "currency": transaction.currency,
        "status": transaction.status,
        "review_decision": transaction.review_decision,
        "reviewed_by_admin_id": transaction.reviewed_by_admin_id,
        "reviewed_at": transaction.reviewed_at,
        "review_reason": transaction.review_reason,
        "risk_reassessment": transaction.risk_reassessment,
        "created_at": transaction.created_at,
        "customer": (
            {"user_id": customer.id, "name": customer.name, "email": customer.email}
            if customer is not None else None
        ),
        "fraud_prediction": {
            "fraud_probability": prediction.fraud_probability,
            **score_classification_fields(prediction),
            "decision": prediction.decision,
            "operational_decision": operational_decision_for(db, transaction, prediction),
            "original_operational_decision": prediction.decision,
            "manual_decision": transaction.review_decision,
            "model_used": prediction.model_used,
            "review_reason": (
                historical_classification_notice(prediction)
                if not score_classification_fields(prediction)["classification_consistent"]
                and transaction.status == "REVIEW" and not transaction.review_decision
                else operational_review_reason(transaction, prediction)
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
            FraudPrediction.score_based_decision.label("score_based_decision"),
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
        .filter(Transaction.status == "REVIEW")
        .order_by(Transaction.created_at.asc(), Transaction.id.asc())
        .all()
    )
    return [
        serialize_review_transaction(transaction, customer, prediction, db)
        for transaction, customer, prediction in rows
        if prediction.decision == "REVIEW" or is_medium_delivery_history_review(transaction, prediction)
    ]


@app.post("/api/admin/reviews/{transaction_id}/reassess")
def reassess_high_risk_transaction(
    transaction_id: int,
    db: Session = Depends(get_db),
    current_admin: Admin = Depends(get_current_admin),
):
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).with_for_update().first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    prediction = db.query(FraudPrediction).filter(
        FraudPrediction.transaction_id == transaction.id
    ).order_by(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()).first()
    if transaction.status != "REVIEW" or prediction is None or prediction.decision != "REVIEW":
        raise HTTPException(status_code=409, detail="Only a pending review can be reassessed")
    if not is_high_risk_prediction(prediction):
        raise HTTPException(status_code=409, detail="This transaction does not require high-risk reassessment")
    try:
        require_verified_email(db, db.query(User).filter(User.id == transaction.user_id).one())
        shipping_address = transaction_shipping_address(transaction)
    except (NoResultFound, HTTPException) as error:
        raise HTTPException(status_code=409, detail="Verified account and saved delivery address are required for reassessment") from error
    if shipping_address.address_confirmed is not True:
        raise HTTPException(status_code=409, detail="The saved delivery address is not confirmed; checkout must be reviewed again")

    address_checks = collect_address_account_history(db, transaction, shipping_address)
    graph_check = collect_graph_relationship_check(db, transaction, prediction)
    now = datetime.datetime.utcnow()
    transaction.risk_reassessment = {
        "version": 1,
        "ready_for_admin_decision": True,
        "assessed_at": now.isoformat(),
        "assessed_by_admin_id": current_admin.id,
        "checkout_attempt_id": order_attempt_identifier(transaction),
        "shipping_address_hash": shipping_address_hash(shipping_address),
        "fraud_prediction_id": prediction.id,
        "score": prediction.fraud_probability,
        "score_based_decision": score_based_decision_for(prediction),
        "operational_decision": prediction.decision,
        "risk_level": prediction.risk_level,
        "model_used": prediction.model_used,
        "thresholds": {"review": FRAUD_REVIEW_THRESHOLD, "block": FRAUD_BLOCK_THRESHOLD},
        "address_account_checks": address_checks,
        "graph_relationship_check": graph_check,
        "automatic_decision_changed": False,
    }
    try:
        db.commit()
    except Exception as error:
        db.rollback()
        logger.exception("High-risk reassessment persistence failed")
        raise HTTPException(status_code=503, detail="Reassessment could not be saved; transaction remains on hold") from error
    return {
        "transaction_id": transaction.id,
        "status": transaction.status,
        "risk_reassessment": transaction.risk_reassessment,
        "review_decision": transaction.review_decision,
    }


def decide_review(transaction_id: int, decision: str, request: AdminReviewRequest, db: Session, current_admin: Admin):
    from datetime import datetime

    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).with_for_update().first()
    if transaction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    prediction = db.query(FraudPrediction).filter(
        FraudPrediction.transaction_id == transaction_id
    ).order_by(FraudPrediction.created_at.desc(), FraudPrediction.id.desc()).first()
    if prediction is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    medium_history_review = is_medium_delivery_history_review(transaction, prediction)
    if prediction.decision != "REVIEW" and not medium_history_review:
        raise HTTPException(status_code=409, detail="Only transactions with a REVIEW prediction can be reviewed")
    if transaction.status != "REVIEW":
        raise HTTPException(status_code=409, detail="This transaction has already been reviewed")
    high_risk = is_high_risk_prediction(prediction)
    if high_risk or medium_history_review:
        if not current_reassessment_matches(transaction, prediction):
            raise HTTPException(status_code=409, detail="Complete the required evidence reassessment before recording an administrator decision")
        if medium_history_review:
            require_current_medium_review_assessment(transaction, prediction)
        if not request.reason or not request.reason.strip():
            raise HTTPException(status_code=422, detail="An administrator reason is required for this evidence-based review")
        graph_incomplete = (transaction.risk_reassessment or {}).get("graph_relationship_check", {}).get("status") == "INCOMPLETE_EVIDENCE"
        if decision == "APPROVE" and graph_incomplete and not request.acknowledge_incomplete_graph_evidence:
            raise HTTPException(status_code=422, detail="Acknowledge incomplete graph evidence before approving this held transaction")

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
    if transaction.risk_reassessment:
        assessment = dict(transaction.risk_reassessment)
        assessment["administrator_decision"] = {
            "decision": decision,
            "reviewed_by_admin_id": current_admin.id,
            "reviewed_at": now.isoformat(),
            "reason": request.reason,
            "acknowledge_incomplete_graph_evidence": request.acknowledge_incomplete_graph_evidence,
        }
        transaction.risk_reassessment = assessment
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
        "risk_reassessment": transaction.risk_reassessment,
        "score_based_decision": score_based_decision_for(prediction),
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
                        **score_classification_fields(prediction),
                        "decision": prediction.decision,
                        "operational_decision": operational_decision_for(db, transaction, prediction),
                        "original_operational_decision": prediction.decision,
                        "manual_decision": transaction.review_decision,
                        "review_status": transaction.status,
                        "model_used": prediction.model_used,
                        "review_reason": (
                            historical_classification_notice(prediction)
                            if not score_classification_fields(prediction)["classification_consistent"]
                            and transaction.status == "REVIEW" and not transaction.review_decision
                            else operational_review_reason(transaction, prediction)
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
