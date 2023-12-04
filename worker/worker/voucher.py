import os
from datetime import datetime, timezone, timedelta

import jwt
import requests
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, scoped_session

from common import logger
from common.models.voucher import VoucherRequest
from common.utils.aws import fetch_secrets, fetch_parameter
from schemas.aws import SQSMessage

DB_URI = os.environ.get("DB_URI")
db_password = fetch_secrets(os.environ.get("REGION_NAME"), os.environ.get("SECRET_ARN"))["password"]
DB_URI = DB_URI.replace("[DB_PASSWORD]", db_password)
VOUCHER_URL = os.environ.get("VOUCHER_URL")
VOUCHER_JWT_SECRET = fetch_parameter(
    os.environ.get("REGION_NAME"),
    f"{os.environ.get('STAGE')}_9c_IAP_VOUCHER_JWT_SECRET",
    True
)["Value"]

engine = create_engine(DB_URI, pool_size=5, max_overflow=5)


def get_voucher_token() -> str:
    now = datetime.now(tz=timezone.utc)
    data = {
        "iat": now,
        "exp": now + timedelta(seconds=10)
    }
    return jwt.encode(data, VOUCHER_JWT_SECRET)


def request(sess, voucher: VoucherRequest) -> bool:
    resp = requests.post(
        VOUCHER_URL,
        headers={"Authorization": f"Bearer {get_voucher_token()}"},
        json={
            "planetId": voucher.planet_id,
            "agentAddress": voucher.agent_addr,
            # "avatarAddress": voucher.avatar_addr,
            "iapUuid": voucher.uuid,
            "productId": voucher.product_id,
            "productName": voucher.product.name,
        },
    )
    success = False
    voucher.status = resp.status_code
    if resp.status_code == 200:
        voucher.message = "Success"
        success = True
    else:
        logger.error(f"{voucher.id} :: {voucher.uuid} :: {resp.status_code} :: {resp.text}")
        voucher.message = resp.text

    sess.add(voucher)
    sess.commit()
    sess.refresh(voucher)

    return success


def handle(event, context):
    message = SQSMessage(Records=event.get("Records", {}))
    logger.info(f"SQS Message: {message}")

    sess = scoped_session(sessionmaker(bind=engine))
    try:
        uuid_list = [x.body.get("uuid") for x in message.Records if x.body.get("uuid")]
        voucher_list = sess.scalars(select(VoucherRequest.uuid).where(VoucherRequest.uuid.in_(uuid_list))).fetchall()
        target_message_list = [x.body for x in message.Records if
                               x.body.get("force", False) is True or x.body.get("uuid") not in voucher_list]

        for msg in target_message_list:
            voucher = VoucherRequest(**msg)
            sess.add(voucher)
            sess.commit()
            sess.refresh(voucher)
            request(sess, voucher)
    finally:
        if sess is not None:
            sess.close()
