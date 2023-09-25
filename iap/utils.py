import datetime

from sqlalchemy import func, Date, cast

from common import logger
from common.enums import ReceiptStatus
from common.models.receipt import Receipt


def get_purchase_count(sess, agent_addr: str, product_id: int, hour_limit: int = 0) -> int:
    """
    Scan purchase history and get purchase count in given time limit.

    :param sess: DB Session
    :param agent_addr: 9c Agent address
    :param product_id: Target product ID to scan.
    :param hour_limit: purchase history limit in hours. 24 for daily limit, 168(24*7) for weekly limit
    :return:
    """
    purchase_count = (
        sess.query(func.count(Receipt.id)).filter_by(product_id=product_id, agent_addr=agent_addr)
        .filter(Receipt.status.in_(
            (ReceiptStatus.INIT, ReceiptStatus.VALIDATION_REQUEST, ReceiptStatus.VALID)
        ))
    )

    start = None
    if hour_limit:
        # NOTE: Subtract 24 hours from incoming hour_limit.
        #  Because last 24 hours means today. Using `datetime.date()` function, timedelta -24 hours makes yesterday.
        start = (datetime.datetime.utcnow() - datetime.timedelta(hours=hour_limit - 24)).date()
        purchase_count = purchase_count.filter(cast(Receipt.purchased_at, Date) >= start)

    purchase_count = purchase_count.scalar()
    logger.debug(
        f"Agent {agent_addr} purchased product {product_id} {purchase_count} times in {hour_limit} hours from {start or 'Anytime'}"
    )
    return purchase_count
