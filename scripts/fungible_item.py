import os
import csv
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.exc import SQLAlchemyError
from common.models.product import FungibleItemProduct

# ✅ .env 파일 로드
load_dotenv()

# ✅ 환경 변수에서 DB URL 가져오기
DATABASE_URL = os.getenv("DATABASE_URL")
FUNGIBLE_ITEM_FILE_PATH = os.getenv("FUNGIBLE_ITEM_FILE_PATH")

# ✅ SQLAlchemy 엔진 및 세션 생성
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def parse_int(value: str):
    return int(value) if value.strip() else None

def compare_and_update_fungible_item(db: Session, csv_data: dict):
    """ 기존 DB 데이터와 CSV 데이터를 비교 후, CLI를 통해 업데이트 여부 결정 """
    existing_item = db.query(FungibleItemProduct).filter(
        FungibleItemProduct.product_id == csv_data["product_id"],
        FungibleItemProduct.fungible_item_id == csv_data["fungible_item_id"]
    ).first()

    if existing_item:
        changes = {}

        for key, value in csv_data.items():
            if getattr(existing_item, key) != value:
                changes[key] = (getattr(existing_item, key), value)

        if changes:
            print(f"\n🔍 기존 FungibleItemProduct 변경 사항 발견 (Product ID: {existing_item.product_id}, Item ID: {existing_item.fungible_item_id}):")
            for field, (old, new) in changes.items():
                print(f"  - {field}: 기존({old}) → 변경({new})")

            confirm = input("변경을 적용하시겠습니까? (y/n): ").strip().lower()
            if confirm == "y":
                for field, (_, new_value) in changes.items():
                    setattr(existing_item, field, new_value)
                db.commit()
                print(f"✅ FungibleItemProduct 업데이트 완료! (Product ID: {existing_item.product_id}, Item ID: {existing_item.fungible_item_id})")
            else:
                print("⏩ 변경 사항이 적용되지 않았습니다.")
    else:
        new_item = FungibleItemProduct(**csv_data)
        db.add(new_item)
        print(f"🆕 새로운 FungibleItemProduct 추가 (Product ID: {csv_data['product_id']}, Item ID: {csv_data['fungible_item_id']})")

def import_fungible_items():
    db: Session = SessionLocal()
    try:
        with open(FUNGIBLE_ITEM_FILE_PATH, mode="r", encoding="utf-8") as file:
            reader = csv.DictReader(file)

            for row in reader:
                csv_data = {
                    "product_id": parse_int(row["product_id"]),
                    "sheet_item_id": parse_int(row["sheet_item_id"]),
                    "name": row["name"],
                    "fungible_item_id": row["fungible_item_id"],
                    "amount": parse_int(row["amount"].replace(",", ""))
                }

                compare_and_update_fungible_item(db, csv_data)

            db.commit()
            print("\n✅ FungibleItemProduct 데이터 동기화 완료!")

    except SQLAlchemyError as e:
        print(f"❌ DB 오류 발생: {e}")
        db.rollback()

    except Exception as e:
        print(f"❌ 일반 오류 발생: {e}")

    finally:
        db.close()
        print("🔌 DB 연결이 종료되었습니다.")

if __name__ == "__main__":
    import_fungible_items()
