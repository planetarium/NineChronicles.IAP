import logging
import os

from starlette.config import Config

from common.utils.aws import fetch_secrets, fetch_parameter

stage = os.environ.get("STAGE", "local")
db_password = None
google_credential = None
apple_credential = None
season_pass_jwt_secret = None
headless_gql_jwt_secret = None

if not stage:
    logging.error("Config file not found")
    raise FileNotFoundError(f"No config file for environment")

if os.path.exists(os.path.join("iap", "settings", f"{stage}.py")):
    env_module = __import__(f"iap.settings.{stage}", fromlist=["iap.settings"])
    envs = {k: v for k, v in env_module.__dict__.items() if k.upper() == k}
    config = Config(environ=envs)
else:
    config = Config(environ=os.environ)
    if os.environ.get("SECRET_ARN"):
        db_password = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))["password"]

    try:
        google_credential = fetch_parameter(
            os.environ.get("REGION_NAME"),
            f"{stage}_9c_IAP_GOOGLE_CREDENTIAL",
            True
        )["Value"]
    except Exception as e:
        google_credential = os.environ.get("GOOGLE_CREDENTIAL", "")

    try:
        apple_credential = fetch_parameter(
            os.environ.get("REGION_NAME"),
            f"{stage}_9c_IAP_APPLE_CREDENTIAL",
            True
        )["Value"]
    except Exception as e:
        apple_credential = os.environ.get("APPLE_CREDENTIAL", "")

    try:
        season_pass_jwt_secret = fetch_parameter(
            os.environ.get("REGION_NAME"),
            f"{stage}_9c_IAP_SEASON_PASS_JWT_SECRET",
            True
        )["Value"]
    except Exception as e:
        season_pass_jwt_secret = os.environ.get("SEASON_PASS_JWT_SECRET", "")

    try:
        headless_gql_jwt_secret = fetch_parameter(
            os.environ.get("REGION_NAME"),
            f"{stage}_9c_IAP_HEADLESS_GQL_JWT_SECRET",
            True
        )["Value"]
    except Exception as e:
        headless_gql_jwt_secret = os.environ.get("HEADLESS_GQL_JWT_SECRET", "")

    try:
        jwt_secret = fetch_parameter(
            os.environ.get("REGION_NAME"),
            f"{stage}_9c_IAP_JWT_SECRET",
            True
        )["Value"]
    except Exception as e:
        jwt_secret = os.environ.get("JWT_SECRET", "")

# Prepare settings
DEBUG = config("DEBUG", cast=bool, default=False)
LOGGING_LEVEL = logging.getLevelName(config("LOGGING_LEVEL", default="INFO"))
DB_URI = config("DB_URI")
if db_password is not None:
    DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)
DB_ECHO = config("DB_ECHO", cast=bool, default=False)

GOOGLE_PACKAGE_NAME = config("GOOGLE_PACKAGE_NAME")
GOOGLE_CREDENTIAL = google_credential or config("GOOGLE_CREDENTIAL")

APPLE_BUNDLE_ID = config("APPLE_BUNDLE_ID")
APPLE_ISSUER_ID = config("APPLE_ISSUER_ID")
APPLE_KEY_ID = config("APPLE_KEY_ID")
APPLE_CREDENTIAL = apple_credential or config("APPLE_CREDENTIAL")
APPLE_VALIDATION_URL = config("APPLE_VALIDATION_URL")

REGION_NAME = config("REGION_NAME")

SEASON_PASS_JWT_SECRET = season_pass_jwt_secret or config("SEASON_PASS_JWT_SECRET")
HEADLESS_JWT_GQL_SECRET = headless_gql_jwt_secret or config("HEADLESS_GQL_JWT_SECRET")
JWT_SECRET = jwt_secret or config("JWT_SECRET")
