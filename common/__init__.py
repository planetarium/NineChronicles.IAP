import logging
import os
from typing import Optional

from pydantic.dataclasses import dataclass

COMMON_LAMBDA_EXCLUDE = [
    "!common",
    "!common/**",
    "common/__pycache__",
    "common/layer",
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
    # NOTE: non-default fields must come first
    stage: str
    account_id: str
    region_name: str
    cdn_host: str

    google_package_name: str
    apple_bundle_id: str

    # Google
    google_credential: Optional[str] = None
    # Apple
    apple_credential: Optional[str] = None
    apple_validation_url: Optional[str] = None
    apple_key_id: Optional[str] = None
    apple_issuer_id: Optional[str] = None

    headless: str = "http://localhost"
    kms_key_id: Optional[str] = None
    golden_dust_request_sheet_id: Optional[str] = None
    golden_dust_work_sheet_id: Optional[str] = None
    form_sheet: Optional[str] = None

    # SeasonPass
    season_pass_jwt_secret: str = None
