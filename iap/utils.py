import datetime

import jwt
from sqlalchemy import func, Date, cast

from common import logger
from common.enums import ReceiptStatus
from common.models.receipt import Receipt
from common.utils.receipt import PlanetID
from iap import settings


def get_purchase_count(sess, product_id: int, *, planet_id: PlanetID, agent_addr: str = None, avatar_addr: str = None,
                       daily_limit: bool = False, weekly_limit: bool = False) -> int:
    """
    Scan purchase history and get purchase count in given time limit.

    :param sess: DB Session
    :param agent_addr: 9c Agent address
    :param product_id: Target product ID to scan.
    :param daily_limit: purchase history limit in day. Get the today
    :param weekly_limit: purchase history limit in week. Get the first weekday(Sunday) of this week
    :return:
    """
    stmt = sess.query(func.count(Receipt.id).filter(
        Receipt.product_id == product_id,
        Receipt.planet_id == planet_id,
        Receipt.status.in_(
            (ReceiptStatus.INIT, ReceiptStatus.VALIDATION_REQUEST, ReceiptStatus.VALID)
        )
    ))
    if agent_addr:
        stmt = stmt.filter(Receipt.agent_addr == agent_addr)
    if avatar_addr:
        stmt = stmt.filter(Receipt.avatar_addr == avatar_addr)

    start = None
    if daily_limit:
        start = datetime.datetime.utcnow().date()
    elif weekly_limit:
        start = (datetime.datetime.utcnow() -
                 datetime.timedelta(days=(datetime.datetime.utcnow().date().isoweekday()) % 7)
                 ).date()
    if start:
        stmt = stmt.filter(cast(Receipt.purchased_at, Date) >= start)
    purchase_count = stmt.scalar()
    logger.debug(
        f"Agent {agent_addr} purchased product {product_id} {purchase_count} times in {'today' if daily_limit else 'this week'} from {start or 'Anytime'}"
    )
    return purchase_count


def create_season_pass_jwt() -> str:
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    return jwt.encode({
        "iat": now,
        "exp": now + datetime.timedelta(minutes=10),
        "aud": "SeasonPass",
    }, settings.SEASON_PASS_JWT_SECRET, algorithm="HS256")
