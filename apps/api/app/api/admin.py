import json
import os
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Annotated, Any, Dict, List, Optional

import structlog
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    Security,
    UploadFile,
)
from fastapi.security import HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel
from shared.enums import GrantStatus, PlanetID, ReceiptStatus, Store
from shared.models.grant_outbox import GrantOutbox
from shared.models.product import (
    FungibleAssetProduct,
    FungibleItemProduct,
    Price,
    Product,
)
from shared.models.product_voucher_grant import ProductVoucherGrant
from shared.models.receipt import Receipt
from shared.schemas.message import SendGrantMessage
from shared.schemas.product import AdminProductSchema
from shared.schemas.receipt import FullReceiptSchema, RefundedReceiptSchema
from shared.utils.address import format_addr
from shared.utils.gacha import (
    GachaPoolError,
    build_gacha_result,
    claim_from_result,
    draw_entries,
)
from shared.utils.alert import send_slack_alert
from sqlalchemy import Date, and_, desc, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from app.celery import send_to_worker
from app.config import config
from app.dependencies import session
from app.grant_guard import (
    GrantGuardViolation,
    GrantWarning,
    alert_key,
    check_fav_tickers,
    enforce_claim_guards,
    enforce_grant_guards,
    limits_from_settings,
    namespace_of,
    should_alert,
    should_warn,
    validate_point_shop_grantable_eligible,
)
from app.utils import verify_token
from app.utils.apple import get_tx_ids
from app.utils.import_utils import (
    import_category_products_from_csv,
    import_fungible_assets_from_csv,
    import_fungible_items_from_csv,
    import_gacha_entries_from_csv,
    import_prices_from_csv,
    import_products_from_csv,
)
from app.utils.r2 import (
    CDN_URLS,
    R2_IMAGE_DETAIL_FOLDER,
    R2_IMAGE_LIST_FOLDER,
    R2_PRODUCT_KEYS,
    purge_cache,
    upload_csv_to_r2,
    upload_image_to_r2,
)
from app.utils.s3 import invalidate_cloudfront, upload_image_to_s3, upload_to_s3
from app.voucher_validation import (
    fetch_live_prize_tables,
    validate_product_voucher_eligible,
    validate_voucher_mapping,
)

logger = structlog.get_logger(__name__)

security = HTTPBearer()

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[
        Depends(verify_token),
        Security(security),
    ],  # 모든 admin 엔드포인트에 인증 필요
)


class PaginatedProductResponse(BaseModel):
    total: int
    # (PLD-1575) 유저용 `ProductSchema` 가 아니라 admin 전용 서브클래스를 쓴다 —
    #   `point_shop_grantable`(포인트 전용 상품 여부)이 상품 목록에서 보여야 한다.
    #   유저용 응답(`GET /api/product`)은 `ProductSchema` 그대로라 이 필드가 나가지 않는다.
    items: List[AdminProductSchema]


class ImportProductsRequest(BaseModel):
    environment: str
    csv_content: str


class ImportCategoryProductsRequest(BaseModel):
    csv_content: str


class ImportFungibleAssetsRequest(BaseModel):
    csv_content: str


class ImportFungibleItemsRequest(BaseModel):
    csv_content: str


class ImportPricesRequest(BaseModel):
    csv_content: str


class ImportGachaEntriesRequest(BaseModel):
    csv_content: str


class UploadCsvToR2Request(BaseModel):
    csv_content: str


class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"


class ReceiptSearchResponse(BaseModel):
    total: int
    items: List[FullReceiptSchema]


class UserReceiptCheckResponse(BaseModel):
    agent_address: str
    avatar_address: str
    year: int
    month: int
    has_purchases: bool
    total_amount: float
    purchase_count: int
    details: List[dict]


class CouragePassCheckResponse(BaseModel):
    agent_address: str
    avatar_address: str
    year: int
    month: int
    has_courage_pass: bool
    courage_pass_count: int
    courage_pass_details: List[dict]


class CouragePassCountResponse(BaseModel):
    count: int


class AdventureBossPassCheckResponse(BaseModel):
    agent_address: str
    avatar_address: str
    year: int
    month: int
    has_adventure_boss_pass: bool
    adventure_boss_pass_count: int
    adventure_boss_pass_details: List[dict]


class NonPassPurchaseCheckResponse(BaseModel):
    agent_address: str
    avatar_address: str
    year: int
    month: int
    total_amount: Decimal
    purchase_count: int
    meets_amount_threshold: bool
    meets_count_threshold: bool
    non_pass_purchases: List[dict]


class TokenSales(BaseModel):
    ticker: str
    decimal_places: int
    total_amount: Decimal


class PlanetTokenSales(BaseModel):
    tokens: List[TokenSales]


class ProductSalesResponse(BaseModel):
    year: int
    month: int
    planets: Dict[str, PlanetTokenSales]


# @router.post("/update-price")
# def update_price(store: Store, sess=Depends(session)):
#     updated_product_count, updated_price_count = (0, 0)
#
#     if store in (Store.GOOGLE, Store.GOOGLE_TEST):
#         updated_product_count, updated_price_count = update_google_price(
#             sess, settings.GOOGLE_CREDENTIAL, settings.GOOGLE_PACKAGE_NAME
#         )
#     elif store in (Store.APPLE, Store.APPLE_TEST):
#         pass
#     elif store == Store.TEST:
#         pass
#     else:
#         raise ValueError(f"{store.name} is unsupported store.")
#
#     return f"{updated_price_count} prices in {updated_product_count} products are updated."


@router.get("/refunded", response_model=List[RefundedReceiptSchema])
def fetch_refunded(
    start: Annotated[
        Optional[int],
        Query(
            description="Where to start to find refunded receipt in unix timestamp format. "
            "If not provided, search starts from 24 hours ago."
        ),
    ] = None,
    limit: Annotated[
        int, Query(description="Limitation of receipt in response.")
    ] = 100,
    sess=Depends(session),
):
    """
    # List refunded receipts
    ---

    Get list of refunded receipts. This only returns user-refunded receipts.
    """
    if not start:
        start_date = (datetime.utcnow() - timedelta(hours=24)).date()
    else:
        start_date = datetime.fromtimestamp(start)

    return sess.scalars(
        select(Receipt)
        .where(Receipt.status == ReceiptStatus.REFUNDED_BY_BUYER)
        .where(Receipt.updated_at.cast(Date) >= start_date)
        .order_by(desc(Receipt.updated_at))
        .limit(limit)
    ).fetchall()


@router.get("/receipt", response_model=List[FullReceiptSchema])
def receipt_list(page: int = 0, pp: int = 50, sess=Depends(session)):
    return sess.scalars(
        select(Receipt)
        .options(joinedload(Receipt.product))
        .order_by(desc(Receipt.purchased_at))
        .offset(pp * page)
        .limit(pp)
    ).fetchall()


@router.get("/products", response_model=PaginatedProductResponse)
def product_list(
    limit: int = Query(default=20, ge=1, le=100),  # 한 페이지당 기본 20개, 최대 100개
    offset: int = Query(default=0, ge=0),  # 시작 위치
    sess=Depends(session),
):
    """상품 정보를 조회합니다.

    Args:
        limit: 한 페이지당 반환할 항목 수 (기본값: 20, 최대: 100)
        offset: 시작 위치 (기본값: 0)
    """
    # 기본 쿼리 생성
    # ID 역순으로 정렬 (항상 일관된 순서 보장)
    base_query = select(Product).order_by(desc(Product.id))

    # 전체 결과 수 계산
    total_count = sess.scalar(select(func.count()).select_from(base_query.subquery()))

    # 페이지네이션 적용
    products = sess.scalars(base_query.offset(offset).limit(limit)).all()

    # 페이지네이션 정보 추가
    return PaginatedProductResponse(
        total=total_count,
        items=products,
    )


