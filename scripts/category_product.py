import os
import csv
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from common.models.product import Product, Category
from sqlalchemy.exc import SQLAlchemyError
from common.models.product import category_product_table

# ✅ .env 파일 로드
load_dotenv()

# ✅ 환경 변수에서 DB URL 가져오기
DATABASE_URL = os.getenv("DATABASE_URL")
CATEGORY_PRODUCTS_FILE_PATH = os.getenv("CATEGORY_PRODUCTS_FILE_PATH")

# ✅ SQLAlchemy 엔진 및 세션 생성
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def import_category_products():
    db: Session = SessionLocal()
    try:
        with open(CATEGORY_PRODUCTS_FILE_PATH, mode="r", encoding="utf-8") as file:
            reader = csv.DictReader(file)

            for row in reader:
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
                    continue

                # ✅ 관계 추가
                db.execute(category_product_table.insert().values(category_id=category_id, product_id=product_id))
                print(f"✅ Category {category_id} - Product {product_id} 관계 추가됨.")

            db.commit()
            print("\n✅ Category-Product 관계 데이터 동기화 완료!")

    except SQLAlchemyError as e:
        print(f"❌ DB 오류 발생: {e}")
        db.rollback()

    except Exception as e:
        print(f"❌ 일반 오류 발생: {e}")

    finally:
        db.close()
        print("🔌 DB 연결이 종료되었습니다.")

if __name__ == "__main__":
    import_category_products()
