from datetime import datetime, timedelta
from typing import Optional, List, Annotated
from enum import Enum

from fastapi import APIRouter, Depends, Query, Security, HTTPException, File, UploadFile
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from sqlalchemy import func, select, Date, desc, and_
from sqlalchemy.orm import joinedload

from common.enums import ReceiptStatus, Store
from common.models.product import Product
from common.models.receipt import Receipt
from common.utils.apple import get_tx_ids
from common.utils.import_utils import import_category_products_from_csv, import_fungible_assets_from_csv, import_fungible_items_from_csv, import_products_from_csv, import_prices_from_csv
from common.utils.r2 import CDN_URLS, R2_IMAGE_DETAIL_FOLDER, R2_IMAGE_LIST_FOLDER, R2_PRODUCT_KEYS, purge_cache, upload_csv_to_r2, upload_image_to_r2
from common.utils.s3 import upload_image_to_s3, upload_to_s3, invalidate_cloudfront
from iap import settings
from iap.dependencies import session
from iap.schemas.product import ProductSchema
from iap.schemas.receipt import RefundedReceiptSchema, FullReceiptSchema
from iap.utils import verify_token
import tempfile
import os

security = HTTPBearer()

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(verify_token), Security(security)],  # 모든 admin 엔드포인트에 인증 필요
)

class PaginatedProductResponse(BaseModel):
    total: int
    items: List[ProductSchema]

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

class UploadCsvToR2Request(BaseModel):
    csv_content: str

class SortOrder(str, Enum):
    ASC = "asc"
    DESC = "desc"

class ReceiptSearchResponse(BaseModel):
    total: int
    items: List[FullReceiptSchema]

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
            Optional[int], Query(description="Where to start to find refunded receipt in unix timestamp format. "
                                             "If not provided, search starts from 24 hours ago.")
        ] = None,
        limit: Annotated[int, Query(description="Limitation of receipt in response.")] = 100,
        sess=Depends(session)):
    """
    # List refunded receipts
    ---

    Get list of refunded receipts. This only returns user-refunded receipts.
    """
    if not start:
        start = (datetime.utcnow() - timedelta(hours=24)).date()
    else:
        start = datetime.fromtimestamp(start)

    return sess.scalars(
        select(Receipt).where(Receipt.status == ReceiptStatus.REFUNDED_BY_BUYER)
        .where(Receipt.updated_at.cast(Date) >= start)
        .order_by(desc(Receipt.updated_at)).limit(limit)
    ).fetchall()


@router.get("/receipt", response_model=List[FullReceiptSchema])
def receipt_list(page: int = 0, pp: int = 50, sess=Depends(session)):
    return sess.scalars(
        select(Receipt).options(joinedload(Receipt.product))
        .order_by(desc(Receipt.purchased_at))
        .offset(pp * page).limit(pp)
    ).fetchall()