@router.post("/products/import")
def import_products_endpoint(request: ImportProductsRequest, sess=Depends(session)):
    """
    CSV 데이터에서 상품 정보를 가져와 데이터베이스에 임포트합니다.

    Args:
        environment: 'internal' 또는 'mainnet'
        csv_content: CSV 파일 내용 (문자열)
    """
    try:
        # 임시 CSV 파일 생성
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".csv"
        ) as temp_file:
            temp_file.write(request.csv_content)
            temp_path = temp_file.name

        try:
            # (C1b) CSV에 **실제 voucher 값이 있는 행**이 있을 때만 라이브 정책 fetch.
            #   컬럼 유무(헤더 substring)가 아니라 데이터 유무로 판정 → voucher 없는 일반 import은 포탈 미의존.
            import csv as _csv_mod
            import io as _io

            _reader = _csv_mod.DictReader(_io.StringIO(request.csv_content or ""))
            _fields = _reader.fieldnames or []
            _vcols = [
                f"voucher_ticket_type_{i}" for i in range(1, 4)
            ]  # VOUCHER_SLOTS=3
            _has_voucher_data = any(v in _fields for v in _vcols) and any(
                any((r.get(v) or "").strip() for v in _vcols) for r in _reader
            )
            voucher_tables = None
            voucher_cap = None
            if _has_voucher_data:
                if config.voucher_grant_max_ncg_per_grant is None and config.stage in (
                    "production",
                    "mainnet",
                ):
                    raise HTTPException(
                        status_code=400,
                        detail="prod에선 voucher_grant_max_ncg_per_grant(C3-lite cap) 설정 후에만 voucher CSV import 가능",
                    )
                voucher_tables = fetch_live_prize_tables(config.portal_prize_tables_url)
                voucher_cap = config.voucher_grant_max_ncg_per_grant

            # 비대화형 모드로 임포트 실행
            processed_count, updated_count = import_products_from_csv(
                sess,
                temp_path,
                request.environment,
                interactive=False,
                voucher_tables=voucher_tables,
                voucher_cap=voucher_cap,
                # (PLD-1562) gacha_draw_count 를 바꾸는 행의 풀 상한 재검증용.
                max_item_units=limits_from_settings(config).max_item_units_per_request,
                max_fav_units=limits_from_settings(config).max_fav_units_per_request,
                # (PLD-1575) `point_shop_grantable` 을 켜는 행의 FAV 티커 선검증에 쓴다.
                #   가드가 **지급 시점에 보는 값과 같아야** 한다 — 임포트는 200 인데 실주문이
                #   전부 거절되는 상태를 만들지 않는다(미주입 503 / 목록 밖 400).
                allowed_fav_tickers=limits_from_settings(config).allowed_fav_tickers,
            )

            return {
                "message": "상품 데이터가 성공적으로 임포트되었습니다.",
                "processed_count": processed_count,
                "updated_count": updated_count,
            }
        finally:
            # 임시 파일 삭제
            os.unlink(temp_path)

    except GrantGuardViolation as e:
        # (PLD-1575) 백오피스 임포트 화면은 응답 **본문을 읽지 않는다**(IAPRepository 의
        #   EnsureSuccessStatusCode) → 운영자에게는 "503" 만 보이고 `[fav_tickers_unset] …` 이
        #   사라진다. 유일한 진단 문자열이므로 서버 로그에는 반드시 남긴다.
        logger.error(
            "product csv import rejected by grant guard",
            reason=e.reason,
            detail=e.detail,
        )
        raise
    except HTTPException:
        raise  # fetch(502/409/503)·prod게이트(400)·grant 가드(503/400) 등 명시 상태코드 보존
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/products/categories/import")
def import_category_products_endpoint(
    request: ImportCategoryProductsRequest, sess=Depends(session)
):
    """
    CSV 데이터에서 카테고리-상품 관계 정보를 가져와 데이터베이스에 임포트합니다.

    Args:
        csv_content: CSV 파일 내용 (문자열)
    """
    try:
        # 임시 CSV 파일 생성
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".csv"
        ) as temp_file:
            temp_file.write(request.csv_content)
            temp_path = temp_file.name

        try:
            # 임포트 실행
            processed_count, added_count = import_category_products_from_csv(
                sess, temp_path
            )

            return {
                "message": "카테고리-상품 관계 데이터가 성공적으로 임포트되었습니다.",
                "processed_count": processed_count,
                "added_count": added_count,
            }
        finally:
            # 임시 파일 삭제
            os.unlink(temp_path)

    except Exception as e:
        print(e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/products/fungible-assets/import")
def import_fungible_assets_endpoint(
    request: ImportFungibleAssetsRequest, sess=Depends(session)
):
    """
    CSV 데이터에서 대체 가능 자산 정보를 가져와 데이터베이스에 임포트합니다.

    Args:
        csv_content: CSV 파일 내용 (문자열)
    """
    try:
        # 임시 CSV 파일 생성
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".csv"
        ) as temp_file:
            temp_file.write(request.csv_content)
            temp_path = temp_file.name

        try:
            # 임포트 실행
            processed_count, changed_count = import_fungible_assets_from_csv(
                sess, temp_path
            )

            return {
                "message": "대체 가능 자산 데이터가 성공적으로 임포트되었습니다.",
                "processed_count": processed_count,
                "changed_count": changed_count,
            }
        finally:
            # 임시 파일 삭제
            os.unlink(temp_path)

    except Exception as e:
        print(e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/products/fungible-items/import")
def import_fungible_items_endpoint(
    request: ImportFungibleItemsRequest, sess=Depends(session)
):
    """
    CSV 데이터에서 대체 가능 아이템 정보를 가져와 데이터베이스에 임포트합니다.

    Args:
        csv_content: CSV 파일 내용 (문자열)
    """
    try:
        # 임시 CSV 파일 생성
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".csv"
        ) as temp_file:
            temp_file.write(request.csv_content)
            temp_path = temp_file.name

        try:
            # 임포트 실행
            processed_count, changed_count = import_fungible_items_from_csv(
                sess, temp_path
            )

            return {
                "message": "대체 가능 아이템 데이터가 성공적으로 임포트되었습니다.",
                "processed_count": processed_count,
                "changed_count": changed_count,
            }
        finally:
            # 임시 파일 삭제
            os.unlink(temp_path)

    except Exception as e:
        print(e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/products/gacha/import")
def import_gacha_entries_endpoint(
    request: ImportGachaEntriesRequest, sess=Depends(session)
):
    """
    # (PLD-1562) 뽑기 풀 임포트
    ---
    컬럼: `product_id, name, weight, kind, ticker, amount, sheet_item_id, decimal_places`
      · `kind` = `ITEM` | `FAV` (생략 시 ITEM). 룬스톤·소울스톤·크리스탈은 **FAV** 다
      · `ticker` = `Item_NT_400000` / `FAV__RUNESTONE_HP` (옛 컬럼명 `fungible_item_id` 도 읽는다)
      · `sheet_item_id` = 아이템 아이콘용. **FAV 는 비워 둘 것**
      · `decimal_places` = FAV 자릿수(생략 시 0). 아이템은 항상 0

    ⚠️ FAV 칸을 넣으려면 `grant_allowed_fav_tickers` 에 그 티커가 열려 있어야 한다.
       닫혀 있으면 그 칸에 당첨된 주문이 **503** 으로 멈춘다(화폐 발행은 명시적으로만 연다).

    `fungible-items/import` 와 같은 모양(상품당 여러 행)이다. **upsert 이고 REPLACE 가
    아니다** — 부분 CSV 로 나머지 칸이 조용히 사라지면 확률이 통째로 바뀌는 사고가 된다.
    칸을 빼려면 명시적으로 지워야 한다.

    이미 뽑힌 주문은 결과가 아웃박스에 동결돼 있어 이 임포트의 영향을 받지 않는다
    (표를 고치는 것이 뒷문 재추첨이 되지 않게 한 설계 — grant_outbox 모델 주석).
    """
    try:
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".csv"
        ) as temp_file:
            temp_file.write(request.csv_content)
            temp_path = temp_file.name

        try:
            _limits = limits_from_settings(config)
            processed_count, changed_count = import_gacha_entries_from_csv(
                sess,
                temp_path,
                _limits.max_item_units_per_request,
                _limits.max_fav_units_per_request,
                _limits.allowed_fav_tickers,
            )
            # 민터 상금표를 바꾸는 write 다 — 무엇이 얼마나 어떤 확률로 발행되는지를 정하는
            #   변경인데 감사 흔적이 stdout 뿐이면 토큰이 유출돼도 채널에 아무것도 안 뜬다.
            #   화이트리스트 플래그 하나 켜는 데도 알림을 남기는 선례와 맞춘다.
            if changed_count:
                logger.info(
                    "gacha_pool_import",
                    processed=processed_count,
                    changed=changed_count,
                )
                send_slack_alert(
                    config.iap_alert_webhook_url,
                    f":game_die: [IAP gacha pool] 뽑기 풀 변경 {changed_count}건"
                    f" (처리 {processed_count}건) — 확률/상금이 바뀌었을 수 있습니다"
                    f" ({config.stage})",
                )
            return {
                "message": "뽑기 풀 데이터가 성공적으로 임포트되었습니다.",
                "processed_count": processed_count,
                "changed_count": changed_count,
            }
        finally:
            os.unlink(temp_path)

    except Exception as e:
        print(e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/prices/import")
def import_prices_endpoint(request: ImportPricesRequest, sess=Depends(session)):
    """
    CSV 데이터에서 가격 정보를 가져와 데이터베이스에 임포트합니다.

    Args:
        csv_content: CSV 파일 내용 (문자열)
    """
    try:
        # 임시 CSV 파일 생성
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".csv"
        ) as temp_file:
            temp_file.write(request.csv_content)
            temp_path = temp_file.name

        try:
            # 비대화형 모드로 임포트 실행
            processed_count, updated_count = import_prices_from_csv(sess, temp_path)

            return {
                "message": "가격 데이터가 성공적으로 임포트되었습니다.",
                "processed_count": processed_count,
                "updated_count": updated_count,
            }
        finally:
            # 임시 파일 삭제
            os.unlink(temp_path)

    except Exception as e:
        print(e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/r2/product")
def upload_product_csv_to_r2_endpoint(request: UploadCsvToR2Request):
    """
    CSV 파일을 R2에 업로드하고 캐시를 초기화합니다.

    Args:
        csv_content: CSV 파일 내용 (문자열)
    """
    try:
        # 임시 CSV 파일 생성
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".csv"
        ) as temp_file:
            temp_file.write(request.csv_content)
            temp_path = temp_file.name

        try:
            # R2에 업로드
            results = []
            for r2_key in R2_PRODUCT_KEYS:
                upload_csv_to_r2(temp_path, r2_key)

            # 캐시 무효화
            for zone_id, cdn_url in CDN_URLS.items():
                result = purge_cache(zone_id, cdn_url, r2_key)
                results.append(result)

            cache_result = all(results)
            if cache_result:
                message = "Product 번역어 파일이 성공적으로 업로드되었습니다."
            else:
                message = "Product 번역어 파일 업로드 실패"
            return {"message": message}
        finally:
            # 임시 파일 삭제
            os.unlink(temp_path)

    except Exception as e:
        print(e)
        raise HTTPException(status_code=400, detail=str(e))


