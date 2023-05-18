import sys
from csv import DictReader

from sqlalchemy import create_engine, select
from sqlalchemy.orm import scoped_session, sessionmaker

from iap.models.item import Item


def set_item_from_csv_to_db(csv_path: str, db_uri: str):
    engine = create_engine(db_uri)
    sess = scoped_session(sessionmaker(engine))
    new_item_list = []
    all_item_dict = {x.id: x for x in sess.execute(select(Item)).scalars().fetchall()}

    with open(csv_path) as csv:
        reader = DictReader(csv)
        for r in reader:
            if r["id"] in all_item_dict:
                all_item_dict[r["id"]].name = r["_name"]
            else:
                new_item_list.append(Item(id=r["id"], name=r["_name"]))
    sess.add_all(new_item_list)

    sess.commit()
    print(f"{len(new_item_list)} items added, {len(all_item_dict)} items updated.")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python set_item.py [csv path] [DB URI]")
    _, csv_path, db_uri = sys.argv
    set_item_from_csv_to_db(csv_path, db_uri)
