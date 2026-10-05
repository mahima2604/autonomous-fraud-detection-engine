import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.database.session import get_db
from app.models.user import User
from app.models.admin import Admin

TOKEN_SECRET = os.getenv("AUTH_TOKEN_SECRET", "").encode("utf-8")
if len(TOKEN_SECRET) < 32:
    raise RuntimeError("AUTH_TOKEN_SECRET must be configured with at least 32 characters")
TOKEN_TTL_SECONDS = 60 * 60 * 24 * 7
PASSWORD_ITERATIONS = 310_000
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(derived).decode()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt, expected = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), base64.urlsafe_b64decode(salt), int(iterations)
        )
        return hmac.compare_digest(base64.urlsafe_b64encode(actual).decode(), expected)
    except (ValueError, TypeError):
        return False


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def create_access_token(user_id: int) -> str:
    payload = _b64encode(json.dumps({"sub": user_id, "exp": int(time.time()) + TOKEN_TTL_SECONDS}, separators=(",", ":")).encode())
    signature = _b64encode(hmac.new(TOKEN_SECRET, payload.encode("ascii"), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def _read_signed_token(token: str, signing_key: bytes, expected_prefix: str | None = None) -> int | None:
    try:
        parts = token.split(".")
        if expected_prefix:
            prefix, payload, signature = parts
            if prefix != expected_prefix:
                return None
        else:
            payload, signature = parts
        if expected_prefix and len(parts) != 3:
            return None
        if not expected_prefix and len(parts) != 2:
            return None
        expected = _b64encode(hmac.new(signing_key, payload.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(signature, expected):
            return None
        data = json.loads(_b64decode(payload))
        if int(data["exp"]) <= int(time.time()):
            return None
        user_id = int(data["sub"])
        return user_id if user_id > 0 else None
    except (ValueError, TypeError, KeyError, json.JSONDecodeError):
        return None


def read_access_token(token: str) -> int | None:
    return _read_signed_token(token, TOKEN_SECRET)


def create_admin_access_token(admin_id: int) -> str:
    payload = _b64encode(json.dumps({"sub": admin_id, "exp": int(time.time()) + TOKEN_TTL_SECONDS}, separators=(",", ":")).encode())
    admin_key = hmac.new(TOKEN_SECRET, b"securecart-admin-token-key", hashlib.sha256).digest()
    signature = _b64encode(hmac.new(admin_key, payload.encode("ascii"), hashlib.sha256).digest())
    return f"admin.{payload}.{signature}"


def read_admin_access_token(token: str) -> int | None:
    admin_key = hmac.new(TOKEN_SECRET, b"securecart-admin-token-key", hashlib.sha256).digest()
    return _read_signed_token(token, admin_key, expected_prefix="admin")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    user_id = read_access_token(credentials.credentials) if credentials else None
    if user_id is None:
        raise HTTPException(status_code=401, detail="Invalid or missing authentication credentials")
    user = db.query(User).filter(User.id == user_id).first()
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive user")
    return user


def get_current_admin(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Admin:
    admin_id = read_admin_access_token(credentials.credentials) if credentials else None
    if admin_id is None:
        raise HTTPException(status_code=401, detail="Invalid or missing admin credentials")
    admin = db.query(Admin).filter(Admin.id == admin_id).first()
    if admin is None or not admin.is_active:
        raise HTTPException(status_code=401, detail="Invalid or inactive admin")
    return admin