# TODO R2 마이그레이션 완료후 S3 엔드포인트 삭제
@router.post("/s3/product")
def upload_product_csv_to_s3_endpoint(request: UploadCsvToR2Request):
    """
    CSV 파일을 S3에 업로드하고 CloudFront 캐시를 초기화합니다.

    Args:
        csv_content: CSV 파일 내용 (문자열)
    """
    try:
        # 임시 CSV 파일 생성
        import os
        import tempfile

        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".csv"
        ) as temp_file:
            temp_file.write(request.csv_content)
            temp_path = temp_file.name

        try:
            # S3에 업로드
            success = upload_to_s3(temp_path)
            if not success:
                raise HTTPException(status_code=400, detail="S3 업로드 실패")

            # CloudFront 캐시 초기화
            invalidate_cloudfront()

            return {"message": "CSV 파일이 성공적으로 업로드되었고 캐시 초기화가 요청되었습니다."}
        finally:
            # 임시 파일 삭제
            os.unlink(temp_path)

    except Exception as e:
        print(e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/r2/images")
async def upload_multiple_images_to_r2(files: List[UploadFile] = File(...)):
    """
    여러 이미지 파일을 R2에 업로드합니다.

    Args:
        files: 이미지 파일 리스트 (multipart/form-data)

    Note:
        - PNG 파일만 업로드 가능
        - 파일당 최대 크기: 10MB
    """
    try:
        results = []
        r2_keys = []
        for file in files:
            # PNG 파일 검증
            if not file.filename or not file.filename.lower().endswith(".png"):
                results.append(
                    {
                        "filename": file.filename or "unknown",
                        "status": "failed",
                        "error": "PNG 파일만 업로드 가능합니다.",
                    }
                )
                continue

            # 파일 크기 검증 (10MB 제한)
            MAX_SIZE = 10 * 1024 * 1024  # 10MB
            content = await file.read()
            if len(content) > MAX_SIZE:
                results.append(
                    {
                        "filename": file.filename,
                        "status": "failed",
                        "error": "파일이 너무 큽니다 (최대 10MB)",
                    }
                )
                continue

            try:
                # 이미지를 임시 파일로 저장
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".png"
                ) as temp_file:
                    temp_file.write(content)
                    temp_path = temp_file.name

                try:
                    # R2에 업로드
                    is_list_image = file.filename.endswith("_s.png")
                    file_name = (
                        file.filename.replace("_s.png", ".png")
                        if is_list_image
                        else file.filename
                    )
                    if is_list_image:
                        for folder in R2_IMAGE_LIST_FOLDER:
                            r2_key = f"{folder}{file_name}"
                            upload_image_to_r2(temp_path, r2_key)
                            results.append(
                                {"filename": file.filename, "status": "success"}
                            )
                            r2_keys.append(r2_key)
                    else:
                        for folder in R2_IMAGE_DETAIL_FOLDER:
                            r2_key = f"{folder}{file_name}"
                            upload_image_to_r2(temp_path, r2_key)
                            results.append(
                                {"filename": file.filename, "status": "success"}
                            )
                            r2_keys.append(r2_key)
                finally:
                    # 임시 파일 삭제
                    os.unlink(temp_path)

            except Exception as e:
                results.append(
                    {"filename": file.filename, "status": "failed", "error": str(e)}
                )

        # 캐시 무효화
        for zone_id, cdn_url in CDN_URLS.items():
            for r2_key in r2_keys:
                purge_cache(zone_id, cdn_url, r2_key)

        success_count = sum(1 for r in results if r["status"] == "success")
        failed_count = len(results) - success_count

        return {
            "message": f"{success_count}개의 이미지가 업로드되었습니다. {failed_count}개 실패.",
            "results": results,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# TODO R2 마이그레이션 완료후 S3 엔드포인트 삭제
@router.post("/s3/images")
async def upload_multiple_images_to_s3(files: List[UploadFile] = File(...)):
    """
    여러 이미지 파일을 S3에 업로드합니다.

    Args:
        files: 이미지 파일 리스트 (multipart/form-data)

    Note:
        - PNG 파일만 업로드 가능
        - 파일당 최대 크기: 10MB
    """
    try:
        results = []
        for file in files:
            # PNG 파일 검증
            if not file.filename or not file.filename.lower().endswith(".png"):
                results.append(
                    {
                        "filename": file.filename or "unknown",
                        "status": "failed",
                        "error": "PNG 파일만 업로드 가능합니다.",
                    }
                )
                continue

            # 파일 크기 검증 (10MB 제한)
            MAX_SIZE = 10 * 1024 * 1024  # 10MB
            content = await file.read()
            if len(content) > MAX_SIZE:
                results.append(
                    {
                        "filename": file.filename,
                        "status": "failed",
                        "error": "파일이 너무 큽니다 (최대 10MB)",
                    }
                )
                continue

            try:
                # 이미지를 임시 파일로 저장
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".png"
                ) as temp_file:
                    temp_file.write(content)
                    temp_path = temp_file.name

                try:
                    # S3에 업로드
                    upload_image_to_s3(temp_path, file.filename)
                    results.append({"filename": file.filename, "status": "success"})
                finally:
                    # 임시 파일 삭제
                    os.unlink(temp_path)

            except Exception as e:
                results.append(
                    {"filename": file.filename, "status": "failed", "error": str(e)}
                )

        # CloudFront 캐시 초기화
        invalidate_cloudfront()

        success_count = sum(1 for r in results if r["status"] == "success")
        failed_count = len(results) - success_count
        return {
            "message": f"{success_count}개의 이미지가 업로드되었습니다. {failed_count}개 실패.",
            "results": results,
        }

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/receipts", response_model=ReceiptSearchResponse)
def search_receipts(
    start_date: Optional[datetime] = Query(None, description="검색 시작 날짜 (ISO 형식)"),
    end_date: Optional[datetime] = Query(None, description="검색 종료 날짜 (ISO 형식)"),
    status: Optional[ReceiptStatus] = Query(None, description="영수증 상태로 필터링"),
    planet_id: Optional[bytes] = Query(None, description="행성 ID로 필터링"),
    agent_addr: Optional[str] = Query(None, description="에이전트 주소로 필터링"),
    store: Optional[Store] = Query(None, description="스토어 타입으로 필터링"),
    order_id: Optional[str] = Query(None, description="주문 ID로 필터링"),
    apple_order_id: Optional[str] = Query(None, description="애플 주문 ID로 필터링"),
    page: int = Query(0, ge=0, description="페이지 번호"),
    page_size: int = Query(50, ge=1, le=100, description="페이지당 항목 수"),
    sess=Depends(session),
):
    """
    영수증 목록을 검색하고 필터링합니다.

    - 날짜 범위로 검색 가능
    - 상태별 필터링 가능
    - 행성 ID로 필터링 가능
    - 에이전트 주소로 필터링 가능
    - 스토어 타입으로 필터링 가능
    - 주문 ID로 필터링 가능
    - 애플 주문 ID로 필터링 가능
    - 정렬 옵션 지원
    - 페이지네이션 지원
    """
    query = select(Receipt).options(joinedload(Receipt.product))

    # 필터 조건 적용
    conditions = []

    if start_date:
        conditions.append(Receipt.purchased_at >= start_date)
    if end_date:
        conditions.append(Receipt.purchased_at <= end_date)
    if status:
        conditions.append(Receipt.status == status)
    if planet_id:
        conditions.append(Receipt.planet_id == planet_id)
    if agent_addr:
        if not agent_addr.startswith("0x"):
            target_addr = "0x" + agent_addr
        else:
            target_addr = agent_addr
        conditions.append(Receipt.agent_addr == target_addr.lower())
    if store:
        conditions.append(Receipt.store == store)
    if order_id:
        conditions.append(Receipt.order_id == order_id)
    if apple_order_id:
        tx_ids = get_tx_ids(
            apple_order_id,
            config.apple_credential,
            config.apple_bundle_id,
            config.apple_key_id,
            config.apple_issuer_id,
        )
        conditions.append(Receipt.order_id.in_(tx_ids))
    if conditions:
        query = query.where(and_(*conditions))

    query = query.order_by(desc(Receipt.purchased_at))

    # 전체 결과 수 계산
    total_count = sess.scalar(select(func.count()).select_from(query.subquery()))

    # 페이지네이션 적용
    query = query.offset(page * page_size).limit(page_size)

    # 결과 조회
    receipts = sess.scalars(query).all()

    return ReceiptSearchResponse(total=total_count, items=receipts)


@router.get("/user-receipts/courage-pass", response_model=CouragePassCheckResponse)
def check_courage_pass_purchases(
    agent_address: str = Query(..., description="9c agent 주소"),
    avatar_address: str = Query(..., description="9c avatar 주소"),
    year: int = Query(..., ge=2020, le=2030, description="조회할 연도"),
    month: int = Query(..., ge=1, le=12, description="조회할 월"),
    planet_id: Optional[bytes] = Query(None, description="행성 ID로 필터링"),
    sess=Depends(session),
):
    """
    해당 년월 유료 커리지패스 구매확인

    Args:
        agent_address: 9c agent 주소
        avatar_address: 9c avatar 주소
        year: 조회할 연도
        month: 조회할 월

    Returns:
        커리지패스 구매 여부와 상세 정보
    """
    # 주소 형식 정규화
    if not agent_address.startswith("0x"):
        agent_address = "0x" + agent_address
    if not avatar_address.startswith("0x"):
        avatar_address = "0x" + avatar_address

    agent_address = agent_address.lower()
    avatar_address = avatar_address.lower()

    # 커리지패스 구매 내역 조회
    courage_pass_receipts = Receipt.get_user_receipts_by_month(
        session=sess,
        agent_addr=agent_address,
        avatar_addr=avatar_address,
        year=year,
        month=month,
        include_product=True,
        only_paid_products=True,
        sku_pattern="couragepass\\d+premium",
        planet_id=planet_id,
    )

    courage_pass_details = []
    for receipt in courage_pass_receipts:
        if receipt.product:
            courage_pass_details.append(
                {
                    "order_id": receipt.order_id,
                    "purchased_at": receipt.purchased_at.isoformat(),
                    "google_sku": receipt.product.google_sku,
                    "product_name": receipt.product.name,
                    "amount": receipt.amount if hasattr(receipt, "amount") else None,
                }
            )

    return CouragePassCheckResponse(
        agent_address=agent_address,
        avatar_address=avatar_address,
        year=year,
        month=month,
        has_courage_pass=len(courage_pass_receipts) > 0,
        courage_pass_count=len(courage_pass_receipts),
        courage_pass_details=courage_pass_details,
    )


