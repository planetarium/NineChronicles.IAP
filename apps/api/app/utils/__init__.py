from datetime import datetime, timezone, timedelta
from collections import defaultdict
from typing import Annotated, Optional

import jwt
import structlog
from fastapi import Header, HTTPException
from jwt.exceptions import ExpiredSignatureError
from shared.enums import PlanetID, ReceiptStatus
from shared.models.mileage import Mileage
from shared.models.product import Product
from shared.models.receipt import Receipt
from shared.utils.address import format_addr
from sqlalchemy import Date, cast, func, select
from sqlalchemy.sql.functions import count

from app.config import config

logger = structlog.get_logger(__name__)


def get_purchase_history(
    sess,
    planet_id: PlanetID,
    address: str,
    product: Optional[Product] = None,
    use_avatar: bool = False,
) -> defaultdict:
    stmt = select(
        Receipt.product_id,
        count(Receipt.id).label("purchase_count"),
        cast(func.timezone('Asia/Seoul', Receipt.purchased_at), Date).label("date"),
    ).where(
        Receipt.planet_id == planet_id,
        Receipt.status.in_(
            (ReceiptStatus.INIT, ReceiptStatus.VALIDATION_REQUEST, ReceiptStatus.VALID)
        ),
    )
    if product is not None:
        stmt = stmt.where(Receipt.product_id == product.id)
    if use_avatar:
        stmt = stmt.where(Receipt.avatar_addr == address)
    else:
        stmt = stmt.where(Receipt.agent_addr == address)
    stmt = stmt.group_by("date", Receipt.product_id)
    receipt_list = sess.execute(stmt).fetchall()

    receipt_dict = defaultdict(lambda: defaultdict(int))
    kst_now = datetime.now(timezone(timedelta(hours=9)))
    daily_limit = kst_now.date()
    # Weekday 0 == Sunday
    weekly_limit = (
        kst_now
        - timedelta(days=(kst_now.date().isoweekday()) % 7)
    ).date()
    for receipt in receipt_list:
        if receipt.date >= daily_limit:
            receipt_dict["daily"][receipt.product_id] += receipt.purchase_count
        if receipt.date >= weekly_limit:
            receipt_dict["weekly"][receipt.product_id] += receipt.purchase_count
        receipt_dict["account"][receipt.product_id] += receipt.purchase_count

    return receipt_dict


def get_purchase_count(
    sess,
    product_id: int,
    *,
    planet_id: PlanetID,
    agent_addr: str = None,
    avatar_addr: str = None,
    daily_limit: bool = False,
    weekly_limit: bool = False,
) -> int:
    """
    Scan purchase history and get purchase count in given time limit.

    :param sess: DB Session
    :param agent_addr: 9c Agent address
    :param product_id: Target product ID to scan.
    :param daily_limit: purchase history limit in day. Get the today
    :param weekly_limit: purchase history limit in week. Get the first weekday(Sunday) of this week
    :return:
    """
    stmt = sess.query(
        func.count(Receipt.id).filter(
            Receipt.product_id == product_id,
            Receipt.planet_id == planet_id,
            Receipt.status.in_(
                (
                    ReceiptStatus.INIT,
                    ReceiptStatus.VALIDATION_REQUEST,
                    ReceiptStatus.VALID,
                )
            ),
        )
    )
    if agent_addr:
        stmt = stmt.filter(Receipt.agent_addr == agent_addr)
    if avatar_addr:
        stmt = stmt.filter(Receipt.avatar_addr == avatar_addr)

    start = None
    kst_now = datetime.now(timezone(timedelta(hours=9)))
    if daily_limit:
        start = kst_now.date()
    elif weekly_limit:
        start = (
            kst_now
            - timedelta(
                days=(kst_now.date().isoweekday()) % 7
            )
        ).date()
    if start:
        stmt = stmt.filter(cast(func.timezone('Asia/Seoul', Receipt.purchased_at), Date) >= start)
    purchase_count = stmt.scalar()
    logger.debug(
        f"Agent {agent_addr} purchased product {product_id} {purchase_count} times in {'today' if daily_limit else 'this week'} from {start or 'Anytime'}"
    )
    return purchase_count


