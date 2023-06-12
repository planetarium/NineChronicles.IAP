import logging
import os

COMMON_LAMBDA_EXCLUDE = [
    "!common",
    "!common/**",
    "common/alembic",
    "common/alembic.ini",
    "common/alembic.ini.example",
    "common/poetry.lock",
    "common/pyproject.toml",
]

logger = logging.Logger("iap_logger")
try:
    logger.setLevel(getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper()))
except AttributeError:
    # Default loglevel is info
    logger.setLevel(logging.INFO)