@router.get(
    "/user-receipts/courage-pass-count", response_model=CouragePassCountResponse
)
def check_courage_pass_count(
    agent_address: str = Query(..., description="9c agent 주소"),
    year: int = Query(..., ge=2020, le=2030, description="조회할 연도"),
    month: int = Query(..., ge=1, le=12, description="조회할 월"),
    avatar_address: Optional[str] = Query(None, description="9c avatar 주소 (옵셔널)"),
    planet_id: Optional[bytes] = Query(None, description="행성 ID로 필터링"),
    sess=Depends(session),
):
    """
    해당 년월 유료 커리지패스 구매 숫자 조회

    Args:
        agent_address: 9c agent 주소
        year: 조회할 연도
        month: 조회할 월
        avatar_address: 9c avatar 주소 (옵셔널, 제공되지 않으면 agent의 모든 avatar 합산)

    Returns:
        커리지패스 구매 숫자
    """
    # 주소 형식 정규화
    if not agent_address.startswith("0x"):
        agent_address = "0x" + agent_address
    agent_address = agent_address.lower()

    normalized_avatar_address = None
    if avatar_address:
        if not avatar_address.startswith("0x"):
            normalized_avatar_address = "0x" + avatar_address
        else:
            normalized_avatar_address = avatar_address
        normalized_avatar_address = normalized_avatar_address.lower()

    # 기존 메서드 재사용
    courage_pass_receipts = Receipt.get_user_receipts_by_month(
        session=sess,
        agent_addr=agent_address,
        avatar_addr=normalized_avatar_address,
        year=year,
        month=month,
        include_product=True,
        only_paid_products=True,
        sku_pattern="couragepass\\d+premium",
        planet_id=planet_id,
    )

    return CouragePassCountResponse(count=len(courage_pass_receipts))


@router.get(
    "/user-receipts/adventure-boss-pass", response_model=AdventureBossPassCheckResponse
)
def check_adventure_boss_pass_purchases(
    agent_address: str = Query(..., description="9c agent 주소"),
    avatar_address: str = Query(..., description="9c avatar 주소"),
    year: int = Query(..., ge=2020, le=2030, description="조회할 연도"),
    month: int = Query(..., ge=1, le=12, description="조회할 월"),
    planet_id: Optional[bytes] = Query(None, description="행성 ID로 필터링"),
    sess=Depends(session),
):
    """
    해당 년월 유료 어드벤쳐보스패스 구매확인

    Args:
        agent_address: 9c agent 주소
        avatar_address: 9c avatar 주소
        year: 조회할 연도
        month: 조회할 월

    Returns:
        어드벤쳐보스패스 구매 여부와 상세 정보
    """
    # 주소 형식 정규화
    if not agent_address.startswith("0x"):
        agent_address = "0x" + agent_address
    if not avatar_address.startswith("0x"):
        avatar_address = "0x" + avatar_address

    agent_address = agent_address.lower()
    avatar_address = avatar_address.lower()

    # 어드벤쳐보스패스 구매 내역 조회
    adventure_boss_pass_receipts = Receipt.get_user_receipts_by_month(
        session=sess,
        agent_addr=agent_address,
        avatar_addr=avatar_address,
        year=year,
        month=month,
        include_product=True,
        only_paid_products=True,
        sku_pattern="adventurebosspass\\d+premium",
        planet_id=planet_id,
    )

    adventure_boss_pass_details = []
    for receipt in adventure_boss_pass_receipts:
        if receipt.product:
            adventure_boss_pass_details.append(
                {
                    "order_id": receipt.order_id,
                    "purchased_at": receipt.purchased_at.isoformat(),
                    "google_sku": receipt.product.google_sku,
                    "product_name": receipt.product.name,
                    "amount": receipt.amount if hasattr(receipt, "amount") else None,
                }
            )

    return AdventureBossPassCheckResponse(
        agent_address=agent_address,
        avatar_address=avatar_address,
        year=year,
        month=month,
        has_adventure_boss_pass=len(adventure_boss_pass_receipts) > 0,
        adventure_boss_pass_count=len(adventure_boss_pass_receipts),
        adventure_boss_pass_details=adventure_boss_pass_details,
    )


@router.get(
    "/user-receipts/non-pass-amount", response_model=NonPassPurchaseCheckResponse
)
def check_non_pass_purchase_amount(
    agent_address: str = Query(..., description="9c agent 주소"),
    avatar_address: str = Query(..., description="9c avatar 주소"),
    year: int = Query(..., ge=2020, le=2030, description="조회할 연도"),
    month: int = Query(..., ge=1, le=12, description="조회할 월"),
    amount_threshold: Decimal = Query(
        Decimal("100.0"), description="금액 임계값 (기본값: 100.0)"
    ),
    planet_id: Optional[bytes] = Query(None, description="행성 ID로 필터링"),
    sess=Depends(session),
):
    """
    해당 년월 패스관련상품을 제외한 구매한 금액이 100$이상인지 확인

    Args:
        agent_address: 9c agent 주소
        avatar_address: 9c avatar 주소
        year: 조회할 연도
        month: 조회할 월
        amount_threshold: 금액 임계값 (기본값: 100.0)

    Returns:
        패스 제외 구매 금액과 임계값 충족 여부
    """
    # 주소 형식 정규화
    if not agent_address.startswith("0x"):
        agent_address = "0x" + agent_address
    if not avatar_address.startswith("0x"):
        avatar_address = "0x" + avatar_address

    agent_address = agent_address.lower()
    avatar_address = avatar_address.lower()

    # 패스 제외 구매 내역 조회
    non_pass_receipts = Receipt.get_user_receipts_by_month(
        session=sess,
        agent_addr=agent_address,
        avatar_addr=avatar_address,
        year=year,
        month=month,
        include_product=True,
        only_paid_products=True,
        exclude_sku_patterns=["adventurebosspass\\d+premium", "couragepass\\d+premium"],
        planet_id=planet_id,
    )

    # 총 금액 계산
    total_amount = Decimal("0.0")
    non_pass_purchases = []

    for receipt in non_pass_receipts:
        if receipt.product:
            # 가격 정보 조회
            price_query = (
                sess.query(Price)
                .filter(and_(Price.product_id == receipt.product.id, Price.price > 0))
                .first()
            )

            amount = Decimal(str(price_query.price)) if price_query else Decimal("0.0")
            total_amount += amount

            non_pass_purchases.append(
                {
                    "order_id": receipt.order_id,
                    "purchased_at": receipt.purchased_at.isoformat(),
                    "google_sku": receipt.product.google_sku,
                    "product_name": receipt.product.name,
                    "amount": amount,
                }
            )

    return NonPassPurchaseCheckResponse(
        agent_address=agent_address,
        avatar_address=avatar_address,
        year=year,
        month=month,
        total_amount=total_amount,
        purchase_count=len(non_pass_receipts),
        meets_amount_threshold=total_amount >= amount_threshold,
        meets_count_threshold=len(non_pass_receipts) >= 1,
        non_pass_purchases=non_pass_purchases,
    )


@router.get(
    "/user-receipts/non-pass-count", response_model=NonPassPurchaseCheckResponse
)
def check_non_pass_purchase_count(
    agent_address: str = Query(..., description="9c agent 주소"),
    avatar_address: str = Query(..., description="9c avatar 주소"),
    year: int = Query(..., ge=2020, le=2030, description="조회할 연도"),
    month: int = Query(..., ge=1, le=12, description="조회할 월"),
    count_threshold: int = Query(1, ge=1, description="구매 건수 임계값 (기본값: 1)"),
    planet_id: Optional[bytes] = Query(None, description="행성 ID로 필터링"),
    sess=Depends(session),
):
    """
    해당 년월 패스관련상품을 제외한 구매건이 1건이상인지 확인

    Args:
        agent_address: 9c agent 주소
        avatar_address: 9c avatar 주소
        year: 조회할 연도
        month: 조회할 월
        count_threshold: 구매 건수 임계값 (기본값: 1)

    Returns:
        패스 제외 구매 건수와 임계값 충족 여부
    """
    # 주소 형식 정규화
    if not agent_address.startswith("0x"):
        agent_address = "0x" + agent_address
    if not avatar_address.startswith("0x"):
        avatar_address = "0x" + avatar_address

    agent_address = agent_address.lower()
    avatar_address = avatar_address.lower()

    # 패스 제외 구매 내역 조회
    non_pass_receipts = Receipt.get_user_receipts_by_month(
        session=sess,
        agent_addr=agent_address,
        avatar_addr=avatar_address,
        year=year,
        month=month,
        include_product=True,
        only_paid_products=True,
        exclude_sku_patterns=["adventurebosspass\\d+premium", "couragepass\\d+premium"],
        planet_id=planet_id,
    )

    # 총 금액 계산
    total_amount = Decimal("0.0")
    non_pass_purchases = []

    for receipt in non_pass_receipts:
        if receipt.product:
            # 가격 정보 조회
            price_query = (
                sess.query(Price)
                .filter(and_(Price.product_id == receipt.product.id, Price.price > 0))
                .first()
            )

            amount = Decimal(str(price_query.price)) if price_query else Decimal("0.0")
            total_amount += amount

            non_pass_purchases.append(
                {
                    "order_id": receipt.order_id,
                    "purchased_at": receipt.purchased_at.isoformat(),
                    "google_sku": receipt.product.google_sku,
                    "product_name": receipt.product.name,
                    "amount": amount,
                }
            )

    return NonPassPurchaseCheckResponse(
        agent_address=agent_address,
        avatar_address=avatar_address,
        year=year,
        month=month,
        total_amount=total_amount,
        purchase_count=len(non_pass_receipts),
        meets_amount_threshold=total_amount >= Decimal("100.0"),  # 기본 금액 임계값
        meets_count_threshold=len(non_pass_receipts) >= count_threshold,
        non_pass_purchases=non_pass_purchases,
    )


_MAINNET_PLANET_NAMES = {
    PlanetID.ODIN.value: "ODIN",
    PlanetID.HEIMDALL.value: "HEIMDALL",
}

