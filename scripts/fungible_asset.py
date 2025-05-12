import os
import csv
from typing import Tuple
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from common.models.product import Product, FungibleAssetProduct
from sqlalchemy.exc import SQLAlchemyError

# ✅ .env 파일 로드
load_dotenv()

# ✅ 환경 변수에서 DB URL 가져오기
DATABASE_URL = os.getenv("DATABASE_URL")
FUNGIBLE_ASSET_FILE_PATH = os.getenv("FUNGIBLE_ASSET_FILE_PATH")

def parse_float(value: str) -> float | None:
    """문자열을 float로 변환합니다."""
    try:
        return float(value.replace(",", "")) if value.strip() else None
    except ValueError:
        return None

def parse_int(value: str) -> int | None:
    """문자열을 int로 변환합니다."""
    try:
        return int(value.replace(",", "")) if value.strip() else None
    except ValueError:
        return None

def process_fungible_asset_row(db: Session, row: dict) -> bool:
    """
    대체 가능 자산 데이터를 처리합니다.

    Args:
        db: 데이터베이스 세션
        row: CSV 행 데이터

    Returns:
        bool: 데이터가 추가되거나 업데이트되면 True
    """
    csv_data = {
        "product_id": parse_int(row["product_id"]),
        "ticker": row["ticker"],
        "amount": parse_float(row["amount"]),
        "decimal_places": parse_int(row["decimal_places"]),
    }

    # 기존 데이터 확인
    existing_asset = db.query(FungibleAssetProduct).filter(
        FungibleAssetProduct.product_id == csv_data["product_id"],
        FungibleAssetProduct.ticker == csv_data["ticker"]
    ).first()

    if existing_asset:
        # 변경사항 확인
        changes = {}
        for key, value in csv_data.items():
            if getattr(existing_asset, key) != value:
                changes[key] = (getattr(existing_asset, key), value)

        if changes:
            print(f"\n🔍 Product ID {csv_data['product_id']} - {csv_data['ticker']} 변경 사항 발견:")
            for field, (old, new) in changes.items():
                print(f"  - {field}: 기존({old}) → 변경({new})")
                setattr(existing_asset, field, new)
            print(f"✅ 업데이트 완료!")
            return True
        return False
    else:
        # 새로운 데이터 추가
        new_asset = FungibleAssetProduct(**csv_data)
        db.add(new_asset)
        print(f"🆕 새로운 FungibleAsset 추가: Product ID {csv_data['product_id']} - {csv_data['ticker']}")
        return True

def import_fungible_assets_from_csv(db: Session, csv_path: str) -> Tuple[int, int]:
    """
    CSV 파일에서 대체 가능 자산 데이터를 가져와 데이터베이스에 임포트합니다.

    Args:
        db: 데이터베이스 세션
        csv_path: CSV 파일 경로

    Returns:
        Tuple[int, int]: (처리된 데이터 수, 변경된 데이터 수)
    """
    processed_count = 0
    changed_count = 0

    try:
        with open(csv_path, mode="r", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                processed_count += 1
                if process_fungible_asset_row(db, row):
                    changed_count += 1

            db.commit()
            print(f"\n✅ FungibleAsset 데이터 동기화 완료! (처리: {processed_count}, 변경: {changed_count})")
            return processed_count, changed_count

    except Exception as e:
        db.rollback()
        raise e

def import_fungible_assets():
    """CLI 도구용 임포트 함수"""
    if not FUNGIBLE_ASSET_FILE_PATH:
        raise ValueError("FUNGIBLE_ASSET_FILE_PATH environment variable is required")

    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is required")

    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db: Session = SessionLocal()

    try:
        import_fungible_assets_from_csv(db, FUNGIBLE_ASSET_FILE_PATH)
    finally:
        db.close()
        print("🔌 DB 연결이 종료되었습니다.")

if __name__ == "__main__":
    import_fungible_assets()
