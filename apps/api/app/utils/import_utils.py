import csv
from datetime import datetime, timezone
from typing import Optional, Tuple, Union

from fastapi import HTTPException
from shared.models.product import (
    FungibleAssetProduct,
    FungibleItemProduct,
    Price,
    GACHA_KIND_FAV,
    GACHA_KIND_ITEM,
    PAYABLE_ANY,
    PAYABLE_NCG,
    Product,
    ProductAssetUISize,
    ProductGachaEntry,
    ProductRarity,
    ProductType,
    Store,
    category_product_table,
)
from shared.models.product_voucher_grant import ProductVoucherGrant
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.grant_guard import (
    parse_point_shop_grantable,
    validate_point_shop_grantable_eligible,
)
from app.voucher_validation import (
    parse_voucher_columns,
    validate_product_voucher_eligible,
)

# (C1b) CSV의 voucher (type, count) 고정 쌍 슬롯 수. voucher_ticket_type_1..N / voucher_count_1..N.
VOUCHER_SLOTS = 3

# (PLD-1575) 포인트샵 지급 화이트리스트 컬럼. **선택 컬럼**이다 — 없는 시트도 그대로 임포트된다
#   (파서는 app/grant_guard.py 의 3상태 parse_point_shop_grantable).
POINT_SHOP_GRANTABLE_COLUMN = "point_shop_grantable"
# (PLD-1561) 포인트 판매가 컬럼. 헤더 없음=유지 / 빈칸=해제(NULL) / 값=양의 정수.
POINT_PRICE_COLUMN = "point_price"
# (PLD-1562) 10연뽑. 헤더 없음=유지 / 빈칸=유지 / 값=1 이상 정수.
GACHA_DRAW_COUNT_COLUMN = "gacha_draw_count"
# (PLD-1562) 뽑기 풀 칸의 정체성. 헤더 없음/빈칸=티커를 키로(옛 시트 호환).
#   값을 주면 **같은 티커를 수량만 다르게 여러 칸** 둘 수 있다(상품표 v0.9 재료 티어).
GACHA_SLOT_KEY_COLUMN = "slot_key"
# (PLD-1564) 결제 가능 포인트 종류. 헤더 없음/빈칸=유지 / 'ANY'|'NCG'.
POINT_PAYABLE_KINDS_COLUMN = "point_payable_kinds"
#: CSV 입력 → 저장값. 문서 어휘(PP-X)와 코드 어휘(NCG)를 **둘 다 받고 하나로 저장**한다.
PAYABLE_ALIASES = {
    PAYABLE_ANY: PAYABLE_ANY,
    "BOTH": PAYABLE_ANY,  # "PP-S·PP-X 모두" 를 그대로 옮겨 적는 경우
    PAYABLE_NCG: PAYABLE_NCG,
    "PP_X": PAYABLE_NCG,
    "PP-X": PAYABLE_NCG,
    "PPX": PAYABLE_NCG,
}
# 추첨은 전역 advisory lock 안에서 돈다 — 큰 값은 그 구간을 늘려 모든 지급 요청을 줄 세우고
# 결과 JSON 도 주문마다 영구 저장된다. 실무상 10연이 최대이므로 넉넉히 100.
MAX_GACHA_DRAW_COUNT = 100


def parse_boolean(value: str) -> bool:
    return value.strip().upper() == "TRUE"


def parse_enum(enum_class, value: str):
    if value:
        try:
            return enum_class[value.strip().upper()]
        except KeyError:
            print(f"⚠️ {value} is not a valid {enum_class.__name__}. Using default.")
    return None


def parse_int(value: str, default=None):
    if not value.strip():
        return default
    # 콤마 제거 후 int로 변환
    return int(value.replace(",", ""))