# SKUs matching this pattern are season-pass style purchases where actual
# token grants are performed by the SeasonPass service (see purchase.py:
# `if "pass" in product.google_sku`), not by IAP. Including them here would
# double-count against SeasonPass's own reward-claims stats.
_SEASON_PASS_SKU_ILIKE = "%pass%"


@router.get("/stats/product-sales", response_model=ProductSalesResponse)
def get_product_sales(
    year: int = Query(..., ge=2020, le=2030, description="조회할 연도"),
    month: int = Query(..., ge=1, le=12, description="조회할 월"),
    sess=Depends(session),
):
    """
    메인넷(오딘, 헤임달) 플래닛별 월간 **결제 기반** 토큰 판매량 집계

    지정한 연/월 동안 VALID 상태의 **영수증(`receipt`)** 을 기준으로,
    grant_items tx와 동일한 ticker 포맷(FAV__{ticker}, Item_NT_{sheet_item_id})으로
    플래닛별 판매 토큰량을 반환합니다.
    날짜 필터는 UTC 기준이며, DB의 created_at(KST)을 UTC로 변환하여 비교합니다.

    시즌패스 계열(google_sku에 "pass" 포함) 영수증은 실제 지급을 IAP가 아닌
    SeasonPass 서비스가 담당하므로 IAP 통계에서 제외됩니다.

    ⚠️ **"온체인 총 발행량"이 아니다.** (PLD-1564) 영수증 없는 지급(`grant_outbox` —
    포탈 포인트샵의 무상 지급)은 `receipt` 행을 만들지 않아 이 집계에 **포함되지 않는다**.
    매출·정산 리포트로는 이게 맞다 — 무상 지급을 매출로 세면 정산이 오염된다(그래서 지급
    아웃박스를 receipt 와 분리했다: shared/models/grant_outbox.py). 발행량 관점의 수치가
    필요하면 `grant_outbox`(status=GRANTED) 를 따로 합산해야 한다.

    TODO(PLD-1575): 발행량 집계가 필요해지면 **별 엔드포인트**로 만들 것. 이 응답에 무상
    지급을 더하면 같은 필드가 매출과 발행량을 동시에 뜻하게 되고, 이 값을 매출로 읽는
    기존 소비자(백오피스 리포트)가 조용히 틀린다.
    """
    utc_start = datetime(year, month, 1)
    utc_end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)

    mainnet_planet_ids = [PlanetID.ODIN.value, PlanetID.HEIMDALL.value]
    base_filter = and_(
        Receipt.status == ReceiptStatus.VALID,
        Receipt.planet_id.in_(mainnet_planet_ids),
        func.timezone("UTC", Receipt.created_at) >= utc_start,
        func.timezone("UTC", Receipt.created_at) < utc_end,
        or_(
            Product.google_sku.is_(None),
            ~Product.google_sku.ilike(_SEASON_PASS_SKU_ILIKE),
        ),
    )

    # FAV 집계: ticker → FAV__{ticker}
    fav_rows = sess.execute(
        select(
            Receipt.planet_id,
            FungibleAssetProduct.ticker,
            FungibleAssetProduct.decimal_places,
            func.sum(FungibleAssetProduct.amount).label("total_amount"),
        )
        .join(Product, Receipt.product_id == Product.id)
        .join(FungibleAssetProduct, Product.id == FungibleAssetProduct.product_id)
        .where(base_filter)
        .group_by(
            Receipt.planet_id,
            FungibleAssetProduct.ticker,
            FungibleAssetProduct.decimal_places,
        )
    ).fetchall()

    # 아이템 집계: fungible_item_id를 ticker로 사용
    item_rows = sess.execute(
        select(
            Receipt.planet_id,
            FungibleItemProduct.fungible_item_id.label("ticker"),
            func.sum(FungibleItemProduct.amount).label("total_amount"),
        )
        .join(Product, Receipt.product_id == Product.id)
        .join(FungibleItemProduct, Product.id == FungibleItemProduct.product_id)
        .where(base_filter)
        .group_by(
            Receipt.planet_id,
            FungibleItemProduct.fungible_item_id,
        )
    ).fetchall()

    planets: Dict[str, list] = {name: [] for name in _MAINNET_PLANET_NAMES.values()}

    for row in fav_rows:
        planet_name = _MAINNET_PLANET_NAMES.get(bytes(row.planet_id))
        if planet_name:
            planets[planet_name].append(
                TokenSales(
                    ticker=row.ticker,
                    decimal_places=row.decimal_places,
                    total_amount=row.total_amount,
                )
            )

    for row in item_rows:
        planet_name = _MAINNET_PLANET_NAMES.get(bytes(row.planet_id))
        if planet_name:
            planets[planet_name].append(
                TokenSales(
                    ticker=row.ticker,
                    decimal_places=0,
                    total_amount=Decimal(row.total_amount),
                )
            )

    return ProductSalesResponse(
        year=year,
        month=month,
        planets={
            name: PlanetTokenSales(tokens=tokens) for name, tokens in planets.items()
        },
    )


# ── (PLD) 바우처 상품→티켓 매핑 admin (C1 정책 크로스검증 + C3-lite + C5) ──────────
#   백오피스(9c-backoffice)가 호출. C1(ticket_type ∈ 라이브 정책)/C3-lite(count×최대상금 ≤ cap)를
#   서버측에서 강제 — UI 검증은 advisory(TOCTOU). 그랜트 미스매치는 R2로 self-heal이나 여기서 예방.
#   ⚠️ per-endpoint scope 클레임은 후속(현재 router-level verify_token = 기존 admin과 동일 티어).


class VoucherGrantItem(BaseModel):
    id: int
    product_id: int
    product_name: Optional[str]
    ticket_type: str
    count: int
    active: bool
    updated_at: Optional[str]


class UpsertVoucherGrantRequest(BaseModel):
    product_id: int
    ticket_type: str
    count: int = 1
    active: bool = True
    base_updated_at: Optional[str] = None  # C5 낙관동시성(직전 조회 updated_at isoformat)


@router.get("/product-voucher-grants", response_model=List[VoucherGrantItem])
def list_product_voucher_grants(sess=Depends(session)):
    """상품→티켓 매핑 전체(상품명 조인). 백오피스 표시·C5 base_updated_at 획득용."""
    rows = (
        sess.execute(
            select(ProductVoucherGrant).options(joinedload(ProductVoucherGrant.product))
        )
        .scalars()
        .all()
    )
    return [
        VoucherGrantItem(
            id=r.id,
            product_id=r.product_id,
            product_name=r.product.name if r.product else None,
            ticket_type=r.ticket_type,
            count=r.count,
            active=r.active,
            updated_at=r.updated_at.isoformat() if r.updated_at else None,
        )
        for r in rows
    ]


@router.put("/product-voucher-grants")
def upsert_product_voucher_grant(
    request: UpsertVoucherGrantRequest, sess=Depends(session)
):
    """
    (product_id, ticket_type) upsert. active=true면 C1/C3-lite를 라이브 정책 대비 강제.
    C5: base_updated_at(직전 조회값)과 현재 행 updated_at 불일치 시 409(그새 변경).
    """
    product = sess.get(Product, request.product_id)
    if not product:
        raise HTTPException(
            status_code=404, detail=f"product {request.product_id} not found"
        )

    # active로 켜는 경우에만 정책 검증(끄는 건 발급 대상 아니라 검증 불요).
    if request.active:
        # (C6) 결제 상품(IAP)만 매핑 허용 — 네트워크 호출(C1) 전에 먼저 거른다.
        validate_product_voucher_eligible(product.id, product.product_type)
        # (리뷰) prod에서 C3-lite cap 미설정 상태로 발급 매핑을 켜는 것 금지 — 머니 가드 fail-open 방지.
        if config.voucher_grant_max_ncg_per_grant is None and config.stage in (
            "production",
            "mainnet",
        ):
            raise HTTPException(
                status_code=400,
                detail="prod에선 voucher_grant_max_ncg_per_grant(C3-lite cap) 설정 후에만 활성화 가능",
            )
        validate_voucher_mapping(
            request.ticket_type,
            request.count,
            fetch_live_prize_tables(config.portal_prize_tables_url),
            config.voucher_grant_max_ncg_per_grant,
        )

    # C5: 갱신 대상 행을 잠가(read-then-commit) 동시제출 silent revert(TOCTOU) 차단.
    #   신규 삽입 레이스는 UNIQUE(product_id, ticket_type)가 최종 가드.
    existing = sess.execute(
        select(ProductVoucherGrant)
        .where(
            ProductVoucherGrant.product_id == request.product_id,
            ProductVoucherGrant.ticket_type == request.ticket_type,
        )
        .with_for_update()
    ).scalar_one_or_none()

    if existing is not None:
        # C5 낙관동시성 — 클라가 base 제공 시 현재 updated_at과 대조(잠금 하에 판정).
        cur = existing.updated_at.isoformat() if existing.updated_at else None
        if request.base_updated_at is not None and cur != request.base_updated_at:
            raise HTTPException(status_code=409, detail="stale — reload before save")
        existing.count = request.count
        existing.active = request.active
        sess.commit()
        return {"id": existing.id, "action": "updated"}

    # 신규인데 base 제공(기존 행 기대) → 그새 삭제됨.
    if request.base_updated_at is not None:
        raise HTTPException(status_code=409, detail="mapping gone (deleted?) — reload")
    row = ProductVoucherGrant(
        product_id=request.product_id,
        ticket_type=request.ticket_type,
        count=request.count,
        active=request.active,
    )
    sess.add(row)
    sess.commit()
    return {"id": row.id, "action": "created"}


