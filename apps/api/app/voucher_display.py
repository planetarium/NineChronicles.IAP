"""
(PLD-1472) 상품 조회 응답에 복권(NCG Voucher) 티켓을 싣는 **표시 전용(read-only)** 계층.

소유권 원칙: **IAP 는 발급까지만 안다.** 상금표·확률·개봉은 포탈 voucher_policy 가 권위라
여기서 내보내는 것은 티켓 **종류와 장수뿐**이다(schemas/product.py `VoucherTicketSchema` 참고).

엔드포인트(app/api/product.py)에서 굳이 분리한 이유 두 가지:
  1. N+1 방지의 핵심(= "상품마다 조회하지 않는다")을 함수 하나에 가둬 회귀를 어렵게 만든다.
     상품 목록은 카테고리 전체(`GET /api/product`)와 전 상품(`GET /api/product/all`)이라
     상품별 조회를 하면 그대로 수백 쿼리가 된다.
  2. `app.config` 를 임포트하지 않아 테스트에서 그대로 부를 수 있다. 엔드포인트 모듈은 임포트만으로
     `app.config.Settings()` 를 평가하고(부모 패키지 `app.api.__init__` 가 admin/purchase 까지
     끌어온다) 전체 런타임 설정 없이는 임포트 자체가 실패한다 — `app/voucher_validation.py` 와 같은 사정.
     (엔드포인트까지 테스트하려면 우회가 필요하다. 방법은
      `apps/api/tests/test_product_voucher_tickets.py` 의 `product_api` 픽스처에 있다 —
      env 를 채우는 걸로는 안 뚫린다. 로컬 `.env` 의 옛 키가 `extra_forbidden` 을 유발한다.)
"""

from typing import Dict, Iterable, List, Tuple

from shared.enums import ProductType
from shared.models.product import Product
from shared.models.product_voucher_grant import ProductVoucherGrant
from shared.schemas.product import SimpleProductSchema, VoucherTicketSchema
from sqlalchemy import select


def active_tickets_by_product(
    sess, product_ids: Iterable[int]
) -> Dict[int, List[VoucherTicketSchema]]:
    """
    상품 id → 표시할 티켓 목록. **쿼리 한 번**으로 여러 상품분을 모아 온다.

    필터는 워커가 보는 **상품 단위** 조건과 같게 맞춘다 — 표시와 발급이 어긋나면 클라가 없는
    티켓을 광고한다:
      - `active=false` 는 placeholder 이자 킬스위치라 발급 제외 → 노출도 제외.
      - `count <= 0` 은 워커가 건너뛴다 → 노출도 제외.
      - 결제 상품(`ProductType.IAP`)만. FREE/MILEAGE 에 매핑이 남아 있어도 워커가 발급하지 않는다
        (C6 게이트). 상품유형을 뒤집었다 되돌리는 동안 매핑 행은 그대로 남으므로 실제로 생긴다
        (인터널에 지금 그런 행이 있다: FREE 상품 111 에 active 매핑).

    ⚠️ 위 세 조건은 워커 `apps/worker/app/tasks/voucher_grant_task.py`
       (`grantable_product_ids` / `tickets_for_product`) 와 **중복 정의**다. apps/api 와 apps/worker 는
       서로 임포트하지 않는 별개 패키지라 공유할 곳이 없다 — 한쪽을 바꾸면 다른 쪽도 함께 바꿀 것.

    ⚠️ 그리고 이건 발급 조건의 **부분집합**이다. 워커에만 있고 API 가 볼 수 없는 게이트가 더 있다:
       `voucher_grant_enabled`(워커 config, **기본값 false**) · `voucher_grant_cutoff`(그 이전
       결제는 영구히 대상 아님) · `_grantable_stores()`(prod 은 실스토어만) · 포탈 정책/planet 등록.
       즉 **표시 킬스위치(active 컬럼)와 발급 킬스위치(워커 env)는 서로 다른 스위치**다. 매핑만 켜고
       워커가 꺼져 있으면 "복권 N장"을 광고한 채 발급이 안 되고, 나중에 cutoff 를 런칭 시각으로
       잡으면 그 구간 유료 결제는 미지급으로 굳는다. 롤아웃 순서는 VOUCHER_ADMIN_API.md 참고.

    정렬은 (product_id, ticket_type) 오름차순으로 **고정**한다. DB 가 돌려주는 순서에 맡기면
    같은 데이터에도 응답 바이트가 흔들려 클라 캐시·스냅샷 테스트가 이유 없이 깨진다.
    (정확한 순서는 DB collation 을 따른다 — PG 와 테스트의 SQLite 가 다를 수 있으나 ticket_type 은
     대문자 ASCII 인 prizeTables 키라 실질 차이는 없고, 같은 DB 안에서 안정적이면 목적은 달성된다.)
    """
    product_ids = list(product_ids)
    if not product_ids:
        return {}

    rows = (
        sess.execute(
            select(ProductVoucherGrant)
            .join(Product, Product.id == ProductVoucherGrant.product_id)
            .where(
                ProductVoucherGrant.product_id.in_(product_ids),
                ProductVoucherGrant.active.is_(True),
                ProductVoucherGrant.count > 0,
                Product.product_type == ProductType.IAP,
            )
            .order_by(ProductVoucherGrant.product_id, ProductVoucherGrant.ticket_type)
        )
        .scalars()
        .all()
    )

    ticket_map: Dict[int, List[VoucherTicketSchema]] = {}
    for row in rows:
        ticket_map.setdefault(row.product_id, []).append(
            VoucherTicketSchema(ticket_type=row.ticket_type, count=row.count)
        )
    return ticket_map


def attach_voucher_tickets(
    sess, targets: Iterable[Tuple[int, SimpleProductSchema]]
) -> None:
    """
    (product_id, 상품 스키마) 쌍들에 티켓을 붙인다. 응답에 실릴 것을 **다 모은 뒤 한 번** 부를 것.

    (id, 스키마) 쌍 목록을 받는 이유: 상품↔카테고리가 다대다라 같은 상품이 여러 카테고리에
    서로 다른 스키마 인스턴스로 실릴 수 있다. dict[product_id] 로 받으면 그중 하나만 채워진다.

    매핑이 없는 상품은 손대지 않는다 — 스키마 기본값(빈 리스트)이 그대로 "매핑 없음"을 뜻한다.
    """
    targets = list(targets)
    if not targets:
        return

    ticket_map = active_tickets_by_product(sess, {pid for pid, _ in targets})
    for product_id, schema in targets:
        tickets = ticket_map.get(product_id)
        if tickets:
            # 리스트는 쌍마다 새로 만든다(같은 상품이 두 카테고리에 실릴 때 리스트를 공유하지 않게).
            schema.voucher_tickets = list(tickets)
