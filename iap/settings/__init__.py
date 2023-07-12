import logging
import os

from starlette.config import Config

from common.utils import fetch_secrets, fetch_parameter

stage = os.environ.get("STAGE", "local")
db_password = None
google_credential = None

if not stage:
    logging.error("Config file not found")
    raise FileNotFoundError(f"No config file for environment")

if os.path.exists(os.path.join("iap", "settings", f"{stage}.py")):
    env_module = __import__(f"iap.settings.{stage}", fromlist=["iap.settings"])
    envs = {k: v for k, v in env_module.__dict__.items() if k.upper() == k}
    config = Config(environ=envs)
else:
    config = Config()
    secrets = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))
    db_password = secrets["password"]
    google_credential = fetch_parameter(
        os.environ.get("REGION_NAME"),
        f"{stage}_9c_IAP_GOOGLE_CREDENTIAL",
        True
    )["Value"]

# Prepare settings
DEBUG = config("DEBUG", cast=bool, default=False)
LOGGING_LEVEL = logging.getLevelName(config("LOGGING_LEVEL", default="INFO"))
DB_URI = config("DB_URI")
if db_password is not None:
    DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)
DB_ECHO = config("DB_ECHO", cast=bool, default=False)

GOOGLE_PACKAGE_NAME = config("GOOGLE_PACKAGE_NAME")
GOOGLE_CREDENTIAL = google_credential or config("GOOGLE_CREDENTIAL")

APPLE_VALIDATION_URL = config("APPLE_VALIDATION_URL")

REGION_NAME = config("REGION_NAME")
