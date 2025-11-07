import uuid
import re
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import UUID, Column, DateTime, ForeignKey, Integer, LargeBinary, Text, and_, extract, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import backref, relationship, joinedload

from shared.enums import PlanetID, ReceiptStatus, Store, TxStatus
from shared.models.base import AutoIdMixin, Base, TimeStampMixin
from shared.models.product import Product


class Receipt(AutoIdMixin, TimeStampMixin, Base):
    __tablename__ = "receipt"
    store = Column(
        ENUM(Store, create_type=False),
        nullable=False,
        index=True,
        doc="Purchased Store Type",
    )
    order_id = Column(Text, nullable=False, doc="Play store / Appstore IAP receipt id")
    uuid = Column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
        default=uuid.uuid4,
        doc="Internal uuid for management",
    )
    package_name = Column(
        Text, nullable=False, doc="Package name where the receipt came from"
    )
    data = Column(JSONB, nullable=False, doc="Full IAP receipt data")
    status = Column(
        ENUM(ReceiptStatus, create_type=False),
        nullable=False,
        default=ReceiptStatus.INIT,
        doc="IAP receipt validation status",
    )
    purchased_at = Column(DateTime(timezone=True), nullable=True)
    product_id = Column(Integer, ForeignKey("product.id"), nullable=True)
    product = relationship(
        Product, foreign_keys=[product_id], backref=backref("purchase_list")
    )
    agent_addr = Column(Text, doc="9c agent address where to get FAVs")
    avatar_addr = Column(Text, doc="9c avatar's address where to get items")
    tx = Column(Text, nullable=True, doc="Signed Tx data to be sent.")
    nonce = Column(Integer, nullable=True, doc="Dedicated nonce for this tx.")
    tx_id = Column(
        Text, nullable=True, index=True, doc="Product delivering 9c transaction ID"
    )
    tx_status = Column(
        ENUM(TxStatus, create_type=False), nullable=True, doc="Transaction status"
    )
    bridged_tx_id = Column(
        Text, nullable=True, index=True, doc="Bridged Tx on another planet"
    )
    bridged_tx_status = Column(
        ENUM(TxStatus, create_type=False),
        nullable=True,
        doc="Transaction status on another planet",
    )
    planet_id = Column(
        LargeBinary(length=12),
        nullable=False,
        default=PlanetID.ODIN.value,
        doc="An identifier of planets",
    )
    mileage_change = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        doc="Mileage change by this purchase",
    )
    mileage_result = Column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
        doc="Result mileage after applying this purchase",
    )
    msg = Column(
        Text,
        nullable=True,
        doc="Any error message while doing action. Please append, Do not replace.",
    )

    @classmethod
    def get_user_receipts_by_month(
        cls,
        session,
        agent_addr: str,
        year: int,
        month: int,
        avatar_addr: Optional[str] = None,
        include_product: bool = True,
        only_paid_products: bool = True,
        sku_pattern: Optional[str] = None,
        exclude_sku_patterns: Optional[List[str]] = None
    ) -> List["Receipt"]:
        """
        특정 유저의 특정 월 구매 영수증 목록을 조회합니다.
        클라이언트는 UTC 기준으로 year, month를 전달하고,
        DB에 저장된 KST 시간을 UTC로 변환하여 조회합니다.

        Args:
            session: SQLAlchemy 세션
            agent_addr: 9c agent 주소
            avatar_addr: 9c avatar 주소 (옵셔널, 제공되지 않으면 agent의 모든 avatar 합산)
            year: 조회할 연도 (UTC 기준)
            month: 조회할 월 (1-12, UTC 기준)
            include_product: product 정보를 함께 불러올지 여부 (기본값: True)
            only_paid_products: 가격이 0보다 큰 상품만 필터링할지 여부 (기본값: True)
            sku_pattern: 포함할 google_sku 패턴 (정규표현식, 예: "adventurebosspass\\d+premium")
            exclude_sku_patterns: 제외할 google_sku 패턴 리스트 (정규표현식 리스트)

        Returns:
            List[Receipt]: 해당 월에 해당 유저가 구매한 영수증 목록 (product 정보 포함)
        """
        from shared.models.product import Price

        # UTC 기준 해당 월의 시작과 끝 시간
        utc_start = datetime(year, month, 1)
        if month == 12:
            utc_end = datetime(year + 1, 1, 1)
        else:
            utc_end = datetime(year, month + 1, 1)

        # DB에 저장된 KST 시간을 UTC로 변환하여 조회
        # KST = UTC + 9시간이므로, KST 시간에서 9시간을 빼면 UTC 시간
        # PostgreSQL의 timezone 함수를 사용하여 KST를 UTC로 변환
        filter_conditions = [
            cls.agent_addr == agent_addr,
            func.timezone('UTC', cls.created_at) >= utc_start,
            func.timezone('UTC', cls.created_at) < utc_end,
        ]

        # avatar_addr이 제공되면 필터링 조건에 추가
        if avatar_addr is not None:
            filter_conditions.append(cls.avatar_addr == avatar_addr)

        query = session.query(cls).filter(and_(*filter_conditions))

        # 가격이 0보다 큰 상품만 필터링
        if only_paid_products:
            query = query.join(cls.product).join(Price).filter(Price.price > 0)

        query = query.order_by(cls.created_at.desc())

        if include_product:
            query = query.options(joinedload(cls.product))

        # 결과를 가져온 후 Python에서 SKU 패턴 필터링
        receipts = query.all()

        # SKU 패턴 필터링
        if sku_pattern or exclude_sku_patterns:
            filtered_receipts = []

            for receipt in receipts:
                if not receipt.product:
                    continue

                product_sku = receipt.product.google_sku
                if not product_sku:
                    continue

                # 제외 패턴 확인
                if exclude_sku_patterns:
                    should_exclude = False
                    for pattern in exclude_sku_patterns:
                        if re.search(pattern, product_sku, re.IGNORECASE):
                            should_exclude = True
                            break
                    if should_exclude:
                        continue

                # 포함 패턴 확인
                if sku_pattern:
                    if not re.search(sku_pattern, product_sku, re.IGNORECASE):
                        continue

                filtered_receipts.append(receipt)

            return filtered_receipts

        return receipts