def create_season_pass_jwt() -> str:
    now = datetime.now(tz=timezone.utc)
    return jwt.encode(
        {
            "iat": now,
            "exp": now + timedelta(minutes=10),
            "aud": "SeasonPass",
        },
        config.season_pass_jwt_secret,
        algorithm="HS256",
    )


def get_mileage(sess, agent_addr: str) -> Mileage:
    """
    Read or create Mileage instance from DB.
    If no valid Mileage instance found, create new one.

    :param sess: SQLAlchemy session to use DB.
    :param planet_id: PlanetID of target agent.
    :param agent_addr: Address of target agent.
    :return: Found/created Mileage instance.
    """
    agent_addr = format_addr(agent_addr)
    # UPDATE: mileage has been merge across planets. Use one without planet_id.
    #  Merged mileage has planet_id as None. Others are historical data.
    mileage = sess.scalar(select(Mileage).where(Mileage.agent_addr == agent_addr))
    if not mileage:
        mileage = Mileage(agent_addr=agent_addr, mileage=0)
        sess.add(mileage)
        sess.commit()
        sess.refresh(mileage)
    return mileage


def upsert_mileage(
    sess, product: Product, receipt: Receipt, mileage: Optional[Mileage] = None
) -> Receipt:
    """
    Update or create mileage from purchase.
    NOTE: This function only create and store mileage from purchase.
        If you want to deal with "mileage purchase", please do it yourself and store new mileage with this function.

    :param sess: SQLAlchemy session to use DB.
    :param product: Product to purchase.
    :param receipt: Receipt to write history.
    :param mileage: Target mileage instance to store mileage data.
    :return: Updated receipt instance.
    """
    if mileage is None:
        mileage = get_mileage(sess, receipt.agent_addr)
    target_mileage = product.mileage or 0
    if receipt.planet_id in (PlanetID.THOR, PlanetID.THOR_INTERNAL):
        target_mileage *= 2
    mileage.mileage += target_mileage
    receipt.mileage_change = (product.mileage or 0) - (product.mileage_price or 0)
    receipt.mileage_result = mileage.mileage
    sess.add(mileage)
    sess.add(receipt)
    return receipt


def verify_token(authorization: Annotated[str, Header()]):
    """
    Verify required API must use this.
    This function verifies `Authorization` Bearer JWT type header.

    ### How to creat token
    1. Create token data
        ```
        now = datetime.now(tz=timezone.utc)
        data = {
            "iat": now,
            "exp": now + timedelta(hours=1),  # Header with longer lifetime than 1 hour is refused.
            "aud": "iap"  # Fixed value
        }
        ```
    2. Create JWT with given secret key
        ```
        token_secret = os.environ.get("JWT_TOKEN_SECRET")
        token = jwt.encode(data, token_secrete, algorithm="HS256")
        ```

    3. Use JWT as Bearer Authorization token
        ```
        headers = {
            "Authorization": "Barer {token}".format(token=token)
        }
        requests.post(URL, headers=headers)
        ```
    JWT verification will check these conditions:
    - Token must be encoded with given secret key
    - Token must be encoded using `HS256` algorithm
    - Token `iat` (Issued at) must be past timestamp
    - Token lifetime must be shorter than 1 hour
    - Token `exp` (Expires at) must be future timestamp
    - Token `aud` (Audience) must be `iap`

    API will return `401 Not Authorized` if any of these check fails.
    """
    now = datetime.now(tz=timezone.utc)
    try:
        prefix, body = authorization.split(" ")
        if prefix != "Bearer":
            raise Exception("Invalid token type. Use `Bearer [TOKEN]`.")
        token_data = jwt.decode(
            body, config.backoffice_jwt_secret, audience="iap", algorithms=["HS256"]
        )
        if (
            datetime.fromtimestamp(token_data["iat"], tz=timezone.utc)
            + timedelta(hours=1)
        ) < datetime.fromtimestamp(
            token_data["exp"], tz=timezone.utc
        ):
            raise ExpiredSignatureError("Too long token lifetime")
        if (
            datetime.fromtimestamp(token_data["iat"], tz=timezone.utc)
            > now
        ):
            raise ExpiredSignatureError("Invalid token issue timestamp")
        if (
            datetime.fromtimestamp(token_data["exp"], tz=timezone.utc)
            < now
        ):
            raise ExpiredSignatureError("Token expired")

    except Exception as e:
        logger.warning(e)
        raise HTTPException(status_code=401, detail="Not Authorized")
