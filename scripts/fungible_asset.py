import os
import csv
from datetime import datetime
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from common.models.product import FungibleAssetProduct
from sqlalchemy.exc import SQLAlchemyError

# ✅ .env 파일 로드
load_dotenv()

# ✅ 환경 변수에서 DB URL 가져오기
DATABASE_URL = os.getenv("DATABASE_URL")
FUNGIBLE_ASSET_FILE_PATH = os.getenv("FUNGIBLE_ASSET_FILE_PATH")

# ✅ SQLAlchemy 엔진 및 세션 생성
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def parse_int(value: str):
    return int(value) if value.strip() else None

def parse_float(value: str):
    return float(value) if value.strip() else None

def compare_and_update_fungible_asset(db: Session, csv_data: dict):
    """ 기존 DB 데이터와 CSV 데이터를 비교 후, CLI를 통해 업데이트 여부 결정 """
    existing_fap = db.query(FungibleAssetProduct).filter(
        FungibleAssetProduct.product_id == csv_data["product_id"],
        FungibleAssetProduct.ticker == csv_data["ticker"]
    ).first()

    if existing_fap:
        changes = {}

        for key, value in csv_data.items():
            if getattr(existing_fap, key) != value:
                changes[key] = (getattr(existing_fap, key), value)

        if changes:
            print(f"\n🔍 기존 FungibleAssetProduct 변경 사항 발견 (Product ID: {existing_fap.product_id}, Ticker: {existing_fap.ticker}):")
            for field, (old, new) in changes.items():
                print(f"  - {field}: 기존({old}) → 변경({new})")

            confirm = input("변경을 적용하시겠습니까? (y/n): ").strip().lower()
            if confirm == "y":
                for field, (_, new_value) in changes.items():
                    setattr(existing_fap, field, new_value)
                db.commit()
                print(f"✅ FungibleAssetProduct 업데이트 완료! (Product ID: {existing_fap.product_id}, Ticker: {existing_fap.ticker})")
            else:
                print("⏩ 변경 사항이 적용되지 않았습니다.")
    else:
        new_fap = FungibleAssetProduct(**csv_data)
        db.add(new_fap)
        print(f"🆕 새로운 FungibleAssetProduct 추가 (Product ID: {csv_data['product_id']}, Ticker: {csv_data['ticker']})")

def import_fungible_assets():
    db: Session = SessionLocal()
    try:
        with open(FUNGIBLE_ASSET_FILE_PATH, mode="r", encoding="utf-8") as file:
            reader = csv.DictReader(file)

            for row in reader:
                csv_data = {
                    "product_id": parse_int(row["product_id"]),
                    "ticker": row["ticker"],
                    "amount": parse_float(row["amount"].replace(",", "")),
                    "decimal_places": parse_int(row["decimal_places"]),
                }

                compare_and_update_fungible_asset(db, csv_data)

            db.commit()
            print("\n✅ FungibleAssetProduct 데이터 동기화 완료!")

    except SQLAlchemyError as e:
        print(f"❌ DB 오류 발생: {e}")
        db.rollback()

    except Exception as e:
        print(f"❌ 일반 오류 발생: {e}")

    finally:
        db.close()
        print("🔌 DB 연결이 종료되었습니다.")

if __name__ == "__main__":
    import_fungible_assets()