@router.delete("/product-voucher-grants/{grant_id}")
def delete_product_voucher_grant(grant_id: int, sess=Depends(session)):
    """
    매핑 하드 삭제. 발급 제외만 원하면 PUT active=false 권장.
    ⚠️ 삭제·active=false 모두 **이미 enroll된 in-flight 결제**는 dispatch 시 "no active mapping (retry)"로
       PENDING에 묶여 stall alert까지 침전할 수 있음(운영자 인지 필요 — UI/문서 경고 대상).
    """
    row = sess.get(ProductVoucherGrant, grant_id)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    sess.delete(row)
    sess.commit()
    return {"deleted": True, "id": grant_id}


# ── (PLD-1575) 포인트샵 지급 화이트리스트 admin ────────────────────────────────
#   `POST /admin/grant` 로 지급할 수 있는 상품 목록(= product.point_shop_grantable).
#   상품 등록의 정상 경로는 CSV import(`point_shop_grantable` 컬럼)지만, 시트 한 바퀴 없이
#   한 상품만 켜고/끄는 운영 수단이 필요하다 — voucher 매핑이 CSV + CRUD 를 함께 둔 것과 같다.
#   ⚠️ 이 엔드포인트도 라우터 레벨 인증 그대로다(per-endpoint scope 는 후속).


class PointShopProductItem(BaseModel):
    product_id: int
    name: str
    product_type: Optional[str]
    active: bool
    point_shop_grantable: bool
    #: (PLD-1561) 포인트 판매가(표시 포인트). None = 포인트로 팔지 않음(지급만 가능).
    #:   화이트리스트에 있으면서 값이 없는 상태는 정상이다 — 뽑기 풀에만 들어가거나
    #:   운영 수동 지급용인 상품이 그렇다.
    point_price: Optional[int]
    updated_at: Optional[str]


class UpsertPointShopGrantableRequest(BaseModel):
    product_id: int
    grantable: bool = True


@router.get("/point-shop-products", response_model=List[PointShopProductItem])
def list_point_shop_products(sess=Depends(session)):
    """
    현재 화이트리스트(= 무상 지급 가능 상품) 전체.

    **켜진 것만** 돌려준다 — 전체 상품 목록은 `GET /admin/products` 가 있고, 여기서 알고 싶은
    건 "지금 민팅 가능한 물건이 무엇인가"이기 때문이다(감사용 짧은 목록).
    """
    rows = sess.scalars(
        select(Product)
        .where(Product.point_shop_grantable.is_(True))
        .order_by(desc(Product.id))
    ).all()
    return [
        PointShopProductItem(
            product_id=row.id,
            name=row.name,
            product_type=(
                row.product_type.name if row.product_type is not None else None
            ),
            active=bool(row.active),
            point_shop_grantable=bool(row.point_shop_grantable),
            point_price=row.point_price,
            updated_at=row.updated_at.isoformat() if row.updated_at else None,
        )
        for row in rows
    ]


@router.put("/point-shop-products")
def upsert_point_shop_grantable(
    request: UpsertPointShopGrantableRequest, sess=Depends(session)
):
    """
    상품 1건의 화이트리스트 플래그 on/off.

    - `grantable=true` 는 현금 상품(IAP)·시즌패스 SKU 에 걸 수 없다(400) — 무상 발행 대상이
      아니다. 같은 검사가 CSV import 와 지급 시점에도 있다(플래그 스테일 방어).
    - FAV 구성품이 있으면 허용 티커 목록 안이어야 한다. 상태코드는 **지급 시점과 같다** —
      목록 미주입 503(`fav_tickers_unset`, 운영 실수) / 목록 밖 400(`fav_ticker_not_allowed`).
    - prod 에서 상한(`API_GRANT_MAX_*`)이 미주입이면 켜는 것 자체를 막는다 — 켜자마자
      상한 없는 발행 창이 열리는 fail-open 을 만들지 않는다(voucher C3-lite 게이트와 같은 규칙).
      ⚠️ 이 게이트는 **400** 인데 바로 위 FAV 티커 미주입은 503 이다. 둘 다 "설정 미주입"이지만
      후자는 지급 시점 함수(`check_fav_tickers`)를 그대로 재사용한 결과다 — 두 경로가 같은
      사유에 같은 코드를 주는 편이 낫다고 봤다(여기서 400 으로 바꾸면 계약 v1.2 와 갈라진다).
    - `grantable=false`(끄기)는 언제나 허용한다. 킬스위치를 게이트 뒤에 두면 안 된다.
    """
    product = sess.get(Product, request.product_id)
    if not product:
        raise HTTPException(
            status_code=404, detail=f"product {request.product_id} not found"
        )
    if request.grantable:
        validate_point_shop_grantable_eligible(
            product.id, product.product_type, product.google_sku
        )
        # FAV 티커도 **켜는 시점에** 본다. 지급 시점만 보면 운영자는 200 을 받고 켠 줄 알지만
        #   실주문이 들어오는 순간 전부 막힌다 — 그때는 이미 주문이 쌓인 뒤다.
        check_fav_tickers(product, limits_from_settings(config).allowed_fav_tickers)
        missing = limits_from_settings(config).missing()
        if missing and config.is_production:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"prod 에선 지급 상한 미주입 상태로 화이트리스트를 켤 수 없습니다: {missing}."
                    " (상품 CSV import 경로엔 이 게이트가 없다 — 그쪽으로 켜도 지급 시점에"
                    " 503 으로 막히므로 발행은 안 열리지만, 상한을 먼저 주입하는 게 정상 순서다)"
                ),
            )
    was_grantable = bool(product.point_shop_grantable)
    product.point_shop_grantable = request.grantable
    sess.commit()
    logger.info(
        "point shop whitelist updated",
        product_id=product.id,
        product_name=product.name,
        grantable=request.grantable,
    )
    if request.grantable and not was_grantable:
        # **켜는 것**은 민터 권한의 대상 목록이 넓어지는 사건이다. 엔드포인트별 스코프가 없어
        #   (admin JWT 하나로 열린다) 이 변경을 사람이 보는 채널에도 남긴다. 끄기는 알리지 않는다
        #   — 안전한 방향이고, 사고 대응 중 킬스위치가 알림을 기다릴 이유가 없다.
        send_slack_alert(
            config.iap_alert_webhook_url,
            f":unlock: [IAP grant whitelist] product {product.id} ({product.name})"
            f" 지급 허용으로 전환 ({config.stage})",
        )
    return {"product_id": product.id, "point_shop_grantable": request.grantable}


# ── (PLD-1564) 영수증 없는 범용 지급 API ─────────────────────────────────────────
#   포탈 포인트샵(무상 포인트 소모)이 온체인 아이템 지급을 요청하는 경로.
#   계약 정본은 포탈(PLD-1563)과 공유하는 "포탈 ↔ IAP 지급 계약 v1". 필드명(camelCase)·상태값·
#   HTTP 코드를 임의로 바꾸면 포탈 클라이언트가 깨진다.
#
#   왜 `receipt` 가 아니라 `grant_outbox` 인가: 영수증 상태기계·환불 폴링·매출 집계가 모두
#   "결제가 있었다"를 전제한다. 무상 지급을 섞으면 정산·CS 가 오염되므로 별도 아웃박스를 쓴다
#   (shared/models/grant_outbox.py 의 docstring 참고).
#
#   인증은 라우터 레벨 그대로다(`verify_token` + Bearer) — 별도 스코프 없음. `grant_items` 는
#   잔액 없이도 발행되는 force-grant 라, 이 토큰을 가진 주체는 사실상 민터 권한을 갖는다.
#   그래서 아웃박스가 감사 로그를 겸한다(누가/언제/무엇을 — 모델 docstring 참고).

# 멱등키. `shop:<orderId>` 를 상정하지만 네임스페이스는 고정하지 않는다(다른 무상 지급원도 쓸 수 있게).
#   문자 집합을 제한하는 이유: 로그·URL 경로·memo JSON 에 그대로 실리는 값이라 공백/제어문자를 막는다.
GRANT_EXTERNAL_REF_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9:_.\-]{0,127}$"
GRANT_ADDRESS_PATTERN = r"^0x[0-9a-fA-F]{40}$"
# memo 는 온체인 tx 에 그대로 실린다 — 무제한이면 tx 가 비대해지므로 직렬화 길이를 제한한다.
GRANT_MEMO_MAX_LEN = 512


class GrantStatusFilter(str, Enum):
    """`GET /admin/grants` 의 status 필터. 값은 `GrantStatus` 이름과 같다."""

    PENDING = "PENDING"
    GRANTED = "GRANTED"
    FAILED = "FAILED"


class GrantRequestSchema(BaseModel):
    """
    지급 요청. JSON 은 camelCase, 파이썬 내부는 snake_case (alias_generator).

    `agentAddress` 는 계약에 없는 **선택** 확장이다 — `grant_items` 는 아바타만 필요하지만,
    CS 문의가 보통 agent 주소로 들어오기 때문에 받아두면 조회가 쉬워진다. 안 보내도 무방.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    external_ref: str = Field(
        ...,
        min_length=1,
        max_length=128,
        pattern=GRANT_EXTERNAL_REF_PATTERN,
        description="멱등키. 포탈 포인트샵은 `shop:<orderId>`. 재요청은 새 tx 를 만들지 않는다",
    )
    planet_id: str = Field(..., description="기존 PlanetID 표기(`0x000000000000` 등)")
    product_id: int = Field(..., gt=0, description="IAP product.id — 구성품→티커 변환은 IAP 책임")
    avatar_address: str = Field(..., pattern=GRANT_ADDRESS_PATTERN)
    agent_address: Optional[str] = Field(None, pattern=GRANT_ADDRESS_PATTERN)
    memo: Optional[Dict[str, Any]] = Field(
        None, description='체인 memo. 미지정 시 서버가 {"shop":{"order":"<orderId>"}} 를 만든다'
    )


class GrantSchema(BaseModel):
    """아웃박스 1행의 외부 표현. 상태값은 `GrantStatus`/`TxStatus` 의 **이름**(문자열)."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    external_ref: str
    status: str
    tx_id: Optional[str] = None
    tx_status: Optional[str] = None
    attempts: int = 0
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None
    granted_at: Optional[datetime] = None
    # (PLD-1562) 뽑기 결과. 고정 상품은 null. POST 응답(201/200)과 GET 양쪽에 실린다 —
    #   포탈이 **재요청으로도 같은 결과를 다시 받을 수 있어야** 대조 배치가 결과를 메운다
    #   (첫 POST 응답이 네트워크로 유실돼도 주문이 결과 없이 남지 않는다).
    draw_result: Optional[dict] = None


