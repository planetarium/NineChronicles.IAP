import os
import csv
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from common.models.product import Product, Category
from sqlalchemy.exc import SQLAlchemyError
from common.models.product import category_product_table
from typing import Tuple

# ✅ .env 파일 로드
load_dotenv()

# ✅ 환경 변수에서 DB URL 가져오기
DATABASE_URL = os.getenv("DATABASE_URL")
CATEGORY_PRODUCTS_FILE_PATH = os.getenv("CATEGORY_PRODUCTS_FILE_PATH")

def process_category_product_row(db: Session, row: dict) -> bool:
    """
    카테고리-상품 관계를 처리합니다.

    Args:
        db: 데이터베이스 세션
        row: CSV 행 데이터

    Returns:
        bool: 새로운 관계가 추가되었으면 True, 이미 존재하면 False
    """
    category_id = int(row["category_id"])
    product_id = int(row["product_id"])

    # ✅ 이미 추가된 관계인지 확인
    existing_relation = db.execute(
        category_product_table.select().where(
            (category_product_table.c.category_id == category_id) &
            (category_product_table.c.product_id == product_id)
        )
    ).fetchone()

    if existing_relation:
        print(f"⏩ Category {category_id} - Product {product_id} 관계가 이미 존재합니다. 건너뜁니다.")
        return False

    # ✅ 관계 추가
    db.execute(category_product_table.insert().values(category_id=category_id, product_id=product_id))
    print(f"✅ Category {category_id} - Product {product_id} 관계 추가됨.")
    return True

def import_category_products_from_csv(db: Session, csv_path: str) -> Tuple[int, int]:
    """
    CSV 파일에서 카테고리-상품 관계를 가져와 데이터베이스에 임포트합니다.

    Args:
        db: 데이터베이스 세션
        csv_path: CSV 파일 경로

    Returns:
        Tuple[int, int]: (처리된 관계 수, 추가된 관계 수)
    """
    processed_count = 0
    added_count = 0

    try:
        with open(csv_path, mode="r", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                processed_count += 1
                if process_category_product_row(db, row):
                    added_count += 1

            db.commit()
            print(f"\n✅ Category-Product 관계 데이터 동기화 완료! (처리: {processed_count}, 추가: {added_count})")
            return processed_count, added_count

    except Exception as e:
        db.rollback()
        raise e

def import_category_products():
    """CLI 도구용 임포트 함수"""
    if not CATEGORY_PRODUCTS_FILE_PATH:
        raise ValueError("CATEGORY_PRODUCTS_FILE_PATH environment variable is required")

    if not DATABASE_URL:
        raise ValueError("DATABASE_URL environment variable is required")

    engine = create_engine(DATABASE_URL)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db: Session = SessionLocal()

    try:
        import_category_products_from_csv(db, CATEGORY_PRODUCTS_FILE_PATH)
    finally:
        db.close()
        print("🔌 DB 연결이 종료되었습니다.")

if __name__ == "__main__":
    import_category_products()
