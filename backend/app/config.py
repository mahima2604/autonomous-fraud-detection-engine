"""Load the repository's local configuration consistently for every process."""

import os
from pathlib import Path

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


def load_project_environment(env_file=ENV_FILE):
    """Load project-root .env values while preserving nonempty process overrides.

    Empty inherited variables are treated as unset so they cannot mask a valid
    value from the project configuration file.
    """
    values = dotenv_values(env_file)
    for name, value in values.items():
        current = os.environ.get(name)
        if current is not None and current.strip():
            continue
        if value is not None and value.strip():
            os.environ[name] = value
        else:
            os.environ.pop(name, None)


def get_required_secret(name, minimum_length=32, env_file=ENV_FILE):
    """Load and validate a required secret without including it in errors."""
    load_project_environment(env_file)
    value = os.environ.get(name, "")
    if len(value.strip()) < minimum_length:
        raise RuntimeError(
            f"{name} is missing or invalid. Set a private random value of at least "
            f"{minimum_length} characters in {env_file} or in the process environment. "
            "For local setup, generate one with Python's secrets.token_urlsafe(48)."
        )
    return value.encode("utf-8")
