from sqlalchemy import create_engine, select, delete
from sqlalchemy.orm import scoped_session, sessionmaker

from common.models.mileage import Mileage, MileageHistory


def move(db_uri: str, dry_run: bool = True):
    print(f"Move mileage to history for {db_uri.split('@')[-1]}")
    if dry_run:
        print("Dry run. Do not move data.")
    else:
        proceed = input("You've selected update mode. This will update values into DB. Proceed? [y/N] : ")
        print(proceed)
        if proceed in ("y", "Y"):
            pass
        else:
            print("Cancel")
            return

    engine = create_engine(db_uri)
    sess = scoped_session(sessionmaker(bind=engine))
    mileage_list = sess.scalars(select(Mileage)).fetchall()
    history_list = []
    print(f"{len(mileage_list)} mileages to save")
    for m in mileage_list:
        history_list.append(MileageHistory(**m.__dict__))

    print(f"{len(history_list)}/{len(mileage_list)} moved to history")
    if len(history_list) != len(mileage_list):
        print("Mileage and history count not match. Abort.")
        return

    if dry_run:
        print("Dry run. Do not save history and delete mileage.")
    else:
        sess.add_all(history_list)
        sess.commit()
        print("History saved. Delete mileage data")
        sess.execute(delete(Mileage))
        sess.commit()
        print("Mileage deleted. Merge mileage from history.")


