import logging
import os
from pydantic.dataclasses import dataclass
from typing import Optional

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


@dataclass
class Config:
    stage: str
    account_id: str
    region_name: str
    headless: str = "http://localhost"
    kms_key_id: Optional[str] = None
    google_credential: Optional[str] = None
