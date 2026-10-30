import os
import sys
from pathlib import Path

os.environ.setdefault("AUTH_TOKEN_SECRET", "test-only-signing-key-for-benchmark-tests")
os.environ.setdefault("ENABLE_DEMO_ADMIN", "false")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import main
from app.database.session import Base
from app.models.admin import Admin
from app.models.user import User
from app.ml.benchmark_eval import compute_metrics, get_or_run_benchmark
from app.services.auth import (
    create_access_token,
    create_admin_access_token,
    hash_password,
)


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'benchmark.sqlite'}")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_compute_metrics_calculation():
    y_true = np.array([0, 0, 1, 1])
    y_prob = np.array([0.1, 0.4, 0.6, 0.8])
    res = compute_metrics(y_true, y_prob, threshold=0.5)

    assert res["roc_auc"] == 1.0
    assert res["pr_auc"] == 1.0
    assert res["precision"] == 1.0
    assert res["recall"] == 1.0
    assert res["f1"] == 1.0
    assert res["confusion_matrix"]["tn"] == 2
    assert res["confusion_matrix"]["fp"] == 0
    assert res["confusion_matrix"]["fn"] == 0
    assert res["confusion_matrix"]["tp"] == 2


def test_compute_metrics_with_errors():
    y_true = np.array([0, 0, 1, 1])
    # 1 FP (index 1), 1 FN (index 2)
    y_prob = np.array([0.1, 0.9, 0.2, 0.8])
    res = compute_metrics(y_true, y_prob, threshold=0.5)

    assert res["confusion_matrix"]["tn"] == 1
    assert res["confusion_matrix"]["fp"] == 1
    assert res["confusion_matrix"]["fn"] == 1
    assert res["confusion_matrix"]["tp"] == 1
    assert res["precision"] == 0.5
    assert res["recall"] == 0.5
    assert res["f1"] == 0.5


def test_benchmark_data_structure_and_values():
    benchmark = get_or_run_benchmark(force_refresh=False)

    assert benchmark["status"] == "success"
    ds = benchmark["dataset_info"]
    assert ds["evaluated_test_rows"] == 88581
    assert ds["fraud_count"] == 3083
    assert ds["legitimate_count"] == 85498
    assert "70% Train" in ds["split_strategy"]

    # GraphSAGE metrics verification
    gs = benchmark["models"]["graphsage"]["metrics"]
    assert 0.70 <= gs["roc_auc"] <= 0.80
    assert 0.10 <= gs["pr_auc"] <= 0.20
    assert gs["confusion_matrix"]["tp"] > 0
    assert gs["confusion_matrix"]["tn"] > 0

    # Baseline metrics verification
    lr = benchmark["models"]["logistic_regression"]["metrics"]
    assert 0.70 <= lr["roc_auc"] <= 0.80
    assert 0.08 <= lr["pr_auc"] <= 0.15

    # Check sample transactions
    samples = benchmark["sample_transactions"]
    assert len(samples) == 20
    outcomes = {s["outcome_group"] for s in samples}
    assert "True Positive" in outcomes
    assert "True Negative" in outcomes
    assert "False Positive" in outcomes
    assert "False Negative" in outcomes

    for sample in samples:
        assert "transaction_id" in sample
        assert "graphsage_score" in sample
        assert "baseline_score" in sample
        assert sample["actual_label"] in (0, 1)
        assert sample["graphsage_outcome"] in ("TP", "TN", "FP", "FN")

    # Check warnings
    warnings = benchmark["warnings_and_limitations"]
    assert any("does NOT establish real-world" in w for w in warnings)
    assert any("ProductCD" in w for w in warnings)
    topology_warning = next(w for w in warnings if "saved model's P_emaildomain and DeviceInfo schema" in w)
    assert "no trustworthy DeviceInfo value" in topology_warning
    assert "remains insufficient" in topology_warning
    assert any("existing REVIEW safeguard remains active" in w for w in warnings)
    assert not any("account-isolated graph topology" in w for w in warnings)


def test_benchmark_route_registered_and_protected(database):
    # Verify the route is registered on app
    routes = [r for r in main.app.routes if getattr(r, "path", None) == "/api/admin/benchmark/evaluation"]
    assert len(routes) == 1
    route = routes[0]
    assert "GET" in route.methods

    # Verify dependency on get_current_admin
    assert any(dep.call == main.get_current_admin for dep in route.dependant.dependencies)

    # Verify authorization mechanics
    admin = Admin(email="bench-admin@example.test", hashed_password=hash_password("adminpass123"))
    user = User(name="Regular Customer", email="customer@example.test", hashed_password=hash_password("userpass123"))
    database.add_all([admin, user])
    database.commit()

    # 1. No credentials -> 401
    with pytest.raises(HTTPException) as unauth:
        main.get_current_admin(credentials=None, db=database)
    assert unauth.value.status_code == 401

    # 2. Customer user credentials -> 401
    user_cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials=create_access_token(user.id))
    with pytest.raises(HTTPException) as forbidden:
        main.get_current_admin(credentials=user_cred, db=database)
    assert forbidden.value.status_code == 401

    # 3. Admin credentials -> returns admin
    admin_cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials=create_admin_access_token(admin.id))
    current_admin = main.get_current_admin(credentials=admin_cred, db=database)
    assert current_admin.id == admin.id

    # 4. Route handler execution with valid admin
    result = main.get_benchmark_evaluation(force_refresh=False, current_admin=current_admin)
    assert result["status"] == "success"
    assert "models" in result
    assert "dataset_info" in result
