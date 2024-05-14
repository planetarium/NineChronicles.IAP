import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import scoped_session, sessionmaker

from common.models.product import Product
from common.models.receipt import Receipt
from common.models.user import AvatarLevel


def run(DB_URI: str):
    engine = create_engine(DB_URI)
    sess = scoped_session(sessionmaker(bind=engine))
    level_product_list = sess.scalars(select(Product).where(Product.required_level.isnot(None))).fetchall()
    product_level_dict = {x.id: x.required_level for x in level_product_list}
    print(product_level_dict)
    receipt_list = sess.scalars(
        select(Receipt).where(Receipt.product_id.in_([x.id for x in level_product_list]))
    ).fetchall()

    avatar_level_dict = {}
    for receipt in receipt_list:
        if (receipt.avatar_addr, receipt.planet_id) not in avatar_level_dict:
            avatar_level_dict[(receipt.agent_addr, receipt.avatar_addr, receipt.planet_id)] = product_level_dict[
                receipt.product_id]
        else:
            avatar_level_dict[(receipt.agent_addr, receipt.avatar_addr, receipt.planet_id)] = max(
                avatar_level_dict[(receipt.agent_addr, receipt.avatar_addr, receipt.planet_id)],
                product_level_dict[receipt.product_id]
            )
    for k, v in avatar_level_dict.items():
        sess.add(AvatarLevel(
            agent_addr=k[0],
            avatar_addr=k[1],
            planet_id=k[2],
            level=v
        ))
    sess.commit()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python cache_avatar_level.py [DB_URI]")
        exit(1)
    _, db_uri = sys.argv
    run(db_uri)
