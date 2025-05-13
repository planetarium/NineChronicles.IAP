from datetime import datetime, timezone
from typing import Tuple
from sqlalchemy.orm import Session
import csv
from common.models.product import FungibleAssetProduct, FungibleItemProduct, Product, ProductRarity, ProductAssetUISize, ProductType, category_product_table

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

def process_csv_row(row: dict, is_internal: bool) -> dict:
    """CSV 행을 파싱하여 Product 모델에 맞는 데이터로 변환합니다."""
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

    # For internal environment, adjust open_timestamp if it's in the future
    current_time_utc = datetime.now(timezone.utc)
    if is_internal and csv_data["open_timestamp"] and csv_data["open_timestamp"] > current_time_utc:
        old_timestamp = csv_data["open_timestamp"]
        csv_data["open_timestamp"] = current_time_utc
        print(f"🕒 Internal environment detected: Adjusting open_timestamp from {old_timestamp} to {csv_data['open_timestamp']} (UTC)")

    return csv_data

def compare_and_update_product(db: Session, csv_data: dict, is_internal: bool, interactive: bool = True) -> bool:
    """기존 DB 데이터와 CSV 데이터를 비교 후 업데이트합니다."""
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

            if not interactive or input("변경을 적용하시겠습니까? (y/n): ").strip().lower() == "y":
                for field, (_, new_value) in changes.items():
                    setattr(existing_product, field, new_value)
                print(f"✅ Product ID {existing_product.id} 업데이트 완료!")
                return True
            else:
                print("⏩ 변경 사항이 적용되지 않았습니다.")
                return False
    else:
        new_product = Product(**csv_data)
        db.add(new_product)
        print(f"🆕 새로운 Product 추가: ID {csv_data['id']}")
        return True


def import_products_from_csv(db: Session, csv_path: str, environment: str, interactive: bool = True) -> tuple[int, int]:
    """
    CSV 파일에서 상품 데이터를 가져와 데이터베이스에 임포트합니다.

    Args:
        db: 데이터베이스 세션
        csv_path: CSV 파일 경로
        environment: 'internal' 또는 'mainnet'
        interactive: 사용자 입력을 받을지 여부

    Returns:
        tuple[int, int]: (처리된 상품 수, 업데이트된 상품 수)
    """
    if environment not in ['internal', 'mainnet']:
        raise ValueError("environment must be either 'internal' or 'mainnet'")

    is_internal = environment == 'internal'
    processed_count = 0
    updated_count = 0

    try:
        with open(csv_path, mode="r", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                processed_count += 1
                csv_data = process_csv_row(row, is_internal)
                if compare_and_update_product(db, csv_data, is_internal, interactive):
                    updated_count += 1

            db.commit()
            print(f"\n✅ CSV 데이터 동기화 완료! (처리: {processed_count}, 업데이트: {updated_count})")
            return processed_count, updated_count

    except Exception as e:
        db.rollback()
        raise e

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

def process_fungible_item_row(db: Session, row: dict) -> bool:
    """
    대체 가능 아이템 데이터를 처리합니다.

    Args:
        db: 데이터베이스 세션
        row: CSV 행 데이터

    Returns:
        bool: 데이터가 추가되거나 업데이트되면 True
    """
    csv_data = {
        "product_id": parse_int(row["product_id"]),
        "sheet_item_id": parse_int(row["sheet_item_id"]),
        "name": row["name"],
        "fungible_item_id": row["fungible_item_id"],
        "amount": parse_int(row["amount"].replace(",", "")),
    }

    # 기존 데이터 확인
    existing_item = db.query(FungibleItemProduct).filter(
        FungibleItemProduct.product_id == csv_data["product_id"],
        FungibleItemProduct.fungible_item_id == csv_data["fungible_item_id"]
    ).first()

    if existing_item:
        # 변경사항 확인
        changes = {}
        for key, value in csv_data.items():
            if getattr(existing_item, key) != value:
                changes[key] = (getattr(existing_item, key), value)

        if changes:
            print(f"\n🔍 Product ID {csv_data['product_id']} - Item ID {csv_data['fungible_item_id']} 변경 사항 발견:")
            for field, (old, new) in changes.items():
                print(f"  - {field}: 기존({old}) → 변경({new})")
                setattr(existing_item, field, new)
            print(f"✅ 업데이트 완료!")
            return True
        return False
    else:
        # 새로운 데이터 추가
        new_item = FungibleItemProduct(**csv_data)
        db.add(new_item)
        print(f"🆕 새로운 FungibleItem 추가: Product ID {csv_data['product_id']} - Item ID {csv_data['fungible_item_id']}")
        return True

def import_fungible_items_from_csv(db: Session, csv_path: str) -> Tuple[int, int]:
    """
    CSV 파일에서 대체 가능 아이템 데이터를 가져와 데이터베이스에 임포트합니다.

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
                if process_fungible_item_row(db, row):
                    changed_count += 1

            db.commit()
            print(f"\n✅ FungibleItem 데이터 동기화 완료! (처리: {processed_count}, 변경: {changed_count})")
            return processed_count, changed_count

    except Exception as e:
        db.rollback()
        raise e
