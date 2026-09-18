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
    check_fav_tickers,
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
        # prod 상한 미주입 게이트는 여기 두지 않는다 — 지급 시점이 fail-closed(503)라
        #   플래그만 켜져도 발행 창이 열리지 않는다(voucher C3-lite 는 그 반대라 게이트가 필요했다).
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


def _check_grantable_fav_row(
    db: Session, csv_data: dict, allowed_fav_tickers: frozenset
) -> None:
    """
    (PLD-1575) 이 행이 화이트리스트를 **켜려 할 때** FAV 티커 얼로우리스트를 선검증한다.

    왜 켜는 시점에 보나: 지급 시점(`enforce_grant_guards`)만 보면 임포트는 200 으로 끝나고
    운영자는 켠 줄 알지만, 실주문이 들어오는 순간 전부 거절된다(그때는 이미 주문이 쌓인 뒤다).
    백오피스 CRUD(`PUT /admin/point-shop-products`)도 같은 이유로 같은 검사를 한다.

    셀이 TRUE 면 **현재 DB 값과 무관하게** 검사한다(전이 False→True 만 보지 않는다) — 같은 행의
    `validate_point_shop_grantable_eligible` 과 같은 규칙이고, 시트가 진실 소스라 TRUE 는 "지금
    켜져 있어야 한다"는 선언이기 때문이다. ⚠️ 운영상 결과: 시트에 TRUE 가 박힌 FAV 상품이 하나라도
    있으면 그 뒤 **모든** 상품 CSV 임포트(가격·오픈시각 변경 포함)가 허용 티커 설정에 묶인다.
    그래서 `API_GRANT_ALLOWED_FAV_TICKERS` 주입이 화이트리스트를 켜기 전 배포 순서에 들어간다.

    `process_csv_row`(순수 행 파서) 가 아니라 여기 있는 이유: FAV 구성품은 상품 CSV 행에 없다
    (`fungible_asset_product` = `fungible-assets/import` 소관) → 세션 없이는 볼 수 없다.
    세션이 필요한 행 단위 검증은 `_apply_voucher_row` 와 같은 자리에 둔다.

    ⚠️ `GrantGuardViolation`(HTTPException)을 **ValueError 로 감싸지 않는다.** 이 파일의 다른 행
    검증은 `raise ValueError(f"product {id}: {e.detail}")` 관례를 쓰지만, 그러면 엔드포인트의
    catch-all 이 전부 400 으로 눌러 버린다 — 허용목록 **미주입은 503**(호출자 잘못이 아니라
    운영 실수)이라는 지급 시점 규약(계약 v1.2)이 켜는 경로에서도 같아야 한다. `check_fav_tickers`
    의 detail 에 이미 product id 가 들어 있어 컨텍스트도 잃지 않는다. 예외가 위로 나가면
    `import_products_from_csv` 가 rollback 하므로 임포트는 통째로 거부된다(voucher 행과 같은 원자성).
    """
    if not csv_data.get(POINT_SHOP_GRANTABLE_COLUMN):
        # 빈칸(=유지)·False(=끄기)는 검사하지 않는다 — 킬스위치를 게이트 뒤에 두면 안 된다.
        return
    product_id = csv_data.get("id")
    if product_id is None:
        # id 빈칸(신규 autoincrement) — 구성품이 있을 수 없다.
        return
    product = db.query(Product).filter(Product.id == product_id).first()
    if product is None:
        # 신규 상품(명시 id) — 아직 구성품이 없다(FK 때문에 FAV 행이 먼저 있을 수도 없다).
        #   FAV 는 뒤이은 fungible-assets 임포트로 붙고, 실주문은 지급 시점 가드가 막는다.
        # TODO(PLD-1575 후속): `import_fungible_assets_from_csv` 에 대칭 게이트가 없다 —
        #   **이미 켜진** 상품에 NCG 를 붙이거나 CRYSTAL→NCG 로 갈아치우는 경로가 그대로 열려
        #   있다(`check_fav_tickers` 도커스트링이 지목한 바로 그 경로). 손대려면 그 엔드포인트
        #   (`POST /admin/products/fungible-assets/import`)에 `except HTTPException: raise` 가
        #   없어 503 이 400 문자열로 붕괴하는 것부터 같이 고쳐야 한다.
        return
    check_fav_tickers(product, allowed_fav_tickers)


