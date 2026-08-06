"""
(PLD) 바우처 상품→티켓 매핑 설정시점 검증 — C1(ticket_type ∈ 라이브 정책)/C3-lite(경제 상한).

admin CRUD와 CSV import가 **공유**하는 순수 검증 로직. config/DB에 의존하지 않게(테스트 용이)
url·cap을 인자로 받는다. 위반은 FastAPI HTTPException으로 표면화(호출부에서 그대로 전파).
"""
from typing import Optional

import requests
from fastapi import HTTPException


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


def parse_voucher_columns(
    tt_raw: Optional[str], cnt_raw: Optional[str], tables: dict, cap: Optional[int]
) -> Optional[dict]:
    """
    CSV의 voucher 컬럼(voucher_ticket_type/voucher_count)을 파싱·검증한 REPLACE 집합.
      반환: None=변경없음(빈칸) · {}=전체 제거('-') · {ticket_type: count}=이 집합으로 REPLACE.
      다중 종류는 세미콜론 인코딩: "STANDARD;PREMIUM" + "1;1". 각 항목에 C1/C3-lite 강제.
      위반은 HTTPException(호출부 import_utils가 상품 컨텍스트 붙여 ValueError로 재래이즈).
    """
    tt = (tt_raw or "").strip()
    if tt == "":
        return None
    if tt == "-":
        return {}
    types = [t.strip() for t in tt.split(";")]
    # 빈 세그먼트("A;;B")·중복은 count 오정렬/오타 마스킹을 유발하므로 거부.
    if any(t == "" for t in types):
        raise HTTPException(status_code=400, detail="voucher_ticket_type에 빈 세그먼트가 있습니다")
    if len(set(types)) != len(types):
        raise HTTPException(status_code=400, detail="voucher_ticket_type에 중복 종류가 있습니다")
    counts = [c.strip() for c in (cnt_raw or "").split(";")]
    if len(counts) == 1 and counts[0] == "":
        counts = ["" for _ in types]  # count 전부 생략 → 각 1(default)
    if len(counts) != len(types):
        raise HTTPException(
            status_code=400, detail="voucher_ticket_type/voucher_count 개수 불일치"
        )
    desired: dict = {}
    for ticket_type, raw in zip(types, counts):
        try:
            count = int(raw) if raw != "" else 1
        except ValueError:
            raise HTTPException(status_code=400, detail=f"voucher_count '{raw}' 정수 아님")
        validate_voucher_mapping(ticket_type, count, tables, cap)
        desired[ticket_type] = count
    return desired
