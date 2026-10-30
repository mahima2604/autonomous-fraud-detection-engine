import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ENV_FILE, get_required_secret, load_project_environment


@pytest.mark.parametrize("contents", [
    "",
    "AUTH_TOKEN_SECRET=too-short-test-value\n",
])
def test_missing_or_short_auth_secret_fails_without_exposing_value(tmp_path, monkeypatch, contents):
    env_file = tmp_path / ".env"
    env_file.write_text(contents, encoding="utf-8")
    monkeypatch.delenv("AUTH_TOKEN_SECRET", raising=False)

    with pytest.raises(RuntimeError) as error:
        get_required_secret("AUTH_TOKEN_SECRET", env_file=env_file)

    assert "AUTH_TOKEN_SECRET" in str(error.value)
    assert "32 characters" in str(error.value)
    assert "too-short-test-value" not in str(error.value)


def test_nonempty_process_environment_takes_precedence_over_dotenv(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CONFIG_TEST_VALUE=from-file\n", encoding="utf-8")
    monkeypatch.setenv("CONFIG_TEST_VALUE", "from-process")

    load_project_environment(env_file)

    assert os.environ["CONFIG_TEST_VALUE"] == "from-process"


def test_empty_process_environment_uses_nonempty_dotenv_value(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("CONFIG_TEST_VALUE=from-file\n", encoding="utf-8")
    monkeypatch.setenv("CONFIG_TEST_VALUE", "")

    load_project_environment(env_file)

    assert os.environ["CONFIG_TEST_VALUE"] == "from-file"


def test_backend_configuration_loads_from_project_root_when_started_in_backend():
    backend_dir = Path(__file__).resolve().parents[1]
    child_env = os.environ.copy()
    child_env.pop("AUTH_TOKEN_SECRET", None)
    command = (
        "from app.services.auth import TOKEN_SECRET; "
        "assert len(TOKEN_SECRET) >= 32; print('AUTH_CONFIG_VALID')"
    )

    result = subprocess.run(
        [sys.executable, "-c", command],
        cwd=backend_dir,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, "Backend auth configuration did not load from the project root"
    assert result.stdout.strip() == "AUTH_CONFIG_VALID"


def test_repository_env_file_is_the_documented_root_env_file():
    assert ENV_FILE == Path(__file__).resolve().parents[2] / ".env"


def test_health_check_endpoint(monkeypatch):
    monkeypatch.setenv("AUTH_TOKEN_SECRET", "test-only-signing-key-for-health-test-123456")
    from app import main
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        data = main.health_check(db=session)
        assert data["status"] in {"healthy", "degraded"}
        assert data["database"] == "connected"
        assert "active_model" in data
        assert "version" in data
        routes = {route.path for route in main.app.routes}
        assert "/health" in routes
        assert "/api/health" in routes
    finally:
        session.close()
        engine.dispose()
