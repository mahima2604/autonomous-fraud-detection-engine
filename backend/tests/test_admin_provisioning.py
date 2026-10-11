import os

# auth.py requires a configured signing key even though these tests exercise
# password hashing and database provisioning only.
os.environ.setdefault("AUTH_TOKEN_SECRET", "test-only-signing-key-for-provisioning-tests")

import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.admin_provisioning import (
    AdminAlreadyExistsError,
    bootstrap_demo_admin,
    provision_admin,
)
from app.database.session import Base
from app.models.admin import Admin
from app.services.auth import hash_password, verify_password


@pytest.fixture
def isolated_session_factory(tmp_path):
    database_path = tmp_path / "isolated-admins.sqlite"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(bind=engine, tables=[Admin.__table__])
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    yield factory
    engine.dispose()


def clear_bootstrap_settings(monkeypatch):
    for key in ("ENABLE_DEMO_ADMIN", "APP_ENV", "ADMIN_EMAIL", "ADMIN_PASSWORD"):
        monkeypatch.delenv(key, raising=False)


def admin_count(session_factory):
    with session_factory() as db:
        return db.query(Admin).count()


def test_bootstrap_disabled_by_default_creates_no_admin(isolated_session_factory, monkeypatch):
    clear_bootstrap_settings(monkeypatch)

    created = bootstrap_demo_admin(isolated_session_factory)

    assert created is False
    assert admin_count(isolated_session_factory) == 0


def test_explicit_development_bootstrap_hashes_password(isolated_session_factory, monkeypatch):
    clear_bootstrap_settings(monkeypatch)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ENABLE_DEMO_ADMIN", "true")
    monkeypatch.setenv("ADMIN_EMAIL", "local-admin@example.test")
    monkeypatch.setenv("ADMIN_PASSWORD", "local-test-password")

    created = bootstrap_demo_admin(isolated_session_factory)

    assert created is True
    with isolated_session_factory() as db:
        admin = db.query(Admin).one()
        assert admin.email == "local-admin@example.test"
        assert admin.hashed_password != "local-test-password"
        assert verify_password("local-test-password", admin.hashed_password)


def test_production_refuses_demo_bootstrap(isolated_session_factory):
    with pytest.raises(RuntimeError, match="only in development"):
        bootstrap_demo_admin(
            isolated_session_factory,
            app_environment="production",
            enabled="true",
            email="local-admin@example.test",
            password="local-test-password",
        )

    assert admin_count(isolated_session_factory) == 0


@pytest.mark.parametrize(
    ("email", "password"),
    [("", "local-test-password"), ("local-admin@example.test", "")],
)
def test_enabled_bootstrap_rejects_missing_credentials(
    isolated_session_factory, email, password
):
    with pytest.raises(ValueError, match="required"):
        bootstrap_demo_admin(
            isolated_session_factory,
            app_environment="development",
            enabled="true",
            email=email,
            password=password,
        )

    assert admin_count(isolated_session_factory) == 0


def test_provisioning_refuses_to_overwrite_existing_admin(isolated_session_factory):
    with isolated_session_factory() as db:
        admin = Admin(
            email="existing-admin@example.test",
            hashed_password=hash_password("original-test-password"),
        )
        db.add(admin)
        db.commit()
        original_hash = admin.hashed_password

    with pytest.raises(AdminAlreadyExistsError, match="already exists"):
        provision_admin(
            "existing-admin@example.test",
            "replacement-test-password",
            isolated_session_factory,
        )

    with isolated_session_factory() as db:
        admin = db.query(Admin).one()
        assert admin.hashed_password == original_hash
        assert verify_password("original-test-password", admin.hashed_password)
