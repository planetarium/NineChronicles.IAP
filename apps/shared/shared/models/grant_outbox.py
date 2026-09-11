from shared.enums import GrantStatus, PlanetID, TxStatus
from shared.models.base import AutoIdMixin, Base, EnumType, TimeStampMixin
from shared.models.product import Product
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, LargeBinary, Text
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.orm import Mapped, relationship

# 실 DB 는 Postgres 라 JSONB 를, 테스트는 SQLite 라 JSON 을 쓴다. `JSONB` 를 그대로 두면
# SQLite 가 타입을 컴파일하지 못해 이 테이블을 쓰는 테스트가 **전부** 수집 단계에서 죽는다
# (receipt.data 는 raw JSONB 지만 그 테이블은 SQLite 테스트에서 생성되지 않아 안 걸렸다).
GACHA_RESULT_TYPE = JSON().with_variant(JSONB(), "postgresql")



class GrantOutbox(AutoIdMixin, TimeStampMixin, Base):
    """
    (PLD-1564) 영수증 없는 범용 지급 아웃박스 — 포탈 포인트샵(무상 포인트 소모)의 온체인 지급 추적.

    `voucher_grant_outbox`(PLD-1468) 의 형제고 방향만 반대다(그쪽은 IAP→포탈, 이쪽은 포탈→체인).
    권위 있는 상태("왜 줬나" — 포인트 차감·추첨 결과)는 포탈에 있고, 이 테이블은 IAP 측
    **"온체인에 넣었나?" 아웃박스 마커**다.

    ## 왜 `receipt` 를 재사용하지 않는가 (뒤집지 말 것)
    `receipt.data`(영수증 JSON)는 NOT NULL 이고, `ReceiptStatus` 검증 상태기계·환불 폴링·
    `GET /api/admin/stats/product-sales` 매출 집계가 전부 "결제가 있었다"를 전제한다. 무상 지급을
    거기 섞으면 정산·CS·환불 로직이 오염된다(의사 영수증은 매출로 집계되고, 환불 폴링이
    스토어에 없는 주문을 조회한다). 그래서 별도 테이블이고, 그 덕에 매출 집계는 **자동으로**
    분리된다(집계 쿼리가 `receipt` 만 스캔한다).

    ## 멱등
    `external_ref` UNIQUE = 1 주문 = 1 행 = 온체인 tx 1건. 포탈 orderId 기반 `shop:<orderId>`.
    같은 ref 재요청은 새 tx 를 만들지 않고 기존 행을 그대로 반환한다(API 200). 워커도 진입 시
    이미 성공한 행이면 즉시 종료한다.

    ## 감사 로그
    `GrantItems` 는 지급 계정 잔액이 없어도 발행되는 force-grant(사실상 민터 권한)다. 그래서
    이 테이블이 감사 기록을 겸한다: **누가**(`external_ref` 의 네임스페이스 + `memo` 에 박힌
    주문 참조) **언제**(`created_at`/`granted_at`) **무엇을**(`product_id`,
    `avatar_addr`/`planet_id`, `tx_id`) 지급했는지가 남는다. `memo` 는 체인 tx 에 실제로 실린
    문자열 원본이라 온체인 값과 대조할 수 있다.

    호출자 신원은 admin JWT 에 subject 클레임이 없어 이 테이블에 별도 컬럼으로 두지 않는다.
    대신 **`external_ref` 네임스페이스가 등록된 출처 식별자**다(PLD-1575: 허용 네임스페이스
    목록을 설정으로 강제하고, 등록 밖 네임스페이스는 400 으로 끊는다 — app/grant_guard.py).
    그래서 `shop:` 접두어는 관례가 아니라 계약이고, 행만 봐도 어느 출처가 요청했는지 남는다.
    """

    __tablename__ = "grant_outbox"

    external_ref = Column(
        Text,
        nullable=False,
        unique=True,
        doc="외부 시스템의 멱등키. 포탈 포인트샵은 `shop:<orderId>`. 1 ref = 1 tx",
    )
    product_id = Column(Integer, ForeignKey("product.id"), nullable=False)
    product: Mapped["Product"] = relationship("Product", foreign_keys=[product_id])
    planet_id = Column(
        LargeBinary(length=12),
        nullable=False,
        default=PlanetID.ODIN.value,
        doc="An identifier of planets (receipt.planet_id 와 같은 타입·표기)",
    )
    avatar_addr = Column(
        Text, nullable=False, doc="9c avatar's address where to get items"
    )
    agent_addr = Column(
        Text,
        nullable=True,
        doc="9c agent address. grant_items 는 아바타만 필요해서 감사·조회 편의용(옵션)",
    )
    memo = Column(
        Text,
        nullable=True,
        doc="체인 tx 에 실린 memo(JSON 문자열). 체인만 보고 주문을 역추적하는 근거",
    )
    status = Column(
        EnumType(GrantStatus),
        nullable=False,
        default=GrantStatus.PENDING,
        server_default=str(
            GrantStatus.PENDING.value
        ),  # "0" — bulk/raw insert도 NOT NULL 안전
    )
    tx = Column(Text, nullable=True, doc="Signed Tx data to be sent.")
    nonce = Column(Integer, nullable=True, doc="Dedicated nonce for this tx.")
    tx_id = Column(
        Text, nullable=True, index=True, doc="Product delivering 9c transaction ID"
    )
    tx_status = Column(
        # receipt 와 같은 PG enum(`txstatus`)을 재사용한다 — 운영 쿼리가 두 테이블을 같은
        #   어휘로 읽고, retryer 류의 문자열 비교("STAGED")도 그대로 통한다.
        ENUM(TxStatus, create_type=False),
        nullable=True,
        doc="Transaction status",
    )
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(Text, nullable=True)
    granted_at = Column(DateTime(timezone=True), nullable=True)

    # ── (PLD-1562) 뽑기 ────────────────────────────────────────────────────────
    # 추첨은 **이 행을 만들 때 1회** 일어나고 결과가 여기 동결된다. `external_ref` UNIQUE 가
    # "1 주문 = 1 행"이므로 재요청은 같은 행 = 같은 결과다 — 재추첨 불가가 앱 규약이 아니라
    # DB 제약으로 강제되는 지점이다. 고정 상품 행은 둘 다 NULL 이다.
    gacha_entry_id = Column(
        Integer,
        ForeignKey("product_gacha_entry.id", ondelete="SET NULL"),
        nullable=True,
        doc=(
            "뽑힌 풀 칸. **조회·집계 편의용이고 지급 근거가 아니다**(지급은 gacha_result 의"
            " 동결값으로 한다). ⚠️ **단연(draw_count=1)일 때만 채운다** — 10연에서 대표 칸"
            " 하나를 박으면 나머지 9회가 조인에서 사라져 집계가 거짓말을 한다."
            " 회차별 원본은 gacha_result['draws'] 가 전부 들고 있으므로 집계는 그쪽을 쓸 것"
        ),
    )
    gacha_result = Column(
        GACHA_RESULT_TYPE,
        nullable=True,
        doc=(
            "추첨 결과 동결본 + 그때의 풀 스냅샷(확률 분쟁의 증거)."
            " v2: {version, drawCount, draws:[{entryId,entryName,kind,ticker,"
            "decimalPlaces,amount}], claim:[티커별 **합산**], pool:[...], totalWeight,"
            " drawnAt}. claim 은 지급 명령이고 draws 가 회차별 원본이다"
        ),
    )

    # ⚠️ 워커는 `gacha_entry_id` 로 풀을 **다시 읽지 않는다**. 읽으면 운영이 표를 고치는 것이
    #    곧 뒷문 재추첨이 된다(유저가 뽑은 것과 다른 게 지급된다). 지급 근거는 항상
    #    `gacha_result["claim"]` 이고, FK 는 "어느 칸이었나"를 나중에 조인해 보기 위한 것뿐이다.
    #    같은 이유로 FK 는 **ON DELETE SET NULL** 이다. CASCADE 면 칸을 지울 때 지급 이력까지
    #    사라지고(감사 기록 소실), 기본(NO ACTION)이면 한 번이라도 뽑힌 칸을 지울 수 없어
    #    라이브 풀이 append-only 가 된다(이벤트 로테이션이 막힌다). SET NULL 은 무손실이다 —
    #    결과·수량·확률은 전부 gacha_result 에 남고 조인 링크만 끊긴다.

    __table_args__ = (
        # 미완료(PENDING) 폴링용 — voucher_grant_outbox 의 ix_..._status 선례와 같다.
        Index("ix_grant_outbox_status", "status"),
        # (PLD-1575) 머니 가드의 시간창 카운트(`created_at >= now - 1h/1d`)용. 이 카운트는
        #   **요청 경로**에서 매번 돌기 때문에 풀스캔이면 지급 API 지연이 행 수에 비례한다.
        Index("ix_grant_outbox_created_at", "created_at"),
        # (PLD-1575) 아바타 축 상한 + 의미적 중복 감지용
        #   (`avatar_addr = ? AND created_at >= ?`, 중복은 여기에 product_id 필터가 더 붙는다).
        #   `ix_grant_outbox_created_at` 만 있으면 창 안 **모든** 행의 힙을 읽어 아바타를
        #   걸러야 한다 — 이 카운트는 요청 경로 **그리고 advisory lock 안**에서 돌기 때문에
        #   지연이 곧 직렬화된 지급 처리량이다. 선두 컬럼을 avatar_addr 로 두면 한 아바타의
        #   행만 훑는다(아바타당 행 수는 아바타 축 상한이 직접 묶는다).
        #   product_id 를 넣지 않은 이유: 아바타 축(product 무관)이 이 인덱스를 그대로 쓰고,
        #   중복 감지는 "이 아바타의 창 안 행"이 이미 몇 건 수준이라 필터가 사실상 무료다.
        Index("ix_grant_outbox_avatar_addr_created_at", "avatar_addr", "created_at"),
        # (PLD-1562) 감사 조인(어느 칸이 몇 번 나왔나) + 위 SET NULL 의 삭제 검사용.
        Index("ix_grant_outbox_gacha_entry_id", "gacha_entry_id"),
    )
