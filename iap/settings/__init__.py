import logging
import os

from starlette.config import Config

from common.utils import fetch_db_password

env = os.environ.get("ENV", "local")
db_password = None

if not env:
    logging.error("Config file not found")
    raise FileNotFoundError(f"No config file for environment")

if os.path.exists(os.path.join("iap", "settings", f"{env}.py")):
    config = Config(os.path.join("iap", "settings", f"{env}.py"))
else:
    config = Config()
    db_password = fetch_db_password(os.environ.get("REGION"), os.environ.get("SECRET_ARN"))

# Prepare settings
DEBUG = config("DEBUG", cast=bool, default=False)
LOGGING_LEVEL = logging.getLevelName(config("LOGGING_LEVEL", default="INFO"))
DB_URI = config("DB_URI")
if db_password is not None:
    DB_URI.replace("[DB_PASSWORD]", db_password)
DB_ECHO = config("DB_ECHO", cast=bool, default=False)
GOOGLE_VALIDATION_URL = config("GOOGLE_VALIDATION_URL")
APPLE_VALIDATION_URL = config("APPLE_VALIDATION_URL")
REGION_NAME = config("REGION_NAME")
