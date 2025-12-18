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
from sqlalchemy import Date, case, cast, func, select
from sqlalchemy.sql.functions import count

from app.config import config

logger = structlog.get_logger(__name__)


def get_kst_now() -> datetime:
    """
    Get current time in KST timezone.

    This function correctly converts UTC time to KST by using astimezone(),
    which properly handles timezone conversion.

    :return: Current datetime in KST timezone
    """
    utc_now = datetime.now(timezone.utc)
    return utc_now.astimezone(timezone(timedelta(hours=9)))


def get_daily_limit_date(kst_now: datetime) -> datetime.date:
    """
    Get the daily limit date based on KST 09:00 reset time.

    If current time is before 09:00 KST, use yesterday's date.
    If current time is 09:00 KST or later, use today's date.

    :param kst_now: Current datetime in KST timezone
    :return: Date to use for daily limit calculation
    """
    if kst_now.hour < 9:
        # Before 09:00 KST, use yesterday
        return (kst_now - timedelta(days=1)).date()
    else:
        # 09:00 KST or later, use today
        return kst_now.date()


def get_purchase_history(
    sess,
    planet_id: PlanetID,
    address: str,
    product: Optional[Product] = None,
    use_avatar: bool = False,
) -> defaultdict:
    # Get all receipts with purchased_at datetime (not just date)
    stmt = select(
        Receipt.product_id,
        Receipt.id,
        func.timezone('Asia/Seoul', Receipt.purchased_at).label("purchased_at_kst"),
    ).where(
        Receipt.planet_id == planet_id,
        Receipt.status.in_(
            (ReceiptStatus.INIT, ReceiptStatus.VALIDATION_REQUEST, ReceiptStatus.VALID)
        ),
        Receipt.purchased_at.isnot(None),
    )
    if product is not None:
        stmt = stmt.where(Receipt.product_id == product.id)
    if use_avatar:
        stmt = stmt.where(Receipt.avatar_addr == address)
    else:
        stmt = stmt.where(Receipt.agent_addr == address)
    receipt_list = sess.execute(stmt).fetchall()

    receipt_dict = defaultdict(lambda: defaultdict(int))
    kst_now = get_kst_now()
    current_daily_limit = get_daily_limit_date(kst_now)
    # Weekday 0 == Sunday
    # Use the same date as daily_limit (KST 09:00 based) for weekly limit calculation
    base_date = get_daily_limit_date(kst_now)
    current_weekly_limit = base_date - timedelta(days=(base_date.isoweekday()) % 7)

    for receipt in receipt_list:
        # Get the purchase date based on the receipt's purchase time (KST 09:00 rule)
        if receipt.purchased_at_kst:
            # func.timezone returns a datetime object, ensure it's timezone-aware
            purchased_at_kst = receipt.purchased_at_kst
            # If it's not timezone-aware, assume it's already in KST from the timezone function
            if purchased_at_kst.tzinfo is None:
                # If somehow timezone info is missing, add KST timezone
                purchased_at_kst = purchased_at_kst.replace(tzinfo=timezone(timedelta(hours=9)))

            # Calculate daily limit date based on the receipt's purchase time
            receipt_daily_limit_date = get_daily_limit_date(purchased_at_kst)

            # Only count if the receipt's daily limit date matches current daily limit date
            if receipt_daily_limit_date == current_daily_limit:
                receipt_dict["daily"][receipt.product_id] += 1

            # For weekly limit, calculate based on receipt's purchase time (KST 09:00 rule)
            receipt_weekly_limit_date = receipt_daily_limit_date - timedelta(days=(receipt_daily_limit_date.isoweekday()) % 7)
            if receipt_weekly_limit_date == current_weekly_limit:
                receipt_dict["weekly"][receipt.product_id] += 1

            # Account limit: always count
            receipt_dict["account"][receipt.product_id] += 1

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
    stmt = sess.query(Receipt).filter(
        Receipt.product_id == product_id,
        Receipt.planet_id == planet_id,
        Receipt.status.in_(
            (
                ReceiptStatus.INIT,
                ReceiptStatus.VALIDATION_REQUEST,
                ReceiptStatus.VALID,
            )
        ),
        Receipt.purchased_at.isnot(None),
    )
    if agent_addr:
        stmt = stmt.filter(Receipt.agent_addr == agent_addr)
    if avatar_addr:
        stmt = stmt.filter(Receipt.avatar_addr == avatar_addr)

    # Get all receipts and filter in Python based on purchase time's daily limit date
    receipt_list = stmt.all()

    kst_now = get_kst_now()
    current_daily_limit = None
    current_weekly_limit = None

    if daily_limit:
        current_daily_limit = get_daily_limit_date(kst_now)
    elif weekly_limit:
        # Use the same date as daily_limit (KST 09:00 based) for weekly limit calculation
        base_date = get_daily_limit_date(kst_now)
        current_weekly_limit = base_date - timedelta(days=(base_date.isoweekday()) % 7)

    if not (daily_limit or weekly_limit):
        # No time limit, return all count
        purchase_count = len(receipt_list)
        logger.debug(
            f"Agent {agent_addr} purchased product {product_id} {purchase_count} times (no limit)"
        )
        return purchase_count

    # Filter receipts based on their purchase time's daily limit date
    count = 0
    for receipt in receipt_list:
        if receipt.purchased_at:
            # Convert to KST
            purchased_at_kst = receipt.purchased_at.astimezone(timezone(timedelta(hours=9)))

            # Calculate daily limit date based on the receipt's purchase time
            receipt_daily_limit_date = get_daily_limit_date(purchased_at_kst)

            if daily_limit:
                # Only count if the receipt's daily limit date matches current daily limit date
                if receipt_daily_limit_date == current_daily_limit:
                    count += 1
            elif weekly_limit:
                # For weekly limit, calculate based on receipt's purchase time (KST 09:00 rule)
                receipt_weekly_limit_date = receipt_daily_limit_date - timedelta(days=(receipt_daily_limit_date.isoweekday()) % 7)
                if receipt_weekly_limit_date == current_weekly_limit:
                    count += 1

    logger.debug(
        f"Agent {agent_addr} purchased product {product_id} {count} times in {'today' if daily_limit else 'this week'} (current limit date: {current_daily_limit or current_weekly_limit})"
    )
    return count


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


def generate_redeem_jwt(service_id: str) -> str:
    """Redeem API 호출용 JWT 토큰 생성

    기존 create_season_pass_jwt() 함수와 유사한 패턴이지만,
    serviceId별로 다른 secret을 사용하고 iss claim에 serviceId를 포함합니다.

    Args:
        service_id: 서비스 ID (9C만 지원)

    Returns:
        JWT 토큰 문자열

    Raises:
        ValueError: service_id가 유효하지 않거나 secret이 없을 경우
    """
    # 9C만 지원하므로 직접 jwt_secret_9c 사용
    if service_id.upper() != "9C":
        raise ValueError(f"Unknown service_id: {service_id}. Only '9C' is supported.")

    secret = config.jwt_secret_9c
    if not secret:
        raise ValueError("JWT secret for 9C service is not configured")

    now = datetime.now(tz=timezone.utc)
    payload = {
        "iss": "9C",
        "iat": int(now.timestamp()),
        "exp": int(now.timestamp()) + 60,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


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
