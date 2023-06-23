import datetime

from sqlalchemy import func

from common import logger
from common.models.receipt import Receipt


def get_purchase_count(sess, agent_addr: str, product_id: int, hour_limit: int) -> int:
    """
    Scan purchase history and get purchase count in given time limit.

    :param sess: DB Session
    :param agent_addr: 9c Agent address
    :param product_id: Target product ID to scan.
    :param hour_limit: purchase history limit in hours. 24 for daily limit, 168(24*7) for weekly limit
    :return:
    """
    start = datetime.datetime.utcnow() - datetime.timedelta(hours=hour_limit)
    purchase_count = (sess.query(func.count(Receipt.id)).filter_by(product_id=product_id, agent_addr=agent_addr)
                      .filter(Receipt.created_at >= start)
                      ).scalar()
    logger.debug(
        f"Agent {agent_addr} purchased product {product_id} {purchase_count} times in {hour_limit} hours from {start}"
    )
    return purchase_count