def parse_float(value: str):
    if not value.strip():
        return None
    # 콤마 제거 후 float으로 변환
    return float(value.replace(",", ""))


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
        # order is NOT NULL with default -1 in the DB; blank CSV cells must
        # coalesce so UPDATEs don't send NULL and violate the constraint.
        # Using the `default=` arg (not `or -1`) preserves a legitimate 0.
        "order": parse_int(row["order"], default=-1),
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
        # mileage is NOT NULL with default 0 in the DB — see Product model.
        # Same rationale as order above.
        "mileage": parse_int(row["mileage"], default=0),
        "mileage_price": parse_int(row["mileage_price"]),
    }

    # (PLD-1564) 결제 가능 포인트 종류. **선택 컬럼 + 3상태**다 — 헤더 없음/빈칸은 유지.
    #   2상태로 읽으면 이 컬럼 없는 기존 시트를 재임포트하는 순간 가챠의 'NCG' 제약이
    #   조용히 'ANY' 로 풀린다. 그건 봇이 무상 포인트로 가챠를 도는 문이 열리는 것이다.
    if POINT_PAYABLE_KINDS_COLUMN in row:
        raw = (row.get(POINT_PAYABLE_KINDS_COLUMN) or "").strip().upper()
        if raw:
            # 기획 문서는 PP-S / **PP-X** 로 말하고 값을 넣는 사람은 그 문서를 본다.
            #   저장은 `NCG` 하나로 하되(코드의 RewardKind 와 같은 이름) **입력은 문서 어휘도
            #   받는다** — 번역이 필요한 경계가 곧 실수가 나는 자리다.
            #   반대 방향(PP_S)은 별칭을 두지 않는다: 'PP_S 전용' 값 자체가 없다.
            canonical = PAYABLE_ALIASES.get(raw)
            if canonical is None:
                raise ValueError(
                    f"product {csv_data['id']}: {POINT_PAYABLE_KINDS_COLUMN} 는"
                    f" {sorted(PAYABLE_ALIASES)} 중 하나여야 한다 (got {raw!r})"
                )
            csv_data[POINT_PAYABLE_KINDS_COLUMN] = canonical

    # (PLD-1562) 10연뽑. **선택 컬럼**이다 — 헤더가 없으면 건드리지 않는다(기존 시트가
    #   전 상품의 추첨 횟수를 1 로 되돌리면 10연이 조용히 단연이 된다).
    if GACHA_DRAW_COUNT_COLUMN in row:
        raw = (row.get(GACHA_DRAW_COUNT_COLUMN) or "").strip()
        if raw:
            draws = parse_int(raw)
            if draws is None or not 1 <= draws <= MAX_GACHA_DRAW_COUNT:
                # 상한이 필요한 이유: 추첨은 전 네임스페이스를 직렬화하는 advisory lock
                #   **안**에서 돈다. 오타 `100000` 하나면 그 1초짜리 CPU 구간 동안 모든
                #   지급 요청이 줄을 서고, 결과 JSON 도 주문마다 수 MB 씩 영구 저장된다.
                raise ValueError(
                    f"product {csv_data['id']}: {GACHA_DRAW_COUNT_COLUMN} 는"
                    f" 1~{MAX_GACHA_DRAW_COUNT} 정수여야 한다 (got {raw!r})"
                )
            csv_data[GACHA_DRAW_COUNT_COLUMN] = draws

    # (PLD-1561) 포인트샵 판매가. **선택 컬럼**이다 — 헤더가 없으면 csv_data 에 넣지 않아
    #   compare_and_update_product 가 이 컬럼을 아예 건드리지 않는다(기존 값 유지).
    #   빈 칸은 "포인트로 팔지 않음"(NULL)로 **명시적 해제**다 — 값을 지우는 유일한 방법이라
    #   유지와 구분되어야 하므로, 헤더 유무로 갈린다.
    if POINT_PRICE_COLUMN in row:
        raw = (row.get(POINT_PRICE_COLUMN) or "").strip()
        if raw == "":
            csv_data[POINT_PRICE_COLUMN] = None
        else:
            price = parse_int(raw)
            # 0·음수는 "공짜 주문 + 원장 0행"(감사 불가) 또는 마이너스 차감이 된다.
            if price is None or price <= 0:
                raise ValueError(
                    f"product {csv_data['id']}: {POINT_PRICE_COLUMN} 는 양의 정수여야 한다"
                    f" (got {raw!r}). 팔지 않으려면 빈 칸으로 둘 것."
                )
            csv_data[POINT_PRICE_COLUMN] = price

    # (PLD-1575) 포인트샵 지급 화이트리스트. 값이 있을 때만 csv_data 에 넣는다 —
    #   키가 없으면 compare_and_update_product 가 이 컬럼을 아예 건드리지 않고(유지),
    #   신규 상품이면 모델 default(False)로 들어간다(화이트리스트 밖에서 시작 = fail-closed).
    grantable = parse_point_shop_grantable(row.get(POINT_SHOP_GRANTABLE_COLUMN))
    if grantable is not None:
        if grantable:
            # 켜는 경우에만 상품유형 검사(끄는 건 항상 허용 — 킬스위치를 막으면 안 된다).
            #   이 행이 **쓰려는** product_type/sku 기준이다(같은 임포트에서 유형이 바뀔 수 있다).
            try:
                validate_point_shop_grantable_eligible(
                    csv_data["id"], csv_data["product_type"], csv_data["google_sku"]
                )
            except HTTPException as e:
                raise ValueError(f"product {csv_data['id']}: {e.detail}")
        # ⚠️ 이 플래그를 켜면 **그 상품은 곧바로 지급 가능**해진다. 예전에는 뒤에 발행량
        #   상한이 한 겹 더 있었지만 지금은 없다(제거 근거는 app/grant_guard.py 도커스트링).
        csv_data[POINT_SHOP_GRANTABLE_COLUMN] = grantable

    # For internal environment, adjust open_timestamp if it's in the future
    current_time_utc = datetime.now(timezone.utc)
    if (
        is_internal
        and csv_data["open_timestamp"]
        and csv_data["open_timestamp"] > current_time_utc
    ):
        old_timestamp = csv_data["open_timestamp"]
        csv_data["open_timestamp"] = current_time_utc
        print(
            f"🕒 Internal environment detected: Adjusting open_timestamp from {old_timestamp} to {csv_data['open_timestamp']} (UTC)"
        )

    return csv_data


def compare_and_update_product(
    db: Session, csv_data: dict, is_internal: bool, interactive: bool = True
) -> bool:
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