@router.get("/products", response_model=PaginatedProductResponse)
def product_list(
    limit: int = Query(default=20, ge=1, le=100),  # 한 페이지당 기본 20개, 최대 100개
    offset: int = Query(default=0, ge=0),  # 시작 위치
    sess=Depends(session)
):
    """상품 정보를 조회합니다.

    Args:
        limit: 한 페이지당 반환할 항목 수 (기본값: 20, 최대: 100)
        offset: 시작 위치 (기본값: 0)
    """
    # 기본 쿼리 생성
    base_query = select(Product).order_by(desc(Product.created_at))

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
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as temp_file:
            temp_file.write(request.csv_content)
            temp_path = temp_file.name

        try:
            # 비대화형 모드로 임포트 실행
            processed_count, updated_count = import_products_from_csv(
                sess,
                temp_path,
                request.environment,
                interactive=False
            )

            return {
                "message": "상품 데이터가 성공적으로 임포트되었습니다.",
                "processed_count": processed_count,
                "updated_count": updated_count
            }
        finally:
            # 임시 파일 삭제
            os.unlink(temp_path)

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/products/categories/import")
def import_category_products_endpoint(request: ImportCategoryProductsRequest, sess=Depends(session)):
    """
    CSV 데이터에서 카테고리-상품 관계 정보를 가져와 데이터베이스에 임포트합니다.

    Args:
        csv_content: CSV 파일 내용 (문자열)
    """
    try:
        # 임시 CSV 파일 생성
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as temp_file:
            temp_file.write(request.csv_content)
            temp_path = temp_file.name

        try:
            # 임포트 실행
            processed_count, added_count = import_category_products_from_csv(
                sess,
                temp_path
            )

            return {
                "message": "카테고리-상품 관계 데이터가 성공적으로 임포트되었습니다.",
                "processed_count": processed_count,
                "added_count": added_count
            }
        finally:
            # 임시 파일 삭제
            os.unlink(temp_path)

    except Exception as e:
        print(e)
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/products/fungible-assets/import")
def import_fungible_assets_endpoint(request: ImportFungibleAssetsRequest, sess=Depends(session)):
    """
    CSV 데이터에서 대체 가능 자산 정보를 가져와 데이터베이스에 임포트합니다.

    Args:
        csv_content: CSV 파일 내용 (문자열)
    """
    try:
        # 임시 CSV 파일 생성
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as temp_file:
            temp_file.write(request.csv_content)
            temp_path = temp_file.name

        try:
            # 임포트 실행
            processed_count, changed_count = import_fungible_assets_from_csv(
                sess,
                temp_path
            )

            return {
                "message": "대체 가능 자산 데이터가 성공적으로 임포트되었습니다.",
                "processed_count": processed_count,
                "changed_count": changed_count
            }
        finally:
            # 임시 파일 삭제
            os.unlink(temp_path)

    except Exception as e:
        print(e)
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/products/fungible-items/import")
def import_fungible_items_endpoint(request: ImportFungibleItemsRequest, sess=Depends(session)):
    """
    CSV 데이터에서 대체 가능 아이템 정보를 가져와 데이터베이스에 임포트합니다.

    Args:
        csv_content: CSV 파일 내용 (문자열)
    """
    try:
        # 임시 CSV 파일 생성
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as temp_file:
            temp_file.write(request.csv_content)
            temp_path = temp_file.name

        try:
            # 임포트 실행
            processed_count, changed_count = import_fungible_items_from_csv(
                sess,
                temp_path
            )

            return {
                "message": "대체 가능 아이템 데이터가 성공적으로 임포트되었습니다.",
                "processed_count": processed_count,
                "changed_count": changed_count
            }
        finally:
            # 임시 파일 삭제
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
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as temp_file:
            temp_file.write(request.csv_content)
            temp_path = temp_file.name

        try:
            # 비대화형 모드로 임포트 실행
            processed_count, updated_count = import_prices_from_csv(
                sess,
                temp_path
            )

            return {
                "message": "가격 데이터가 성공적으로 임포트되었습니다.",
                "processed_count": processed_count,
                "updated_count": updated_count
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
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as temp_file:
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
            return {
                "message": message
            }
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
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.csv') as temp_file:
            temp_file.write(request.csv_content)
            temp_path = temp_file.name

        try:
            # S3에 업로드
            success = upload_to_s3(temp_path)
            if not success:
                raise HTTPException(status_code=400, detail="S3 업로드 실패")

            # CloudFront 캐시 초기화
            invalidate_cloudfront()

            return {
                "message": "CSV 파일이 성공적으로 업로드되었고 캐시 초기화가 요청되었습니다."
            }
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
            if not file.filename or not file.filename.lower().endswith('.png'):
                results.append({
                    "filename": file.filename or "unknown",
                    "status": "failed",
                    "error": "PNG 파일만 업로드 가능합니다."
                })
                continue

            # 파일 크기 검증 (10MB 제한)
            MAX_SIZE = 10 * 1024 * 1024  # 10MB
            content = await file.read()
            if len(content) > MAX_SIZE:
                results.append({
                    "filename": file.filename,
                    "status": "failed",
                    "error": "파일이 너무 큽니다 (최대 10MB)"
                })
                continue

            try:
                # 이미지를 임시 파일로 저장
                with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as temp_file:
                    temp_file.write(content)
                    temp_path = temp_file.name

                try:
                    # R2에 업로드
                    is_list_image = file.filename.endswith("_s.png")
                    file_name = file.filename.replace("_s.png", ".png") if is_list_image else file.filename
                    if is_list_image:
                        for folder in R2_IMAGE_LIST_FOLDER:
                            r2_key = f"{folder}{file_name}"
                            upload_image_to_r2(temp_path, r2_key)
                            results.append({
                                "filename": file.filename,
                                "status": "success"
                            })
                            r2_keys.append(r2_key)
                    else:
                        for folder in R2_IMAGE_DETAIL_FOLDER:
                            r2_key = f"{folder}{file_name}"
                            upload_image_to_r2(temp_path, r2_key)
                            results.append({
                                "filename": file.filename,
                                "status": "success"
                            })
                            r2_keys.append(r2_key)
                finally:
                    # 임시 파일 삭제
                    os.unlink(temp_path)

            except Exception as e:
                results.append({
                    "filename": file.filename,
                    "status": "failed",
                    "error": str(e)
                })

        # 캐시 무효화
        for zone_id, cdn_url in CDN_URLS.items():
            for r2_key in r2_keys:
                purge_cache(zone_id, cdn_url, r2_key)

        success_count = sum(1 for r in results if r["status"] == "success")
        failed_count = len(results) - success_count

        return {
            "message": f"{success_count}개의 이미지가 업로드되었습니다. {failed_count}개 실패.",
            "results": results
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
            if not file.filename or not file.filename.lower().endswith('.png'):
                results.append({
                    "filename": file.filename or "unknown",
                    "status": "failed",
                    "error": "PNG 파일만 업로드 가능합니다."
                })
                continue

            # 파일 크기 검증 (10MB 제한)
            MAX_SIZE = 10 * 1024 * 1024  # 10MB
            content = await file.read()
            if len(content) > MAX_SIZE:
                results.append({
                    "filename": file.filename,
                    "status": "failed",
                    "error": "파일이 너무 큽니다 (최대 10MB)"
                })
                continue

            try:
                # 이미지를 임시 파일로 저장
                with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as temp_file:
                    temp_file.write(content)
                    temp_path = temp_file.name

                try:
                    # S3에 업로드
                    upload_image_to_s3(temp_path, file.filename)
                    results.append({
                        "filename": file.filename,
                        "status": "success"
                    })
                finally:
                    # 임시 파일 삭제
                    os.unlink(temp_path)

            except Exception as e:
                results.append({
                    "filename": file.filename,
                    "status": "failed",
                    "error": str(e)
                })

        # CloudFront 캐시 초기화
        invalidate_cloudfront()

        success_count = sum(1 for r in results if r["status"] == "success")
        failed_count = len(results) - success_count
        return {
            "message": f"{success_count}개의 이미지가 업로드되었습니다. {failed_count}개 실패.",
            "results": results
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
    sess=Depends(session)
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
        tx_ids = get_tx_ids(apple_order_id, settings.APPLE_CREDENTIAL, settings.APPLE_BUNDLE_ID, settings.APPLE_KEY_ID, settings.APPLE_ISSUER_ID)
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

    return ReceiptSearchResponse(
        total=total_count,
        items=receipts
    )
