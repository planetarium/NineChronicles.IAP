import sys

from sqlalchemy import create_engine, select, delete
from sqlalchemy.orm import scoped_session, sessionmaker

from common.models.mileage import Mileage
from common.utils.receipt import PlanetID


def merge(db_uri: str, dry_run: bool = True):
    print(f"Merge mileages for {db_uri.split('@')[-1]}")
    if dry_run:
        print("Dry run mode. This will not update DB.")
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

    print("Delete old merged data")
    sess.execute(delete(Mileage).where(Mileage.planet_id.is_(None)))

    all_mileage_list = sess.scalars(select(Mileage)).fetchall()
    print(f"Total {len(all_mileage_list)} mileages found.")

    merged = {}
    print(f"{len(all_mileage_list)} mileages to merge")

    for i, m in enumerate(all_mileage_list):
        target = merged.get(m.agent_addr)
        if not target:
            merged[m.agent_addr] = target = Mileage(agent_addr=m.agent_addr, planet_id=None, mileage=0)
        prev = target.mileage
        target.mileage += m.mileage
        print(
            f"[{i + 1:4d}/{len(all_mileage_list):4d}] [{PlanetID(m.planet_id).name}] "
            f"{target.agent_addr}: {prev} + {m.mileage} = {target.mileage}"
        )

    if dry_run:
        print("Dry run mode. Do not update to DB")
    else:
        print("Update to DB")
        sess.add_all(merged.values())
        sess.commit()


if __name__ == "__main__":
    merge(sys.argv[1],
          dry_run=len(sys.argv) > 2 and sys.argv[2].lower() in ("dryrun", "dry_run", "dry-run", "dry")
          )