def _apply_voucher_row(
    db: Session,
    product_id: int,
    row: dict,
    voucher_tables: Optional[dict],
    voucher_cap: Optional[int],
    product_type: Optional[Union[ProductType, str]] = None,
) -> None:
    """
    (C1b) CSV 행의 voucher 컬럼을 product_voucher_grant에 적용(REPLACE 시맨틱).
      빈칸=유지 · '-'=전체 비활성 · 값=나열된 것만 active, 나머지는 active=False.
      ⚠️ 나열 안 된/제거된 매핑은 **hard-delete 대신 active=False**(복구 가능·데이터 보존).
         단 active=False도 이미 enroll된 in-flight 결제는 "no active mapping (retry)"로
         PENDING stall될 수 있음(운영 인지 필요 — CRUD delete와 동일 caveat).
      C1/C3-lite는 parse_voucher_columns(pure)에서 강제 — 위반 시 상품 컨텍스트 붙여 ValueError
      (import 전체 트랜잭션이 rollback → 원자적 거부).
    """
    # 고정 슬롯 (type_i, count_i) 쌍 수집 — 세미콜론 정렬 불필요.
    pairs = [
        (row.get(f"voucher_ticket_type_{i}"), row.get(f"voucher_count_{i}"))
        for i in range(1, VOUCHER_SLOTS + 1)
    ]
    if all(((t or "").strip() == "") for (t, _) in pairs):
        return  # 전 슬롯 빈칸 = 유지 — 정책 fetch/검증 불필요
    if voucher_tables is None:
        raise ValueError(
            f"product {product_id}: voucher 컬럼이 있으나 라이브 정책 미로드"
            " (portal_prize_tables_url 확인)"
        )
    if product_id is None:
        # blank id(신규상품 autoincrement)면 grant FK가 None → IntegrityError. voucher 행은 id 필수.
        raise ValueError(
            f"voucher 매핑 행은 product id가 필요합니다(빈칸 불가, sku={row.get('google_sku')})"
        )
    try:
        desired = parse_voucher_columns(pairs, voucher_tables, voucher_cap)
    except HTTPException as e:
        raise ValueError(f"product {product_id}: {e.detail}")
    if desired is None:
        return
    # (C6) 매핑을 **붙이는** 경우에만 상품유형 검사. desired=={} 는 '-'(전체 비활성)이라 통과시켜야
    #   잘못 붙은 매핑을 CSV 로 되돌릴 수 있다(막으면 정리 수단이 없어지고, 그 시트를 쓰는 다음
    #   정기 임포트가 통째로 롤백된다). 검사는 이 행이 **쓰려는** product_type 기준.
    if desired:
        try:
            validate_product_voucher_eligible(product_id, product_type)
        except HTTPException as e:
            raise ValueError(f"product {product_id}: {e.detail}")
    db.flush()  # 기존 상품이면 no-op, 신규(명시 id)면 FK 위해 먼저 반영
    existing = {
        r.ticket_type: r
        for r in db.execute(
            select(ProductVoucherGrant).where(
                ProductVoucherGrant.product_id == product_id
            )
        )
        .scalars()
        .all()
    }
    # REPLACE: 나열 안 된 기존 타입 비활성('-'면 desired={}라 전부 비활성), 나열된 것 upsert(active).
    for ticket_type, grant in existing.items():
        if ticket_type not in desired:
            grant.active = False
    for ticket_type, count in desired.items():
        if ticket_type in existing:
            existing[ticket_type].count = count
            existing[ticket_type].active = True
        else:
            db.add(
                ProductVoucherGrant(
                    product_id=product_id,
                    ticket_type=ticket_type,
                    count=count,
                    active=True,
                )
            )


def import_products_from_csv(
    db: Session,
    csv_path: str,
    environment: str,
    interactive: bool = True,
    voucher_tables: Optional[dict] = None,
    voucher_cap: Optional[int] = None,
) -> tuple[int, int]:
    """
    CSV 파일에서 상품 데이터를 가져와 데이터베이스에 임포트합니다.

    Args:
        db: 데이터베이스 세션
        csv_path: CSV 파일 경로
        environment: 'internal' 또는 'mainnet'
        interactive: 사용자 입력을 받을지 여부
    """
    if environment not in ["internal", "mainnet"]:
        raise ValueError("environment must be either 'internal' or 'mainnet'")

    is_internal = environment == "internal"
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
                # (C1b) voucher 컬럼이 있으면 상품→티켓 매핑도 같은 트랜잭션서 REPLACE(원자적).
                _apply_voucher_row(
                    db,
                    csv_data["id"],
                    row,
                    voucher_tables,
                    voucher_cap,
                    product_type=csv_data.get("product_type"),
                )

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
            (category_product_table.c.category_id == category_id)
            & (category_product_table.c.product_id == product_id)
        )
    ).fetchone()

    if existing_relation:
        print(f"⏩ Category {category_id} - Product {product_id} 관계가 이미 존재합니다. 건너뜁니다.")
        return False

    # ✅ 관계 추가
    db.execute(
        category_product_table.insert().values(
            category_id=category_id, product_id=product_id
        )
    )
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
            print(
                f"\n✅ Category-Product 관계 데이터 동기화 완료! (처리: {processed_count}, 추가: {added_count})"
            )
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
    existing_asset = (
        db.query(FungibleAssetProduct)
        .filter(
            FungibleAssetProduct.product_id == csv_data["product_id"],
            FungibleAssetProduct.ticker == csv_data["ticker"],
        )
        .first()
    )

    if existing_asset:
        # 변경사항 확인
        changes = {}
        for key, value in csv_data.items():
            if getattr(existing_asset, key) != value:
                changes[key] = (getattr(existing_asset, key), value)

        if changes:
            print(
                f"\n🔍 Product ID {csv_data['product_id']} - {csv_data['ticker']} 변경 사항 발견:"
            )
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
        print(
            f"🆕 새로운 FungibleAsset 추가: Product ID {csv_data['product_id']} - {csv_data['ticker']}"
        )
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
            print(
                f"\n✅ FungibleAsset 데이터 동기화 완료! (처리: {processed_count}, 변경: {changed_count})"
            )
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
    existing_item = (
        db.query(FungibleItemProduct)
        .filter(
            FungibleItemProduct.product_id == csv_data["product_id"],
            FungibleItemProduct.fungible_item_id == csv_data["fungible_item_id"],
        )
        .first()
    )

    if existing_item:
        # 변경사항 확인
        changes = {}
        for key, value in csv_data.items():
            if getattr(existing_item, key) != value:
                changes[key] = (getattr(existing_item, key), value)

        if changes:
            print(
                f"\n🔍 Product ID {csv_data['product_id']} - Item ID {csv_data['fungible_item_id']} 변경 사항 발견:"
            )
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
        print(
            f"🆕 새로운 FungibleItem 추가: Product ID {csv_data['product_id']} - Item ID {csv_data['fungible_item_id']}"
        )
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
            touched_products = set()
            for row in reader:
                processed_count += 1
                touched_products.add(parse_int(row["product_id"]))
                if process_fungible_item_row(db, row):
                    changed_count += 1

            # (PLD-1562) 반대 방향의 배타 검사. 이미 뽑기 풀이 있는 상품에 고정 구성품을
            #   붙이면 그 상품은 등록 시점에 조용히 통과하고 **주문 시점에 400** 이 된다 —
            #   등록 시점 검사를 만든 이유 그 자체다.
            db.flush()
            for product_id in touched_products:
                assert_not_mixed_components(db, product_id)

            db.commit()
            print(
                f"\n✅ FungibleItem 데이터 동기화 완료! (처리: {processed_count}, 변경: {changed_count})"
            )
            return processed_count, changed_count

    except Exception as e:
        db.rollback()
        raise e