class GrantListSchema(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    items: List[GrantSchema]
    next_cursor: Optional[str] = None


def _grant_schema(row: GrantOutbox) -> GrantSchema:
    return GrantSchema(
        external_ref=row.external_ref,
        status=row.status.name,
        tx_id=row.tx_id,
        tx_status=row.tx_status.name if row.tx_status is not None else None,
        attempts=row.attempts or 0,
        last_error=row.last_error,
        created_at=row.created_at,
        granted_at=row.granted_at,
        draw_result=row.gacha_result,
    )


def parse_grant_planet(planet_id: str) -> PlanetID:
    """planetId 문자열 → PlanetID. 미등록 값은 400(체인 없는 행성으로 tx 를 만들 수 없다)."""
    try:
        return PlanetID(bytes(planet_id, "utf-8"))
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown planetId: {planet_id}")


def order_id_of(external_ref: str) -> str:
    """`shop:<orderId>` → `<orderId>`. 네임스페이스가 없으면 ref 전체를 주문키로 본다."""
    _, _, order_id = external_ref.partition(":")
    return order_id or external_ref


def build_grant_memo(external_ref: str, memo: Optional[Dict[str, Any]]) -> str:
    """
    체인에 실을 memo(JSON 문자열).

    불변식: **memo 만 보고 externalRef 를 복원할 수 있어야 한다.** `shop:<orderId>` 는
    `{"shop": {"order": "<orderId>"}}` 와 같은 정보다. 호출자가 memo 를 줘도 이 표식은 보장한다
    (없으면 채워 넣는다) — 안 그러면 체인에서 주문을 역추적할 수 없다.
    """
    canonical = {"order": order_id_of(external_ref)}
    merged: Dict[str, Any] = dict(memo) if memo else {}
    shop = merged.get("shop")
    if isinstance(shop, dict):
        # canonical 이 **뒤**여야 한다 — 호출자가 shop.order 를 다른 값으로 보내도 externalRef 의
        #   주문키가 이긴다. 순서를 뒤집으면 "memo 만 보고 externalRef 복원" 불변식이 깨진다.
        merged["shop"] = {**shop, **canonical}
    else:
        merged["shop"] = canonical
    serialized = json.dumps(merged, ensure_ascii=False)
    if len(serialized) > GRANT_MEMO_MAX_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"memo too long: {len(serialized)} > {GRANT_MEMO_MAX_LEN}",
        )
    return serialized


def warn_grant_pressure(warning: GrantWarning) -> None:
    """
    (PLD-1575) 거절하지 않는 가드 경고 — 시간창 상한 **임박** · 의미적 **중복 의심**.

    위반 알림만 있으면 첫 초과 주문이 이미 400(포탈 기준 영구 실패)이다. 상한을 올릴 시간을
    벌어주는 게 임박 경고의 목적이다(사유가 `*_warn`).

    스로틀 **키는 가드가 만들어 준다**(`GrantWarning.throttle_key`) — 축마다 접는 단위가
    다르기 때문이다(임박 경고는 아바타를 접고, 중복 경고는 사건이 (아바타, 상품) 단위라
    접지 않는다 — `GrantScope.key` / `coarse_key`). 저장소도 위반 알림과 **분리돼 있다**
    (`should_warn`): 카디널리티가 큰 경고 키가 위반 알림의 스로틀을 지우면 거절 알림 도배가
    다시 열린다.

    호출 시점은 **commit·큐 발행 뒤**다(잠금 밖). 이건 정상 응답 경로라 알림이 실패해도 지급을
    깨서는 안 되고, `send_slack_alert` 가 예외를 올리지 않는 것에 의존한다. 큐 발행보다도 뒤인
    이유: webhook 은 동기 호출(타임아웃 3초)이라 앞에 두면 Slack 지연이 워커 착수를 늦춘다.
    """
    logger.warning("grant guard warning", reason=warning.reason, detail=warning.message)
    if not should_warn(warning.throttle_key):
        return
    send_slack_alert(
        config.iap_alert_webhook_url,
        f":warning: [IAP grant guard] {warning.reason} ({config.stage})\n"
        f"{warning.message}",
    )


def report_grant_violation(
    violation: GrantGuardViolation, request: GrantRequestSchema
) -> None:
    """
    (PLD-1575) 가드 위반 감사 로그 + Slack 알림.

    로그는 **항상** 남기고(who/what/when 감사 근거) Slack 만 사유별로 스로틀한다 —
    도배 방지가 목적이지 은폐가 아니다. 알림 실패는 무시한다(거절 판정은 이미 정해졌다).

    ⚠️ 호출부는 이 함수 **전에 rollback** 해야 한다. 시간창 위반은 advisory lock 을 잡은 채로
    던져지므로, 여기서 webhook POST(수 초 타임아웃)를 하는 동안 잠금을 들고 있으면 하필
    호출자가 몰아치는 순간에 모든 지급 요청이 그 뒤에 줄을 선다.
    """
    namespace = namespace_of(request.external_ref)
    logger.warning(
        "grant rejected by guard",
        reason=violation.reason,
        status_code=violation.status_code,
        detail=violation.detail,
        namespace=namespace,
        external_ref=request.external_ref,
        product_id=request.product_id,
        avatar_addr=request.avatar_address,
        planet_id=request.planet_id,
    )
    allowed = limits_from_settings(config).allowed_namespaces
    if not should_alert(alert_key(violation.reason, namespace, allowed)):
        return
    send_slack_alert(
        config.iap_alert_webhook_url,
        f":no_entry: [IAP grant guard] {violation.reason} ({config.stage})\n"
        f"externalRef=`{request.external_ref}` productId={request.product_id}"
        f" avatar=`{request.avatar_address}`\n{violation.detail}",
    )


