from datetime import datetime, timedelta
from typing import Optional, List, Annotated

from fastapi import APIRouter, Depends, Query, Security, HTTPException
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from sqlalchemy import func, select, Date, desc
from sqlalchemy.orm import joinedload

from common.enums import Store, ReceiptStatus
from common.models.product import Product
from common.models.receipt import Receipt
from common.utils.google import update_google_price
from iap import settings
from iap.dependencies import session
from iap.schemas.product import ProductSchema
from iap.schemas.receipt import RefundedReceiptSchema, FullReceiptSchema
from iap.utils import verify_token
from scripts.products import import_products_from_csv
from scripts.category_product import import_category_products_from_csv

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
