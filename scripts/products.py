import os
import csv
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from common.models.product import Product, ProductRarity, ProductAssetUISize, ProductType
from sqlalchemy.exc import SQLAlchemyError

# ✅ .env 파일 로드
load_dotenv()

# ✅ 환경 변수에서 DB URL 가져오기
DATABASE_URL = os.getenv("DATABASE_URL")
PRODUCTS_FILE_PATH = os.getenv("PRODUCTS_FILE_PATH")

# ✅ SQLAlchemy 엔진 및 세션 생성
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def parse_boolean(value: str) -> bool:
    return value.strip().upper() == "TRUE"

def parse_enum(enum_class, value: str):
    if value:
        try:
            return enum_class[value.strip().upper()]
        except KeyError:
            print(f"⚠️ {value} is not a valid {enum_class.__name__}. Using default.")
    return None

def parse_int(value: str):
    return int(value) if value.strip() else None

def parse_float(value: str):
    return float(value) if value.strip() else None

def parse_datetime(value: str):
    try:
        return datetime.fromisoformat(value) if value.strip() else None
    except ValueError:
        return None

def compare_and_update_product(db: Session, csv_data: dict):
    """ 기존 DB 데이터와 CSV 데이터를 비교 후, CLI를 통해 업데이트 여부 결정 """
    existing_product = db.query(Product).filter(Product.id == csv_data["id"]).first()

    if existing_product:
        changes = {}

        for key, value in csv_data.items():
            if getattr(existing_product, key) != value:
                changes[key] = (getattr(existing_product, key), value)

        if changes:
            print(f"\n🔍 기존 Product ID {existing_product.id} 변경 사항 발견:")
            for field, (old, new) in changes.items():
                print(f"  - {field}: 기존({old}) → 변경({new})")

            confirm = input("변경을 적용하시겠습니까? (y/n): ").strip().lower()
            if confirm == "y":
                for field, (_, new_value) in changes.items():
                    setattr(existing_product, field, new_value)
                db.commit()
                print(f"✅ Product ID {existing_product.id} 업데이트 완료!")
            else:
                print("⏩ 변경 사항이 적용되지 않았습니다.")
    else:
        new_product = Product(**csv_data)
        db.add(new_product)
        print(f"🆕 새로운 Product 추가: ID {csv_data['id']}")

def import_products():
    db: Session = SessionLocal()
    try:
        with open(PRODUCTS_FILE_PATH, mode="r", encoding="utf-8") as file:
            reader = csv.DictReader(file)

            for row in reader:
                csv_data = {
                    "id": parse_int(row["id"]),
                    "name": row["name"],
                    "google_sku": row["google_sku"],
                    "apple_sku": row["apple_sku"],
                    "apple_sku_k": row["apple_sku_k"],
                    "daily_limit": parse_int(row["daily_limit"]),
                    "weekly_limit": parse_int(row["weekly_limit"]),
                    "account_limit": parse_int(row["account_limit"]),
                    "order": parse_int(row["order"]),
                    "active": parse_boolean(row["active"]),
                    "open_timestamp": parse_datetime(row["open_timestamp"]),
                    "close_timestamp": parse_datetime(row["close_timestamp"]),
                    "discount": parse_float(row["discount"]),
                    "rarity": parse_enum(ProductRarity, row["rarity"]),
                    "path": "=",
                    "l10n_key": "=",
                    "size": parse_enum(ProductAssetUISize, row["size"]),
                    "bg_path": None,
                    "popup_path_key": row["popup_path_key"] if row["popup_path_key"] else None,
                    "required_level": parse_int(row["required_level"]),
                    "product_type": parse_enum(ProductType, row["product_type"]),
                    "mileage": parse_int(row["mileage"]),
                    "mileage_price": parse_int(row["mileage_price"])
                }

                compare_and_update_product(db, csv_data)

            db.commit()
            print("\n✅ CSV 데이터 동기화 완료!")

    except SQLAlchemyError as e:
        print(f"❌ DB 오류 발생: {e}")
        db.rollback()

    except Exception as e:
        print(f"❌ 일반 오류 발생: {e}")

    finally:
        db.close()
        print("🔌 DB 연결이 종료되었습니다.")

if __name__ == "__main__":
    import_products()
