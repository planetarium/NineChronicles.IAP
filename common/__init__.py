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

try:
    loglevel = getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper())
except AttributeError:
    loglevel = logging.INFO

logger = logging.Logger("iap_logger")
logger.setLevel(loglevel)

handler = logging.StreamHandler()
handler.setLevel(loglevel)
logger.addHandler(handler)
