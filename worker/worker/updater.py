import concurrent.futures
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from common import logger
from common.utils.aws import fetch_secrets, fetch_parameter
from common.utils.google import update_google_price

stage = os.environ.get("STAGE", "development")
DB_URI = os.environ.get("DB_URI")
secrets = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))
DB_URI = DB_URI.replace("[DB_PASSWORD]", secrets["password"])

engine = create_engine(DB_URI, pool_size=5, max_overflow=5)


def update_google() -> str:
    sess = scoped_session(sessionmaker(bind=engine))
    google_credential = fetch_parameter(
        os.environ.get("REGION_NAME"),
        f"{stage}_9c_IAP_GOOGLE_CREDENTIAL", True
    )["Value"]

    try:
        updated_product_count, updated_price_count = update_google_price(
            sess, google_credential, os.environ.get("GOOGLE_PACKAGE_NAME")
        )
        return f"{updated_price_count} prices in {updated_product_count} products are updated"
    except Exception as e:
        msg = f"Google price updater failed: {e}"
        logger.error(msg)
        return msg


def update_apple() -> str:
    return "No apple update for now"


def update_prices(event, context):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(update_google), executor.submit(update_apple)]
        results = [future.result() for future in concurrent.futures.as_completed(futures)]

    for result in results:
        logger.info(result)