def _check_gacha_draw_count_row(db: Session, csv_data: dict, max_item_units, max_fav_units):
    """
    이 행이 `gacha_draw_count` 를 실었고 그 상품이 풀을 갖고 있으면 상한을 다시 잰다.

    컬럼이 없는 행(= 추첨 횟수 미변경)은 건너뛴다 — 뽑기와 무관한 상품 임포트마다 풀을
    조회할 이유가 없다.
    """
    if GACHA_DRAW_COUNT_COLUMN not in csv_data:
        return
    db.flush()  # 위 update 가 아직 세션에만 있을 수 있다(상한은 **새 값**으로 재야 한다)
    if (
        db.query(ProductGachaEntry)
        .filter(ProductGachaEntry.product_id == csv_data["id"])
        .first()
        is None
    ):
        return
    assert_gacha_entry_within_caps(
        db, csv_data["id"], max_item_units, max_fav_units
    )


def import_products_from_csv(
    db: Session,
    csv_path: str,
    environment: str,
    interactive: bool = True,
    voucher_tables: Optional[dict] = None,
    voucher_cap: Optional[int] = None,
    allowed_fav_tickers: frozenset = frozenset(),
    max_item_units=None,
    max_fav_units=None,
) -> tuple[int, int]:
    """
    CSV 파일에서 상품 데이터를 가져와 데이터베이스에 임포트합니다.

    Args:
        db: 데이터베이스 세션
        csv_path: CSV 파일 경로
        environment: 'internal' 또는 'mainnet'
        interactive: 사용자 입력을 받을지 여부
        allowed_fav_tickers: (PLD-1575) 지급 허용 FAV 티커. `point_shop_grantable` 을 켜는 행에만
            쓴다. **미전달 = 빈 집합 = FAV 구성품이 있는 상품은 켤 수 없다**(fail-closed —
            `grant_guard.parse_fav_tickers` 와 같은 의미). 값의 출처는 설정이고 호출부가 넣는다
            (voucher_cap 과 같은 규칙 — 이 모듈은 `app.config` 를 임포트하지 않는다).
        max_item_units / max_fav_units: (PLD-1562) 요청 단위 발행량 상한. `gacha_draw_count`
            를 바꾸는 행에서 **풀의 수량 상한을 다시 재는 데** 쓴다(그 경로가 없으면
            1→10 변경이 상한 검사를 통째로 건너뛴다 — 조용한 재추첨의 입구).

    Returns:
        tuple[int, int]: (처리된 상품 수, 업데이트된 상품 수)
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
                # (PLD-1575) 화이트리스트를 **켜는** 행이면 FAV 티커를 선검증한다 — 켜는 순간
                #   거절(미주입 503 / 목록 밖 400)이라야 운영자가 그 자리에서 안다.
                _check_grantable_fav_row(db, csv_data, allowed_fav_tickers)
                if compare_and_update_product(db, csv_data, is_internal, interactive):
                    updated_count += 1
                # (PLD-1562) 🔴 `gacha_draw_count` 가 바뀌면 **풀의 수량 상한을 다시 잰다.**
                #   상한은 1 요청 단위인데 10연은 한 요청이 10회 지급이라, 1→10 으로 고치는
                #   순간 이미 등록된 칸들의 최악값이 10배가 된다. 풀 CSV 쪽 검사만 있으면
                #   이 경로는 **한 번도 안 돌고**, 그 뒤 `amount × 10 > cap` 인 칸이 뽑힌
                #   10연만 지급 시점에 400 이 된다 — 그 400 이 곧 조용한 재추첨이다
                #   (행이 안 생겨 포탈 재시도가 멱등에 안 걸리고 다시 뽑는다).
                _check_gacha_draw_count_row(
                    db, csv_data, max_item_units, max_fav_units
                )
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
# 컬럼: product_id, name, weight, kind, ticker, amount, sheet_item_id, decimal_places
#   · kind           = ITEM | FAV (생략 시 ITEM — 기존 시트 하위호환)
#   · ticker         = Item_NT_400000 / FAV__RUNESTONE_HP
#   · sheet_item_id  = 아이템 아이콘용(ITEM 필수 / FAV 는 비워 둘 것)
#   · decimal_places = FAV 자릿수(생략 시 0). 아이템은 항상 0
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


def assert_gacha_entry_within_caps(
    db: Session, product_id: int, max_item_units, max_fav_units=None
) -> None:
    """
    풀의 **모든 칸**이 요청 단위 수량 상한 안인지. 상한이 미설정(None)이면 검사하지 않는다.

    ⚠️ FAV 칸은 **FAV 상한**으로 잰다. 아이템 상한으로 재면 "물약 1,000개를 허용하려고
       올린 상한이 NCG 1,000 발행을 허용한다"가 등록 시점에 그대로 재현된다.

    ⚠️ 이게 없으면 "임포트는 200 인데 **그 칸에 당첨된 유저만** 400" 이 된다. 확률이 낮은
       칸일수록 늦게 발견되고, 운영에는 저빈도 거절 알림만 보여 공격처럼 읽힌다.
       같은 함정을 FAV 티커에서 이미 겪고 선례를 만들어 뒀다(admin.py 의
       "임포트는 200 인데 실주문이 전부 거절되는 상태를 만들지 않는다").

    ⚠️ (10연) 상한은 **1 요청** 단위인데 10연은 한 요청이 10회 지급이다. 같은 칸이 10번
       뽑히면 합산되므로 최악은 `amount x draw_count` — 그 배수로 재야 "운 좋은 10연만
       400" 이 안 생긴다.
    """
    caps = {GACHA_KIND_ITEM: max_item_units, GACHA_KIND_FAV: max_fav_units}
    product = db.query(Product).filter(Product.id == product_id).first()
    draws = int(getattr(product, "gacha_draw_count", 1) or 1)
    over = []
    for entry in (
        db.query(ProductGachaEntry)
        .filter(ProductGachaEntry.product_id == product_id)
        .all()
    ):
        cap = caps.get(entry.kind)
        # 10연은 한 요청이 10회 지급이라 최악의 경우 amount × draw_count 가 나간다.
        worst = int(entry.amount) * draws
        if cap is not None and worst > cap:
            over.append((entry, cap, worst))
    if over:
        names = ", ".join(
            f"{e.name}[{e.kind}](x{e.amount}*{draws}={worst}>{cap})"
            for e, cap, worst in over
        )
        raise ValueError(
            f"product {product_id} 뽑기 칸의 수량이 요청 단위 상한을 넘는다: {names}"
            " — 그 칸에 당첨된 유저만 지급이 거절된다"
        )


def assert_gacha_fav_tickers_allowed(db: Session, product_id: int, allowed) -> None:
    """
    풀의 FAV 칸 티커가 **지급 허용목록 안**인지. 등록 시점에 막는다.

    ⚠️ 이게 없으면 지급 시점에 `check_fav_tickers` 가 그 칸에 당첨된 주문만 거절하는데,
       그 거절은 "그 주문만 멈춤"이 아니라 **조용한 재추첨**이다 — 추첨이 아웃박스 행보다
       먼저라 거절 시 행이 없고, 포탈 재시도가 멱등에 안 걸려 다시 뽑는다. 공시 확률이
       차단 칸을 빼고 재정규화되고(화면 99% 인데 실제 분포가 다르다) 로그도 안 남는다.
       그래서 **닫힌 티커는 아예 등록되지 않게** 한다.

    ⚠️ 허용목록이 비어 있으면 FAV 칸 등록 자체를 막는다(배선 실수일 수 있으니 메시지로
       구분한다). 화폐 발행은 "실수로 열려 있는" 상태가 없어야 하고, 그 규칙은 등록에도
       같이 적용된다.

    ⚠️ 남는 리스크: 등록 뒤에 티커를 닫으면 다시 재추첨 경로가 열린다. 티커를 닫을 때는
       그 상품을 `point_shop_grantable=false` 로 같이 내릴 것(런북).
    """
    fav_tickers = {
        e.ticker
        for e in db.query(ProductGachaEntry)
        .filter(
            ProductGachaEntry.product_id == product_id,
            ProductGachaEntry.kind == GACHA_KIND_FAV,
        )
        .all()
    }
    if not fav_tickers:
        return
    if not allowed:
        raise ValueError(
            f"product {product_id} 뽑기 풀에 FAV 칸({sorted(fav_tickers)})이 있는데"
            " 지급 허용 티커 목록(grant_allowed_fav_tickers)이 비어 있다"
            " — 티커를 열거나 FAV 칸을 빼야 한다"
        )
    denied = sorted(fav_tickers - set(allowed))
    if denied:
        raise ValueError(
            f"product {product_id} 뽑기 풀의 FAV 티커 {denied} 는 지급 허용목록 밖이다"
            f" (허용: {sorted(allowed)}) — 그 칸에 당첨되면 지급이 거절되고 재추첨된다"
        )


def process_gacha_entry_row(db: Session, row: dict) -> bool:
    """뽑기 풀 한 칸 upsert. upsert 키는 (product_id, ticker) — 테이블 UNIQUE 와 같다."""
    weight = parse_int((row.get("weight") or "").replace(",", ""))
    amount = parse_int((row.get("amount") or "").replace(",", ""))
    product_id = parse_int(row["product_id"])
    # kind 는 **3상태**다 — 빈칸/컬럼 부재는 "변경 없음"이지 ITEM 이 아니다.
    #   2상태로 읽으면 kind 컬럼 없는 옛 시트를 재임포트하는 순간 **기존 FAV 칸이 ITEM 으로
    #   내려앉고**, 그 칸은 그 뒤로 얼로우리스트를 안 지나고 아이템 상한으로 재진다
    #   (이 커밋이 닫은 구멍이 임포트로 다시 열린다).
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

    existing = (
        db.query(ProductGachaEntry)
        .filter(
            ProductGachaEntry.product_id == product_id,
            ProductGachaEntry.ticker == ticker,
        )
        .first()
    )
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
            f" {csv_data['ticker']}) 변경:"
        )
        for field, (old, new) in changes.items():
            print(f"  - {field}: 기존({old}) → 변경({new})")
            setattr(existing, field, new)
        return True

    db.add(ProductGachaEntry(**csv_data))
    print(
        f"🆕 Gacha entry 추가: product {csv_data['product_id']} /"
        f" [{csv_data['kind']}] {csv_data['ticker']} x{csv_data['amount']}"
        f" (weight {csv_data['weight']})"
    )
    return True


def import_gacha_entries_from_csv(
    db: Session,
    csv_path: str,
    max_item_units=None,
    max_fav_units=None,
    allowed_fav_tickers=None,
) -> Tuple[int, int]:
    """
    뽑기 풀 CSV 임포트.

    ⚠️ 임포트가 끝나고 **등록 시점 검증 2종**을 돈다(둘 다 지급 시점에만 걸리면 유저가
       포인트를 쓴 뒤에 실패하는 것들이다):
         · 고정 구성품과의 배타 — assert_not_mixed_components
         · 요청 단위 수량 상한   — assert_gacha_entry_within_caps
         · FAV 지급 허용목록     — assert_gacha_fav_tickers_allowed (재추첨 차단)
       실패는 전체 롤백이다(부분 반영된 풀은 확률이 기획과 다른 표가 된다).
    """
    processed_count = 0
    changed_count = 0
    touched_products = set()

    try:
        with open(csv_path, mode="r", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            for row in reader:
                processed_count += 1
                touched_products.add(parse_int(row["product_id"]))
                if process_gacha_entry_row(db, row):
                    changed_count += 1

            db.flush()
            for product_id in touched_products:
                assert_not_mixed_components(db, product_id)
                assert_gacha_entry_within_caps(
                    db, product_id, max_item_units, max_fav_units
                )
                assert_gacha_fav_tickers_allowed(db, product_id, allowed_fav_tickers)

            db.commit()
            print(
                f"\n✅ Gacha 풀 동기화 완료! (처리: {processed_count}, 변경: {changed_count})"
            )
            return processed_count, changed_count

    except Exception as e:
        db.rollback()
        raise e