def process_price_row(db: Session, row: dict) -> bool:
    """
    가격 정보를 처리합니다.

    Args:
        db: 데이터베이스 세션
        row: CSV 행 데이터

    Returns:
        bool: 업데이트되었으면 True, 변경사항이 없으면 False
    """
    product_id = int(row["product_id"])
    store = Store[row["store"]]

    # 기존 가격 정보 확인
    existing_price = (
        db.query(Price)
        .filter(Price.product_id == product_id, Price.store == store)
        .first()
    )

    price_data = {
        "product_id": product_id,
        "store": store,
        "currency": row["currency"],
        "price": parse_float(row["price"]),
        "active": parse_boolean(row["active"]),
        "discount": parse_float(row["discount"]) or 0,
        "regular_price": parse_float(row["regular_price"]) or 0,
    }

    if existing_price:
        # 변경사항 확인
        changed = False
        for key, value in price_data.items():
            if getattr(existing_price, key) != value:
                setattr(existing_price, key, value)
                changed = True

        if changed:
            print(f"✅ Product {product_id}의 {store.value} 스토어 가격 정보가 업데이트되었습니다.")
            return True
        else:
            print(f"⏩ Product {product_id}의 {store.value} 스토어 가격 정보에 변경사항이 없습니다.")
            return False
    else:
        # 새로운 가격 정보 추가
        new_price = Price(**price_data)
        db.add(new_price)
        print(f"🆕 Product {product_id}의 {store.value} 스토어 가격 정보가 추가되었습니다.")
        return True


