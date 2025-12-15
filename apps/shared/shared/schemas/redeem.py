from datetime import datetime
from typing import Optional

from pydantic import BaseModel as BaseSchema


class RedeemRequestSchema(BaseSchema):
    """Redeem Code 사용 요청 스키마"""
    code: str
    target_user_id: str
    service_id: str
    agent_address: str
    avatar_address: str
    planet_id: str
    package_name: Optional[str] = None


class RedeemResponseSchema(BaseSchema):
    """Redeem Code 사용 성공 응답 스키마"""
    success: bool
    code: str
    product_code: str
    issued_by: str
    buyer_user_id: str
    used: bool
    used_by_user_id: str
    used_at: datetime
    metadata: dict


class RedeemErrorResponseSchema(BaseSchema):
    """Redeem Code 사용 에러 응답 스키마"""
    success: bool
    error_code: str
    message: str
