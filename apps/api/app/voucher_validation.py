"""
(PLD) 바우처 상품→티켓 매핑 설정시점 검증 — C1(ticket_type ∈ 라이브 정책)/C3-lite(경제 상한).

admin CRUD와 CSV import가 **공유**하는 순수 검증 로직. config/DB에 의존하지 않게(테스트 용이)
url·cap을 인자로 받는다. 위반은 FastAPI HTTPException으로 표면화(호출부에서 그대로 전파).
"""
from typing import Optional, Union

import requests
from fastapi import HTTPException
from shared.enums import ProductType


def fetch_live_prize_tables(url: Optional[str]) -> dict:
    """
    포탈 공개 prize-tables read → {ticket_type: [tiers]}.
      미설정(url None)/temporary(placeholder·off 정책)/도달불가/비200은 **fail-closed**(저장 거부).
      → 실제 구성·활성 정책이 없는데 매핑을 저장해 grant 미스매치를 만드는 것을 원천 차단.
    """
    if not url:
        raise HTTPException(
            status_code=503, detail="portal_prize_tables_url 미설정 — 매핑 검증 불가"
        )
    try:
        resp = requests.get(url, timeout=5)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"포탈 정책 조회 실패: {e}")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"포탈 정책 조회 {resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="포탈 정책 응답 파싱 실패")
    if not isinstance(body, dict) or body.get("temporary"):
        raise HTTPException(status_code=409, detail="포탈 정책 미구성(temporary) — 매핑 저장 불가")
    return body.get("prizeTables") or {}


def validate_voucher_mapping(
    ticket_type: str, count: int, tables: dict, cap: Optional[int]
) -> None:
    """
    C1 + count sanity + C3-lite. 위반 시 HTTPException.
      - C1: ticket_type이 라이브 정책 prizeTables에 존재(빈 표도 거부).
      - count: 1 이상 정수.
      - C3-lite: cap이 설정돼 있으면 count×최대상금(NCG) ≤ cap (머니펌프 방어, 가격/환율 무관).
    """
    if not isinstance(count, int) or count < 1:
        raise HTTPException(status_code=400, detail="count는 1 이상 정수여야 합니다")
    tiers = tables.get(ticket_type)
    if not tiers:
        raise HTTPException(
            status_code=409,
            detail=f"ticket_type '{ticket_type}' not in live policy {sorted(tables.keys())}",
        )
    if cap is not None:
        try:
            max_prize = max(
                (float(t.get("ncg", 0) or 0) for t in tiers if isinstance(t, dict)),
                default=0.0,
            )
        except (TypeError, ValueError):
            raise HTTPException(status_code=502, detail="포탈 정책 tier 파싱 실패")
        if count * max_prize > cap:
            raise HTTPException(
                status_code=400,
                detail=f"C3-lite exceeded: count*maxPrize({count}*{max_prize}) > cap({cap})",
            )


def validate_product_voucher_eligible(
    product_id: int, product_type: Optional[Union[ProductType, str]]
) -> None:
    """
    (C6) 바우처 티켓을 매핑할 수 있는 상품인지 — **결제 상품(IAP)만 허용**. 위반 시 400.

    무료 상품(FREE)도 결제와 동일하게 VALID+SUCCESS 영수증을 만들고, 발급 enroll 조건은
    status/tx_status/store/cutoff 뿐이라 무료 클레임 1회가 곧 티켓 N장이 된다. 메인넷 실측
    (2026-08) FREE 상품 영수증이 일 ~790건이므로 매핑 1행이 결제 0원짜리 NCG faucet 이 된다.

    MILEAGE 도 막는다. 마일리지는 무료 클레임으로도 적립되므로(`/purchase/free` → upsert_mileage)
    "무료 클레임 → 마일리지 → MILEAGE 상품 구매 → VALID+SUCCESS" 사슬이 FREE 차단을 우회한다.
    현금이 새로 들어오지 않은 결제라 티켓 지급 대상이 아니다. 기획 확정 매핑도 $ SKU(IAP)뿐이다.

    얼로우리스트인 이유: ProductType 에 타입이 추가돼도 기본이 차단이고, 미지값·None·오전달
    (예: ORM 클래스 속성 `Product.product_type`)이 조용히 통과하지 않는다(fail-closed).
    """
    name = getattr(product_type, "name", None) or str(product_type)
    if name.strip().upper() != ProductType.IAP.name:
        raise HTTPException(
            status_code=400,
            detail=(
                f"product {product_id} product_type={name} — 바우처 티켓은 결제 상품"
                f"({ProductType.IAP.name})에만 매핑할 수 있습니다"
                " (무료·마일리지 상품은 결제 없이 발급되어 NCG faucet 이 됨)"
            ),
        )


def parse_voucher_columns(
    pairs: list, tables: dict, cap: Optional[int]
) -> Optional[dict]:
    """
    CSV의 (ticket_type, count) **쌍 목록**을 파싱·검증한 REPLACE 집합.
      pairs = [(type_1, count_1), (type_2, count_2), ...] (각 슬롯 원본 문자열). 세미콜론 정렬 불필요.
      반환: None=변경없음(전 슬롯 빈칸) · {}=전체 비활성('-' 단독) · {ticket_type: count}=이 집합으로 REPLACE.
      count 빈칸=1(default). C1/C3-lite는 validate_voucher_mapping에서 강제.
      위반은 HTTPException(호출부 import_utils가 상품 컨텍스트 붙여 ValueError로 재래이즈).
    """
    filled = [
        ((t or "").strip(), (c or "").strip())
        for (t, c) in pairs
        if (t or "").strip() != ""
    ]
    if not filled:
        return None  # 전 슬롯 빈칸 = 유지
    if any(t == "-" for (t, _) in filled):
        # '-'(전체 제거)는 단독 슬롯 신호 — 다른 종류와 섞으면 의도 모호 → 거부.
        if len(filled) != 1:
            raise HTTPException(status_code=400, detail="'-'(전체 제거)는 단독 슬롯으로만 사용하세요")
        return {}
    desired: dict = {}
    for ticket_type, raw in filled:
        if ticket_type in desired:
            raise HTTPException(
                status_code=400, detail=f"중복 ticket_type '{ticket_type}'"
            )
        try:
            count = int(raw) if raw != "" else 1
        except ValueError:
            raise HTTPException(status_code=400, detail=f"voucher_count '{raw}' 정수 아님")
        validate_voucher_mapping(ticket_type, count, tables, cap)
        desired[ticket_type] = count
    return desired