def import_prices_from_csv(db: Session, csv_path: str) -> Tuple[int, int]:
    """
    CSV 파일에서 가격 정보를 가져와 데이터베이스에 임포트합니다.

    Args:
        db: 데이터베이스 세션
        csv_path: CSV 파일 경로

    Returns:
        Tuple[int, int]: (처리된 가격 정보 수, 업데이트된 가격 정보 수)
    """
    processed_count = 0
    updated_count = 0

    try:
        with open(csv_path, mode="r", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                processed_count += 1
                if process_price_row(db, row):
                    updated_count += 1

            db.commit()
            print(f"\n✅ 가격 정보 동기화 완료! (처리: {processed_count}, 업데이트: {updated_count})")
            return processed_count, updated_count

    except Exception as e:
        db.rollback()
        raise e


# ── (PLD-1562) 뽑기 풀 CSV ────────────────────────────────────────────────────
# 컬럼: product_id, name, weight, kind, ticker, amount, sheet_item_id, decimal_places,
#       slot_key
#   · kind           = ITEM | FAV (생략 시 ITEM — 기존 시트 하위호환)
#   · ticker         = Item_NT_400000 / FAV__RUNESTONE_HP
#   · sheet_item_id  = 아이템 아이콘용(ITEM 필수 / FAV 는 비워 둘 것)
#   · decimal_places = FAV 자릿수(생략 시 0). 아이템은 항상 0
#   · slot_key       = **칸의 정체성**(생략 시 티커). 같은 아이템을 수량만 다르게 여러 칸
#                      두려면 필요하다. 한 상품 안에서는 **전부 쓰거나 전부 안 쓴다**
#
# `fungible-items/import` 와 같은 모양(상품당 여러 행)을 따른다. voucher 처럼 고정 슬롯을
# 쓰지 않는 이유: 풀은 수십 칸이 될 수 있어 `gacha_item_1..N` 으로는 표가 못 넘어간다.
#
# ⚠️ **REPLACE 가 아니라 upsert 다.** 행을 지우려면 CSV 가 아니라 명시적으로 지워야 한다.
#    REPLACE 로 만들면 부분 CSV 를 올리는 순간 나머지 칸이 조용히 사라지고, 그건 확률이
#    통째로 바뀌는 사고다(그리고 이미 뽑힌 주문은 동결돼 있어 대조로도 안 드러난다).


def assert_not_mixed_components(db: Session, product_id: int) -> None:
    """
    한 상품이 **고정 구성품과 뽑기 풀을 동시에** 갖지 못하게 한다.

    "둘 다 주나 하나만 주나"가 정의되지 않아 지급 API 가 400 으로 끊는 상태다. 그걸
    **등록 시점에** 알려야 한다 — 지급 시점에만 걸리면 유저가 포인트를 쓴 뒤에 실패한다.

    ⚠️ 양방향이어야 한다. 뽑기 import 만 검사하면 반대 경로(이미 풀이 있는 상품에
       `fungible-items/import` 로 고정 구성품을 붙이는 것)가 조용히 통과한다.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if product is None:
        raise ValueError(f"product {product_id} 가 존재하지 않는다")
    has_fixed = bool(product.fav_list or product.fungible_item_list)
    has_pool = bool(product.gacha_entry_list)
    if has_fixed and has_pool:
        raise ValueError(
            f"product {product_id} 는 고정 구성품과 뽑기 풀을 동시에 가질 수 없다"
            " (지급 시점에 400 으로 끊긴다 — 한쪽을 비울 것)"
        )


def _row_ticker(row: dict) -> str:
    """CSV 행의 티커. `fungible_item_id` 는 옛 컬럼명이다(불일치는 행 단위 검사가 끊는다)."""
    return (row.get("ticker") or row.get("fungible_item_id") or "").strip()


def _effective_slot_key(row: dict) -> str:
    """실제 upsert 키. 명시 `slot_key`, 없으면 티커 폴백 — process_gacha_entry_row 와 같다."""
    return (row.get(GACHA_SLOT_KEY_COLUMN) or "").strip() or _row_ticker(row)


def _claim_id(entry: ProductGachaEntry) -> int:
    """
    이번 임포트에서 이 칸을 이미 썼는지 가리는 키 = **PK**.

    ⚠️ 파이썬 객체 id 를 쓰면 안 된다. SQLAlchemy 의 identity map 은 **약한 참조**라
    지역 변수가 사라진 뒤 GC 되면 같은 행이라도 다음 쿼리가 **새 인스턴스**를 만든다
    (실측: claimed 에 넣은 id 와 다음 쿼리가 돌려준 객체의 id 가 달랐다). 게다가 해제된
    id 는 재사용될 수 있어 엉뚱한 행을 '이미 썼다'고 볼 수도 있다.

    그래서 신규 행은 `add()` 직후 flush 해 PK 를 받고 그 값을 기록한다.
    """
    assert entry.id is not None, "flush 전 행을 claim 하려 한다 — PK 가 없다"
    return entry.id


def gacha_pool_summary(
    db: Session, product_id: int, file_keys: Optional[set] = None
) -> str:
    """풀 한 줄 요약 — **칸 수와 Σweight**, 그리고 파일에 없던 기존 칸.

    확률을 바꾸는 사고(칸 복제·칸 합쳐짐)는 전부 이 두 숫자로 드러난다. "변경 N건" 만으로는
    운영이 알아챌 수 없다 — 사고 났을 때도 변경 건수는 정상값이기 때문이다.

    `file_keys` 를 주면 **이번 파일에 없던 기존 칸**도 적는다. 전환이 끝난 뒤에는 "부분
    시트 = 담긴 칸만 갱신" 이 정상 동작이라 칸 이름 오타·리네임과 구분할 방법이 없다 —
    막을 게 아니라 **보이게** 할 문제다(`mat_s` 를 `mat_hourglass_s` 로 고쳐 올리면
    옛 칸이 그대로 남아 표가 한 칸 늘어난다).
    """
    rows = (
        db.query(ProductGachaEntry)
        .filter(ProductGachaEntry.product_id == product_id)
        .all()
    )
    total = sum(r.weight for r in rows)
    line = f"product {product_id}: {len(rows)}칸 / Σweight {total}"
    if file_keys is not None:
        absent = sorted({r.slot_key for r in rows} - file_keys)
        if absent:
            line += f" / 파일에 없는 기존 칸: {absent}"
    return line


def assert_slot_keys_consistent(db: Session, rows: list) -> None:
    """
    (PLD-1562) `slot_key` 파일 단위 선행 검사. 전부 **확률을 조용히 바꾸는** 사고들이다.

    풀 CSV 는 upsert-only(삭제가 없다)라 잘못 들어간 칸은 DB 를 직접 고쳐야 없어진다.
    그래서 "틀린 채로 성공" 을 한 줄도 허용하지 않는다.

    막는 것:
      1. **한 상품 안에서 slot_key 전부/전무** — 섞이면 무키 행이 레거시 칸을 갱신하고,
         뒤 행이 그 칸을 또 입양해 두 행이 한 칸으로 합쳐진다(9칸 표가 5칸).
      2. **파일 안 중복 키** — 오타·복붙, 그리고 **slot_key 컬럼을 깜빡한 재료 시트**.
         판정은 실효 키(명시값 or 티커 폴백) 기준이다 — 키 있는 행만 보면 후자가 샌다.
      3. **이미 키잉된 상품에 무키 시트** — 옛 시트 탭이 남아 있는 전환 직후가 제일 위험하다.
         티커로 폴백해 INSERT 되고, 칸이 복제돼 공시 확률이 절반이 된다.
      4. **레거시 칸을 덮지 않는 부분 시트** — 새 행만 올리면 남은 레거시 칸이 그 행으로
         **변신**한다(추가가 아니라 재정의). 전환 임포트는 풀 전체를 한 번에 올려야 한다.
    """
    by_product: dict = {}
    for row in rows:
        by_product.setdefault(parse_int(row["product_id"]), []).append(row)

    for product_id, product_rows in by_product.items():
        keyed = [r for r in product_rows if (r.get(GACHA_SLOT_KEY_COLUMN) or "").strip()]
        if keyed and len(keyed) != len(product_rows):
            raise ValueError(
                f"gacha product {product_id}: {GACHA_SLOT_KEY_COLUMN} 는 그 상품의 행"
                " **전부**에 있거나 전부 없어야 한다 — 섞이면 두 행이 한 칸으로 합쳐진다"
            )

        # 중복은 **실효 키**(명시값 or 티커 폴백) 기준으로 본다. 키 있는 행만 보면
        #   무키 시트의 티커 중복 — 재료 9행을 쓰면서 slot_key 컬럼을 깜빡하는, 전환기
        #   1순위 실수 — 이 그대로 통과해 9칸이 5칸이 된다(이 티켓의 원래 사고다).
        keys = [_effective_slot_key(r) for r in product_rows]
        dups = sorted({k for k in keys if keys.count(k) > 1})
        if dups:
            raise ValueError(
                f"gacha product {product_id}: 같은 칸이 파일에 두 번 있다 {dups} —"
                f" 뒤 행이 앞 행을 덮어써 칸이 사라진다."
                f" 같은 아이템을 수량만 다르게 두려면 {GACHA_SLOT_KEY_COLUMN} 를 다르게 줄 것"
            )

        if keyed:
            # 칸 이름을 남의 티커로 지으면 그 칸을 집는다(백필 때문에 레거시 칸의 키가
            #   곧 티커다). 자기 티커와 같은 건 폴백과 구분이 안 되므로 허용한다.
            #   ⚠️ 이건 **보증이 아니라 벨트**다 — 접두어 없는 티커(예: `CRYSTAL`)는 못
            #   거른다. 실제 방어는 위 중복 검사와 아래 커버 검사이고, 그 둘을 손댈 때
            #   이 검사에 기대지 말 것.
            for r in keyed:
                key = (r.get(GACHA_SLOT_KEY_COLUMN) or "").strip()
                ticker = _row_ticker(r)
                if not ticker:
                    continue  # 원인은 빈 티커다 — 행 단위 검사가 제대로 된 메시지를 낸다
                if key != ticker and (key.startswith("Item_") or key.startswith("FAV__")):
                    raise ValueError(
                        f"gacha product {product_id}: {GACHA_SLOT_KEY_COLUMN}={key!r} 는"
                        " 티커 형태다 — 다른 칸을 덮어쓴다. 칸 이름은 티커로 짓지 말 것"
                    )

        existing = (
            db.query(ProductGachaEntry)
            .filter(ProductGachaEntry.product_id == product_id)
            .all()
        )
        # ⚠️ 커버는 티커가 아니라 **(티커, 수량)** 으로 잰다. 이 티켓의 전제가 "티커 하나가
        #   수량별로 여러 칸" 이라, 티커로 재면 **티커는 전부 덮으면서 칸은 절반만 담은**
        #   시트가 통과한다(작은 수량 칸들이 통째로 큰 수량으로 재정의된다).
        #   정상 전환 행은 레거시 칸과 수량이 같으므로 오탐이 없다.
        legacy = {(e.ticker, e.amount) for e in existing if e.slot_key == e.ticker}

        if not keyed:
            if len(legacy) < len(existing):
                raise ValueError(
                    f"gacha product {product_id}: 이 상품은 이미"
                    f" {GACHA_SLOT_KEY_COLUMN} 로 관리된다 — 칸 이름 없는 옛 시트로"
                    " 덮어쓸 수 없다(칸이 복제돼 확률이 어긋난다)"
                )
            continue

        # 전환 임포트(레거시 칸이 남아 있는데 키를 붙이는 중)는 **풀 전체**여야 한다.
        csv_slots = {
            (_row_ticker(r), parse_int((r.get("amount") or "").replace(",", "")))
            for r in product_rows
        }
        missing = sorted(legacy - csv_slots)
        if missing:
            shown = ", ".join(f"{t} x{a}" for t, a in missing)
            raise ValueError(
                f"gacha product {product_id}: 아직 칸 이름이 없는 기존 칸 [{shown}] 이"
                " 이 파일에 없다 — 전환 임포트는 풀 전체를 한 번에 올려야 한다"
                " (빠진 칸이 이 파일의 다른 행으로 변신한다)"
            )


def process_gacha_entry_row(db: Session, row: dict, claimed: Optional[set] = None) -> bool:
    """뽑기 풀 한 칸 upsert. upsert 키는 (product_id, slot_key) — 테이블 UNIQUE 와 같다."""
    weight = parse_int((row.get("weight") or "").replace(",", ""))
    amount = parse_int((row.get("amount") or "").replace(",", ""))
    product_id = parse_int(row["product_id"])
    # kind 는 **3상태**다 — 빈칸/컬럼 부재는 "변경 없음"이지 ITEM 이 아니다.
    #   2상태로 읽으면 kind 컬럼 없는 옛 시트를 재임포트하는 순간 **기존 FAV 칸이 ITEM 으로
    #   내려앉고**, 그 칸은 지급 tx 에서 아이템으로 취급돼 발행이 깨진다.
    #   같은 리포의 선례: parse_point_shop_grantable 의 "머니 플래그는 3상태여야 한다".
    raw_kind = (row.get("kind") or "").strip().upper()
    if raw_kind and raw_kind not in (GACHA_KIND_ITEM, GACHA_KIND_FAV):
        raise ValueError(
            f"gacha product {product_id}: kind 는 ITEM 또는 FAV 여야 한다 (got {raw_kind!r})"
        )
    # `ticker` 가 정본이고 `fungible_item_id` 는 옛 컬럼명이다(기존 시트가 그대로 돈다).
    #   둘 다 있고 값이 다르면 조용히 ticker 가 이기는 대신 끊는다(어느 쪽 의도인지 모른다).
    ticker = (row.get("ticker") or "").strip()
    legacy = (row.get("fungible_item_id") or "").strip()
    if ticker and legacy and ticker != legacy:
        raise ValueError(
            f"gacha product {product_id}: ticker({ticker!r}) 와"
            f" fungible_item_id({legacy!r}) 가 다르다 — 한쪽만 쓸 것"
        )
    ticker = ticker or legacy
    if not ticker:
        raise ValueError(f"gacha product {product_id}: ticker 가 비어 있다")

    # `slot_key` 는 **칸의 정체성**이고 티커는 산출물이다. 컬럼이 없거나 빈칸이면 티커를
    #   키로 쓴다 — 옛 시트가 그대로 돌아야 하고, 마이그레이션이 기존 행을 정확히 그 값
    #   (slot_key = ticker)으로 백필해 뒀다.
    slot_key = (row.get(GACHA_SLOT_KEY_COLUMN) or "").strip() or ticker
    claimed_ids = claimed if claimed is not None else set()
    existing = (
        db.query(ProductGachaEntry)
        .filter(
            ProductGachaEntry.product_id == product_id,
            ProductGachaEntry.slot_key == slot_key,
        )
        .first()
    )
    if existing is None and slot_key != ticker:
        # 옛 시트에 slot_key 를 **처음 붙이는** 재임포트. 그냥 INSERT 하면 22칸 표가 44칸이
        #   되고 확률이 절반으로 어긋난다(가장 흔한 사고 경로다). 아직 아무도 이름표를 붙이지
        #   않은 칸(slot_key == ticker)이 있으면 그 칸을 **입양**해 이름표만 갈아 끼운다.
        #   이번 임포트가 이미 쓴 칸은 제외한다 — 그래야 같은 티커의 두 번째 행이 첫 번째
        #   행의 칸을 다시 집지 않고 새 칸이 된다(둘이 한 칸으로 합쳐지면 표가 줄어든다).
        existing = next(
            (
                e
                for e in db.query(ProductGachaEntry)
                .filter(
                    ProductGachaEntry.product_id == product_id,
                    ProductGachaEntry.ticker == ticker,
                    ProductGachaEntry.slot_key == ProductGachaEntry.ticker,
                )
                .order_by(ProductGachaEntry.id)
                .all()
                if _claim_id(e) not in claimed_ids
            ),
            None,
        )
    if existing is not None:
        if _claim_id(existing) in claimed_ids:
            # 선행 검사가 파일 안 중복 키를 이미 막지만, 이 함수를 직접 부르는 경로
            #   (스크립트·테스트)까지 같은 보장을 준다.
            raise ValueError(
                f"gacha product {product_id}: 칸 {slot_key} 를 이번 임포트에서 두 번 쓴다"
            )
        claimed_ids.add(_claim_id(existing))
    # 빈칸이면 기존 행의 kind 유지, 신규면 ITEM(옛 시트 하위호환).
    kind = raw_kind or (existing.kind if existing else GACHA_KIND_ITEM)
    sheet_item_id = parse_int((row.get("sheet_item_id") or "").strip() or "0") or None
    decimal_places = parse_int((row.get("decimal_places") or "").strip() or "0") or 0

    if kind == GACHA_KIND_ITEM:
        if sheet_item_id is None:
            raise ValueError(
                f"gacha product {product_id}: ITEM 칸은 sheet_item_id 가 필요하다"
                f" ({ticker}) — 화면 아이콘이 이걸로 그려진다"
            )
        if decimal_places != 0:
            raise ValueError(
                f"gacha product {product_id}: ITEM 의 decimal_places 는 0 이어야 한다"
                f" ({ticker}) — 아이템에 소수 자릿수가 없다"
            )
    else:
        if sheet_item_id is not None:
            raise ValueError(
                f"gacha product {product_id}: FAV 칸에 sheet_item_id 를 두지 말 것"
                f" ({ticker}) — 화면이 없는 아이콘을 그린다"
            )
        if decimal_places < 0:
            raise ValueError(
                f"gacha product {product_id}: decimal_places 는 0 이상이어야 한다 ({ticker})"
            )

    # 0·음수는 DB CheckConstraint 도 막지만, 여기서 끊어야 **어느 행이** 틀렸는지 말해줄 수
    # 있다(제약 위반은 IntegrityError 문자열만 남아 운영이 CSV 를 못 찾는다).
    if weight is None or weight <= 0:
        raise ValueError(
            f"gacha product {product_id}: weight 는 양의 정수여야 한다 (got {row.get('weight')!r})."
            " 0 을 넣으면 '넣었는데 절대 안 나오는 칸'이 된다"
        )
    if amount is None or amount <= 0:
        raise ValueError(
            f"gacha product {product_id}: amount 는 양의 정수여야 한다 (got {row.get('amount')!r})"
        )

    csv_data = {
        "product_id": product_id,
        "slot_key": slot_key,
        "name": row["name"],
        "weight": weight,
        "kind": kind,
        "ticker": ticker,
        "decimal_places": decimal_places,
        "sheet_item_id": sheet_item_id,
        "amount": amount,
    }

    if existing:
        changes = {
            key: (getattr(existing, key), value)
            for key, value in csv_data.items()
            if getattr(existing, key) != value
        }
        if not changes:
            return False
        print(
            f"\n🔍 Gacha entry (product {csv_data['product_id']} /"
            f" 칸 {csv_data['slot_key']}) 변경:"
        )
        for field, (old, new) in changes.items():
            print(f"  - {field}: 기존({old}) → 변경({new})")
            setattr(existing, field, new)
        return True

    entry = ProductGachaEntry(**csv_data)
    db.add(entry)
    db.flush()  # PK 를 받아야 claim 할 수 있다(아래 주석) — 롤백 경계는 그대로다
    # 이번 임포트가 **새로 만든** 칸도 입양 대상에서 빼야 한다. 빼지 않으면 뒤 행이
    #   (slot_key == ticker 로 들어간) 이 칸을 집어 두 행이 한 칸으로 합쳐진다 —
    #   "기존 칸은 이름 그대로 두고 새 칸만 이름 붙인다" 는 가장 자연스러운 시트 쓰기가
    #   바로 그 조합이라, 회피 경로가 아니라 주 경로다.
    claimed_ids.add(_claim_id(entry))
    print(
        f"🆕 Gacha entry 추가: product {csv_data['product_id']} /"
        f" 칸 {csv_data['slot_key']} = [{csv_data['kind']}] {csv_data['ticker']}"
        f" x{csv_data['amount']}"
        f" (weight {csv_data['weight']})"
    )
    return True


def import_gacha_entries_from_csv(
    db: Session,
    csv_path: str,
    summary_out: Optional[list] = None,
) -> Tuple[int, int]:
    """
    뽑기 풀 CSV 임포트.

    ⚠️ 임포트가 끝나고 **등록 시점 검증 2종**을 돈다(둘 다 지급 시점에만 걸리면 유저가
       포인트를 쓴 뒤에 실패하는 것들이다):
         · 고정 구성품과의 배타 — assert_not_mixed_components
       실패는 전체 롤백이다(부분 반영된 풀은 확률이 기획과 다른 표가 된다).
    """
    processed_count = 0
    changed_count = 0
    touched_products = set()
    # 이번 임포트가 이미 쓴 칸. 입양 후보에서 빼고, 같은 칸을 두 번 쓰는 것도 여기서 잡는다.
    #   (autoflush 에 기대지 않는다 — 배치화·autoflush=False 한 번에 조용히 깨진다)
    claimed: set = set()

    try:
        with open(csv_path, mode="r", encoding="utf-8") as file:
            rows = list(csv.DictReader(file))

        # 행을 하나라도 쓰기 전에 **파일 전체**를 본다. 아래 규칙들은 행 단위로는 판정이
        #   불가능하고(앞뒤 행과 DB 상태를 같이 봐야 한다), 반쯤 반영된 풀은 확률이 기획과
        #   다른 표다.
        assert_slot_keys_consistent(db, rows)

        for row in rows:
            processed_count += 1
            touched_products.add(parse_int(row["product_id"]))
            if process_gacha_entry_row(db, row, claimed=claimed):
                changed_count += 1

        db.flush()
        for product_id in touched_products:
            assert_not_mixed_components(db, product_id)

        db.commit()
        print(
            f"\n✅ Gacha 풀 동기화 완료! (처리: {processed_count}, 변경: {changed_count})"
        )
        # 요약은 **임포터가 만든다.** 호출부가 CSV 를 다시 파싱하면 파서가 갈리고
        #   (예: 콤마 낀 product_id) 그 상품이 요약에서 조용히 빠지는데, 지금은 이 요약이
        #   사고를 잡는 유일한 신호다.
        keys_by_product: dict = {}
        for row in rows:
            keys_by_product.setdefault(parse_int(row["product_id"]), set()).add(
                _effective_slot_key(row)
            )
        for product_id in sorted(touched_products):
            line = gacha_pool_summary(db, product_id, keys_by_product.get(product_id))
            print(f"   {line}")
            if summary_out is not None:
                summary_out.append(line)
        return processed_count, changed_count

    except Exception as e:
        db.rollback()
        raise e
