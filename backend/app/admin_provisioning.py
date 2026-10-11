"""Private admin provisioning helpers and interactive CLI.

Run from the backend directory with ``python -m app.admin_provisioning``.
"""

import argparse
from getpass import getpass
import os
import sys

from sqlalchemy.exc import IntegrityError

from app.database.session import SessionLocal
from app.models.fraud_prediction import FraudPrediction as _FraudPrediction
from app.models.transaction import Transaction as _Transaction
from app.models.user import User as _User
from app.models.admin import Admin
from app.services.auth import hash_password


class AdminAlreadyExistsError(Exception):
    """Raised when provisioning would overwrite an existing administrator."""


def _read_setting(explicit_value, environment_name):
    if explicit_value is not None:
        return explicit_value
    return os.getenv(environment_name, "")


def _required_credentials(email, password):
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        raise ValueError("An administrator email is required.")
    if not password:
        raise ValueError("An administrator password is required.")
    return normalized_email


def _insert_admin(email, password, session_factory):
    normalized_email = _required_credentials(email, password)
    db = session_factory()
    try:
        existing = db.query(Admin).filter(Admin.email == normalized_email).first()
        if existing is not None:
            raise AdminAlreadyExistsError("An administrator with that email already exists.")

        admin = Admin(email=normalized_email, hashed_password=hash_password(password))
        db.add(admin)
        try:
            db.commit()
        except IntegrityError as error:
            db.rollback()
            raise AdminAlreadyExistsError("An administrator with that email already exists.") from error
        db.refresh(admin)
        return admin.id
    finally:
        db.close()


def bootstrap_demo_admin(
    session_factory=SessionLocal,
    *,
    app_environment=None,
    enabled=None,
    email=None,
    password=None,
):
    """Create the configured demo admin only when explicitly enabled locally."""
    enabled_value = _read_setting(enabled, "ENABLE_DEMO_ADMIN").strip().lower()
    if enabled_value in ("", "false"):
        return False
    if enabled_value != "true":
        raise RuntimeError("ENABLE_DEMO_ADMIN must be either true or false.")

    environment = _read_setting(app_environment, "APP_ENV").strip().lower()
    if environment != "development":
        raise RuntimeError("Demo administrator bootstrap is allowed only in development.")

    configured_email = _read_setting(email, "ADMIN_EMAIL")
    configured_password = _read_setting(password, "ADMIN_PASSWORD")
    _required_credentials(configured_email, configured_password)

    try:
        _insert_admin(configured_email, configured_password, session_factory)
    except AdminAlreadyExistsError:
        return False
    return True


def provision_admin(email, password, session_factory=SessionLocal):
    """Provision one administrator without replacing an existing account."""
    return _insert_admin(email, password, session_factory)


def main():
    parser = argparse.ArgumentParser(description="Provision an administrator account.")
    parser.add_argument("--email", help="Administrator email (prompted if omitted).")
    args = parser.parse_args()

    email = (args.email or input("Administrator email: ")).strip()
    password = getpass("Administrator password: ")
    confirmation = getpass("Confirm administrator password: ")
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 1

    try:
        provision_admin(email, password)
    except AdminAlreadyExistsError:
        print("Administrator already exists; no changes were made.", file=sys.stderr)
        return 1
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1

    print("Administrator provisioned.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