@router.post("/grant", response_model=GrantSchema, status_code=201)
def create_grant(
    request: GrantRequestSchema, response: Response, sess=Depends(session)
):
    """
    # 영수증 없는 지급 요청 (멱등)
    ---
    포탈 포인트샵 주문 1건을 온체인 `grant_items` 대기열(아웃박스)에 넣는다.

    - **201**: 새 아웃박스 행 생성 + 워커 큐 발행
    - **200**: 같은 `externalRef` 재요청 — **새 tx 를 만들지 않고** 기존 행을 그대로 반환
      (그래서 409 를 쓰지 않는다. 포탈은 재시도해도 안전하다)
    - **400**: 검증 실패(형식·미존재 productId·구성품 없는 상품·긴 memo) 또는
      **머니 가드 위반**(화이트리스트 밖 상품·발행량/빈도 상한 초과·**아바타 축 상한 초과**·
      미등록 네임스페이스). 가드 위반은 **행을 만들지 않는다** — 아웃박스에 FAILED 를 남기면
      포탈이 환급을 트리거하는데, 지급이 시작되지도 않았기 때문이다(계약 v1.1).
    - **503**: prod 인데 머니 가드 임계가 미주입(운영 실수 — 포탈은 재시도하면 된다)
    - **401/403**: 인증(라우터 레벨)

    `status` 는 이 시점에 항상 `PENDING` 이다 — 실제 온체인 확정은 워커가 추적하며,
    포탈은 `GET /admin/grant/{externalRef}` 로 `GRANTED` 를 기다린다.

    같은 `(아바타, 상품)` 이 짧은 창 안에 반복되면 **201 로 통과시키고 Slack 경고만** 남긴다
    (`duplicate_grant_warn`) — 포탈이 같은 구매에 새 `externalRef` 를 붙여 재요청했을
    가능성이지만 정상 반복 구매와 구분되지 않아 거절하지 않는다(grant_guard.py 참고).
    """
    planet = parse_grant_planet(request.planet_id)

    existing = sess.scalar(
        select(GrantOutbox).where(GrantOutbox.external_ref == request.external_ref)
    )
    if existing is not None:
        # 멱등 — 요청 본문이 달라도 **기존 행이 진실**이다(이미 tx 가 나갔을 수 있다).
        response.status_code = 200
        return _grant_schema(existing)

    # 상품과 구성품 검증. active 여부는 보지 않는다 — 판매 가능성의 권위는 포탈이고,
    #   비활성 상품이라도 이미 성립한 주문은 지급돼야 한다.
    product = sess.scalar(
        select(Product)
        .options(selectinload(Product.fav_list))
        .options(selectinload(Product.fungible_item_list))
        .options(selectinload(Product.gacha_entry_list))
        .where(Product.id == request.product_id)
    )
    if product is None:
        raise HTTPException(
            status_code=400, detail=f"product {request.product_id} not found"
        )
    has_fixed = bool(product.fav_list or product.fungible_item_list)
    if has_fixed and product.is_gacha:
        # (PLD-1562) 고정 구성품 + 풀을 동시에 가진 상품은 "둘 다 주나 하나만 주나"가
        #   정의되지 않는다. 지급은 되돌릴 수 없으므로 애매한 상태를 지급 시점에 끊는다.
        raise HTTPException(
            status_code=400,
            detail=(
                f"product {request.product_id} has both fixed components and a gacha"
                " pool — a product must be one or the other"
            ),
        )
    if not (has_fixed or product.is_gacha):
        # 구성품이 없으면 "성공했는데 아무것도 안 준" tx 가 된다 — 요청 단계에서 끊는다.
        raise HTTPException(
            status_code=400,
            detail=f"product {request.product_id} has no grantable components",
        )

    # memo 길이 검증(400)은 가드 **앞**에서 끝낸다 — 가드가 advisory lock 을 잡은 뒤에 형식
    #   오류로 빠지면 잠금을 요청 종료까지 들고 있게 된다. 형식 검증은 형식 검증끼리 모은다.
    memo = build_grant_memo(request.external_ref, request.memo)

    # (PLD-1575) 머니 가드 — 화이트리스트·발행량·빈도·네임스페이스. **INSERT 전에** 끝난다
    #   (위반 시 행이 없어야 포탈이 환급을 오판하지 않는다). 멱등 재요청은 위(200)에서 이미
    #   빠져나갔으므로, 상한을 나중에 낮춰도 진행 중인 주문의 폴링이 깨지지 않는다.
    #   시간창 카운트는 아래 commit 과 **같은 트랜잭션**이어야 유효하다(advisory lock 구간).
    #   임박 경고는 **모아 두고 commit 뒤에** 보낸다 — 가드는 잠금을 잡은 상태로 콜백을
    #   부르므로 거기서 webhook 을 때리면 위반 알림과 같은 문제(잠금 뒤 줄서기)가 생긴다.
    #   아래 INSERT 와 아바타 축 카운트가 **같은 문자열**을 봐야 한다(가드도 안에서 같은
    #   `format_addr` 로 정규화한다 — 멱등이므로 여기서 미리 맞춰 두는 게 안전하다).
    avatar_addr = format_addr(request.avatar_address)

    # (PLD-1562) 추첨 — **가드보다 먼저, INSERT 와 같은 트랜잭션에서** 한 번.
    #   · 가드보다 먼저인 이유: 수량 상한을 뽑힌 칸으로 재야 한다(뽑기 상품 자체는 구성품이
    #     없어 발행량 0 으로 계산되므로, 순서가 반대면 뽑기가 상한을 통째로 우회한다).
    #   · 여기서 뽑아도 **재추첨이 안 되는 이유**는 위 멱등 분기다. 같은 external_ref 재요청은
    #     이 지점에 도달하지 않고 기존 행을 200 으로 돌려준다. 동시 요청으로 둘 다 여기까지
    #     와도 INSERT 의 UNIQUE(external_ref) 가 하나만 남기고, 진 쪽은 이긴 행을 반환한다
    #     (아래 IntegrityError 분기) — 즉 **행이 곧 추첨이고 행은 하나뿐**이다.
    #   · 가드가 거절하면 행이 없으므로 이 추첨은 없던 일이다. 포탈이 환급하고, 재시도는
    #     새로 뽑는다. 아무것도 지급되지 않았으므로 그게 맞다.
    gacha_entry = None
    gacha_result = None
    gacha_claim = None
    limits = limits_from_settings(config)

    pressure: List[GrantWarning] = []
    try:
        # ① 추첨과 무관한 가드 먼저(네임스페이스·화이트리스트·레이트리밋).
        #    ⚠️ 이 순서가 **조용한 재추첨**을 막는다 — 추첨 뒤에 일시적 거절(레이트리밋)이
        #       있으면, 행이 안 생긴 채 포탈이 재시도하면서 매번 다시 뽑힌다. 그러면 공시
        #       확률이 차단 칸을 빼고 조용히 재정규화된다(grant_guard.enforce_claim_guards).
        namespace = enforce_grant_guards(
            sess,
            external_ref=request.external_ref,
            product=product,
            avatar_addr=avatar_addr,
            limits=limits,
            is_production=config.is_production,
            on_warning=pressure.append,
        )

        # ② 추첨 — 아래 INSERT 와 **같은 트랜잭션**이다. 재추첨이 안 되는 근거는 위 멱등
        #    분기와 INSERT 의 UNIQUE(external_ref) 다(행이 곧 추첨이고 행은 하나뿐).
        if product.is_gacha:
            try:
                # 상품이 정한 횟수만큼 **독립** 추첨(10연 = 복원추출 10회).
                picks = draw_entries(
                    product.gacha_entry_list, int(product.gacha_draw_count or 1)
                )
                # FK 는 조회 편의용이라 **단연일 때만** 채운다 — 10연의 "어느 한 칸"을
                #   대표로 박으면 나머지 9회가 조인에서 사라져 집계가 거짓말을 한다.
                #   회차별 원본은 gacha_result["draws"] 가 전부 들고 있다.
                gacha_entry = picks[0] if len(picks) == 1 else None
                gacha_result = build_gacha_result(product.gacha_entry_list, picks)
                # 동결본을 **여기서 바로 되읽는다**. 아래 가드가 재는 값과 워커가 체인에
                #   싣는 값이 같은 바이트여야 하고, 형식 검증도 이 시점에 끝나야 한다 —
                #   워커까지 미루면 "포인트 쓰고 결과까지 본 뒤 FAILED→환급" 이 된다.
                gacha_claim = claim_from_result(gacha_result)
            except GachaPoolError as e:
                # 풀 설정 오류(빈 풀·잘못된 가중치·형식). 재시도해도 같으므로 400 이다.
                raise GrantGuardViolation(
                    400,
                    "gacha_pool_unusable",
                    f"product {request.product_id} gacha pool is unusable: {e}",
                )

        # ③ 지급 내용 가드 — **뽑힌 칸**의 티커·수량을 잰다(뽑기 상품은 구성품이 비어 있어
        #    이걸 안 하면 얼로우리스트와 수량 상한을 통째로 우회한다).
        enforce_claim_guards(product, limits=limits, gacha_claim=gacha_claim)
    except GrantGuardViolation as violation:
        # 먼저 트랜잭션을 놓는다(= advisory lock 해제). 아직 아무것도 쓰지 않았으므로 rollback 은
        #   무손실이고, 알림 webhook 이 느려도 다른 지급 요청을 막지 않는다.
        sess.rollback()
        report_grant_violation(violation, request)
        raise

    row = GrantOutbox(
        external_ref=request.external_ref,
        product_id=product.id,
        planet_id=planet.value,
        avatar_addr=avatar_addr,
        agent_addr=(
            format_addr(request.agent_address) if request.agent_address else None
        ),
        memo=memo,
        status=GrantStatus.PENDING,
        gacha_entry_id=(gacha_entry.id if gacha_entry is not None else None),
        gacha_result=gacha_result,
    )
    sess.add(row)
    try:
        sess.commit()
    except IntegrityError:
        # UNIQUE(external_ref) — 동시 요청이 먼저 넣었다. 멱등 규약대로 기존 행을 200 으로.
        sess.rollback()
        existing = sess.scalar(
            select(GrantOutbox).where(GrantOutbox.external_ref == request.external_ref)
        )
        if existing is None:
            raise
        response.status_code = 200
        return _grant_schema(existing)
    sess.refresh(row)

    # 감사 로그(who/what/when). who = 등록된 external_ref 네임스페이스(admin JWT 에 subject
    #   클레임이 없어 이게 유일한 출처 식별자다 — PLD-1575 근거는 grant_guard.py 참고).
    logger.info(
        "grant requested",
        namespace=namespace,
        external_ref=row.external_ref,
        product_id=row.product_id,
        avatar_addr=row.avatar_addr,
        planet_id=request.planet_id,
    )
    try:
        send_to_worker(
            "iap.send_grant",
            SendGrantMessage(external_ref=row.external_ref).model_dump(),
            # 결제 지급 큐(product_queue)에 무상 지급을 섞지 않는다 — 이벤트로 몰릴 때
            #   유상 결제 지급이 뒤로 밀리면 안 된다.
            queue="background_job_queue",
        )
    except Exception as e:  # noqa: BLE001
        # 큐 발행 실패로 요청을 깨지 않는다 — 행은 이미 커밋됐고 beat(`iap.grant_track`)가
        #   미완료 PENDING 을 다시 집는다. 여기서 500 을 내면 포탈이 재요청하는데, 그건 200(멱등)이
        #   돌아올 뿐이라 상황이 나아지지 않는다.
        logger.warning(
            "grant queue publish failed (beat will retry)",
            external_ref=row.external_ref,
            error=str(e),
        )
    # 경고 알림은 **큐 발행 뒤**에 보낸다 — webhook 은 동기 호출(타임아웃 3초)이라 앞에 두면
    #   Slack 지연이 워커 착수까지 늦춘다. 이 시점엔 행도 커밋됐고 잠금도 없다.
    for warning in pressure:
        warn_grant_pressure(warning)
    return _grant_schema(row)


@router.get("/grant/{external_ref:path}", response_model=GrantSchema)
def get_grant(external_ref: str, sess=Depends(session)):
    """
    # 지급 상태 조회
    ---
    포탈이 폴링하는 엔드포인트. 없으면 404.
    """
    row = sess.scalar(
        select(GrantOutbox).where(GrantOutbox.external_ref == external_ref)
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"grant {external_ref} not found")
    return _grant_schema(row)


@router.get("/grants", response_model=GrantListSchema)
def list_grants(
    status: Annotated[
        Optional[GrantStatusFilter], Query(description="상태 필터. 미지정 시 전체")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[
        Optional[str], Query(description="이전 응답의 nextCursor(불투명 값)")
    ] = None,
    sess=Depends(session),
):
    """
    # 지급 목록 (백오피스 실패 큐)
    ---
    최신순 keyset 페이지네이션. `nextCursor` 가 null 이면 마지막 페이지.
    """
    stmt = select(GrantOutbox)
    if status is not None:
        stmt = stmt.where(GrantOutbox.status == GrantStatus[status.value])
    if cursor:
        if not cursor.isdigit():
            raise HTTPException(status_code=400, detail=f"Invalid cursor: {cursor}")
        stmt = stmt.where(GrantOutbox.id < int(cursor))
    rows = sess.scalars(stmt.order_by(desc(GrantOutbox.id)).limit(limit)).all()
    return GrantListSchema(
        items=[_grant_schema(row) for row in rows],
        # 마지막 페이지 판별은 "요청한 만큼 다 찼는가" — 딱 맞아떨어지면 빈 다음 페이지가 한 번 나온다.
        next_cursor=str(rows[-1].id) if len(rows) == limit else None,
    )
