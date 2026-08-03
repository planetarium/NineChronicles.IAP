from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, backref, relationship

from shared.models.base import AutoIdMixin, Base, TimeStampMixin
from shared.models.receipt import Receipt


class VoucherGrantOutbox(AutoIdMixin, TimeStampMixin, Base):
    """
    (PLD-1468) NCG Voucher 아웃박스 — 검증된 결제(Receipt)에 대한 포탈 바우처 발급/회수의 멱등·재시도 추적.

    - receipt_id UNIQUE = 1 결제 = 1 행 (멱등).
    - 지급 트리거(worker)가 포탈 grant 호출 후 status=GRANTED. 실패는 attempts++/last_error 기록 후 재시도.
    - 리컨사일(beat)이 cutoff 이후 VALID인데 여기 GRANTED가 없는 receipt를 찾아 재호출(포탈 멱등).
    - 환불 감지 시 REVOKE_PENDING → 포탈 revoke 성공 후 REVOKED.

    권위 있는 바우처 상태(등급/개봉/홀드/회수)는 포탈 `purchase_voucher`에 있고,
    이 테이블은 IAP측 "포탈에 넘겼나?" 아웃박스 마커일 뿐이다. (고아 `voucher_request` 재사용 대신 신규 — 옛 스키마 의미·스테일 회피)
    """

    __tablename__ = "voucher_grant_outbox"

    receipt_id = Column(Integer, ForeignKey("receipt.id"), nullable=False, unique=True)
    receipt: Mapped["Receipt"] = relationship(
        "Receipt",
        foreign_keys=[receipt_id],
        uselist=False,
        backref=backref("voucher_grant_outbox"),
    )

    # PENDING / GRANTED / REVOKE_PENDING / REVOKED / FAILED
    status = Column(Text, nullable=False, default="PENDING")
    portal_ref = Column(Text, nullable=True, doc="포탈 grant 응답 참조(멱등 확인용)")
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    granted_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
