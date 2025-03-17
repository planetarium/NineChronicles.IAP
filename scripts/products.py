import os
import csv
import argparse
from datetime import datetime, timezone
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

def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(description="Import products from CSV to database")
    parser.add_argument("--environment", required=True, choices=['internal', 'mainnet'], 
                        help="Specify whether this is for internal or mainnet environment")
    parser.add_argument("--csv-path", 
                        default=PRODUCTS_FILE_PATH,
                        help="Path to the CSV file containing product data")
    parser.add_argument("--db-uri", 
                        default=DATABASE_URL,
                        help="Database URI (e.g., postgresql://user:password@host/database)")
    
    args = parser.parse_args()
    
    # Validate required parameters
    if not args.csv_path:
        parser.error("CSV file path is required. Provide with --csv-path or set PRODUCTS_FILE_PATH environment variable")
    if not args.db_uri:
        parser.error("Database URI is required. Provide with --db-uri or set DATABASE_URL environment variable")
    
    return args

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
        # Parse to datetime then ensure it has UTC timezone
        dt = datetime.fromisoformat(value) if value.strip() else None
        if dt and dt.tzinfo is None:
            # If no timezone info, assume UTC
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None

def compare_and_update_product(db: Session, csv_data: dict, is_internal: bool):
    """ 기존 DB 데이터와 CSV 데이터를 비교 후, CLI를 통해 업데이트 여부 결정 """
    existing_product = db.query(Product).filter(Product.id == csv_data["id"]).first()

    # For internal environment, adjust open_timestamp if it's in the future
    current_time_utc = datetime.now(timezone.utc)
    if is_internal and csv_data["open_timestamp"] and csv_data["open_timestamp"] > current_time_utc:
        old_timestamp = csv_data["open_timestamp"]
        csv_data["open_timestamp"] = current_time_utc
        print(f"🕒 Internal environment detected: Adjusting open_timestamp from {old_timestamp} to {csv_data['open_timestamp']} (UTC)")

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

def import_products(csv_path, db_uri, environment):
    # Get user confirmation about environment
    print(f"\n🌐 Selected environment: {environment.upper()}")
    print(f"⏰ Current UTC time: {datetime.now(timezone.utc)}")
    confirm = input(f"계속 진행하시겠습니까? 이 작업은 {environment.upper()} 환경에 영향을 미칩니다. (y/n): ").strip().lower()
    if confirm != "y":
        print("⏩ 작업이 취소되었습니다.")
        return
    
    # Create DB session with provided URI
    engine = create_engine(db_uri)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db: Session = SessionLocal()
    
    is_internal = environment == 'internal'
    
    try:
        with open(csv_path, mode="r", encoding="utf-8") as file:
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

                compare_and_update_product(db, csv_data, is_internal)

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
    args = parse_args()
    import_products(args.csv_path, args.db_uri, args.environment)
