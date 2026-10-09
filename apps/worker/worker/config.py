"""Worker configuration, read from environment variables (and .env, for local runs)."""

import os

from dotenv import load_dotenv


def load_environment() -> None:
    """Load .env into the environment. Real environment variables always win."""
    load_dotenv(override=False)


def required(name: str) -> str:
    """An environment variable that must be set; fails with a clear message if not."""
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is not set: add it to .env (see .env.example)")
    return value
