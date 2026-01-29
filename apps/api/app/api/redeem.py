import logging
from datetime import datetime, timezone
from uuid import uuid4

import requests
from fastapi import APIRouter, Depends, HTTPException
from shared.enums import PackageName, PlanetID, ReceiptStatus, Store
from shared.models.product import Product
from shared.models.receipt import Receipt
from shared.schemas.message import SendProductMessage
from shared.schemas.redeem import (
    RedeemErrorResponseSchema,
    RedeemRequestSchema,
    RedeemResponseSchema,
)
from sqlalchemy import or_, select
from sqlalchemy.orm import joinedload

from app.celery import send_to_worker
from app.config import config
from app.dependencies import session
from app.utils import generate_redeem_jwt

router = APIRouter(
    prefix="/redeem-codes",
    tags=["Redeem"],
)

logger = logging.getLogger(__name__)


@router.post("/redeem", response_model=RedeemResponseSchema)
def redeem_code(
    request: RedeemRequestSchema,
    sess=Depends(session),
):
    """
    Redeem Code 사용 처리

    외부 API를 호출하여 Redeem Code를 사용 처리하고, 성공 시 Receipt를 생성하여 grant_items transaction을 생성합니다.
    """
    try:
        # 서비스 ID 검증: 9C만 허용
        if request.service_id.upper() != "9C":
            logger.error(f"Service ID not allowed: {request.service_id}. Only '9C' is allowed.")
            raise HTTPException(
                status_code=403,
                detail=f"Service ID '{request.service_id}' is not allowed. Only '9C' service is allowed for redeem."
            )

        # serviceId 기반으로 JWT 토큰 생성
        try:
            redeem_token = generate_redeem_jwt(request.service_id)
        except ValueError as e:
            logger.error(f"Invalid service_id: {request.service_id}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid service_id: {request.service_id}"
            )

        # 외부 API URL 구성
        api_url = f"{config.redeem_api_base_url}/redeem-codes/redeem"

        # 요청 헤더에 생성한 JWT 토큰 포함
        headers = {
            "Authorization": f"Bearer {redeem_token}",
            "Content-Type": "application/json",
        }

        # 요청 본문 구성
        payload = {
            "code": request.code,
            "target_user_id": request.target_user_id,
        }

        # 외부 API 호출
        response = requests.post(api_url, json=payload, headers=headers, timeout=30)

        # 응답 처리
        if response.status_code == 201:
            # 성공 응답
            response_data = response.json()
            redeem_response = RedeemResponseSchema(**response_data)

            # product_code로 Product 조회 (google_sku, apple_sku, apple_sku_k 중 하나와 매칭)
            product = sess.scalar(
                select(Product)
                .options(joinedload(Product.fav_list))
                .options(joinedload(Product.fungible_item_list))
                .where(
                    Product.active.is_(True),
                    or_(
                        Product.google_sku == redeem_response.product_code,
                        Product.apple_sku == redeem_response.product_code,
                        Product.apple_sku_k == redeem_response.product_code,
                    ),
                )
            )

            if not product:
                logger.error(f"Product not found for product_code: {redeem_response.product_code}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Product not found for product_code: {redeem_response.product_code}"
                )

            # Package name 처리
            package_name = request.package_name
            if not package_name:
                # 기본값 설정
                package_name = (
                    PackageName.NINE_CHRONICLES_M.value
                    if config.stage == "mainnet"
                    else PackageName.NINE_CHRONICLES_M.value
                )

            # Planet ID 처리
            planet_id = PlanetID(bytes(request.planet_id, "utf-8"))

            # Receipt 생성
            order_id = f"REDEEM-{request.code}-{uuid4()}"
            receipt = Receipt(
                store=Store.REDEEM,
                package_name=package_name,
                data={
                    "code": request.code,
                    "product_code": redeem_response.product_code,
                    "target_user_id": request.target_user_id,
                },
                agent_addr=request.agent_address.lower(),
                avatar_addr=request.avatar_address.lower(),
                order_id=order_id,
                purchased_at=datetime.now(timezone.utc),
                product_id=product.id,
                planet_id=planet_id.value,
                status=ReceiptStatus.VALID,
            )

            sess.add(receipt)
            sess.commit()
            sess.refresh(receipt)

            # Celery worker로 전송하여 grant_items transaction 생성
            send_product_message = SendProductMessage(uuid=str(receipt.uuid))
            task_id = send_to_worker("iap.send_product", send_product_message.model_dump())
            logger.debug(
                f"Task for redeem code {receipt.uuid} sent to Celery worker with task_id: {task_id}"
            )

            return redeem_response
        elif response.status_code == 401:
            # JWT 인증 실패
            raise HTTPException(
                status_code=401,
                detail="JWT authentication failed"
            )
        elif response.status_code == 403:
            # 잘못된 프로젝트
            error_data = response.json()
            error_schema = RedeemErrorResponseSchema(**error_data)
            raise HTTPException(
                status_code=403,
                detail=error_schema.message
            )
        elif response.status_code == 404:
            # 존재하지 않는 코드
            error_data = response.json()
            error_schema = RedeemErrorResponseSchema(**error_data)
            raise HTTPException(
                status_code=404,
                detail=error_schema.message
            )
        elif response.status_code == 409:
            # 이미 사용된 코드
            error_data = response.json()
            error_schema = RedeemErrorResponseSchema(**error_data)
            raise HTTPException(
                status_code=409,
                detail=error_schema.message
            )
        else:
            # 기타 에러
            logger.error(
                f"Unexpected status code from redeem API: {response.status_code}, "
                f"response: {response.text}"
            )
            raise HTTPException(
                status_code=500,
                detail="Internal server error while processing redeem code"
            )

    except requests.exceptions.RequestException as e:
        logger.error(f"Network error while calling redeem API: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Network error while processing redeem code"
        )
    except HTTPException:
        # HTTPException은 그대로 재발생
        raise
    except Exception as e:
        logger.error(f"Unexpected error while processing redeem code: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error while processing redeem code"
        )
