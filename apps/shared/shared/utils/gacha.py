"""
(PLD-1562) 뽑기 추첨 — 가중치 추첨 + 결과 동결본 조립.

## 이 모듈이 지켜야 하는 것

1. **난수는 `secrets`**. `random` 은 Mersenne Twister 라 출력 624개를 관측하면 내부 상태가
   복원되고 이후 결과가 예측된다. 뽑기는 돈 경로이고 결과가 유저에게 그대로 노출되므로
   (= 관측 가능하다) 예측 가능한 PRNG 를 쓸 수 없다.
2. **부동소수 금지**. 확률을 float 으로 정규화해 누적 비교하면 잔여 오차로 마지막 칸이
   과대/과소 선택된다. 정수 가중치와 정수 난수만 쓴다(`randbelow(Σweight)`).
3. **결과는 동결된다**. 뽑은 칸의 지급 내용을 그 자리에서 `claim` 으로 펼쳐 둔다 —
   나중에 칸을 읽어 지급하면 운영이 표를 고치는 것이 곧 뒷문 재추첨이 된다.
4. **풀 스냅샷을 같이 남긴다**. 표를 바꾸면 "그때 확률이 얼마였나"를 재현할 수 없고,
   확률 공시 분쟁에서 그게 유일한 증거다.
5. **상금은 아이템과 FAV 둘 다**다(룬스톤·소울스톤·크리스탈이 FAV 축이다). 온체인에선
   둘 다 FungibleAssetValue 라 티커 하나로 합치되, `kind` 를 결과에 못박는다 — 지급 tx 의
   분기(FAV=MintAsset / 아이템=인벤토리 민팅)와 자릿수 해석이 여기서 갈리고, 그 분기를
   나중에 티커 접두어로 복원하면 접두어 관례 하나에 어긋난다.
"""

import secrets
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from shared.models.product import GACHA_KIND_FAV, GACHA_KIND_ITEM

# 추첨 결과 JSON 의 버전. 형식을 바꾸면 올리고, 읽는 쪽이 모르는 버전을 만나면 **거절**한다
# (모르는 형식을 추측해서 지급하면 안 된다 — 조용히 다른 걸 주는 것보다 멈추는 게 낫다).
#   v2: 10연뽑. `draws`(회차별) 추가, `claim` 은 티커별 **합산**본이 됐다.
GACHA_RESULT_VERSION = 2

#: **읽을 수 있는** 버전. 쓰기는 항상 최신(GACHA_RESULT_VERSION)이다.
#: v1 을 남겨 두는 이유는 데이터가 아니라 **배포 스큐**다 — api/worker 가 별도 Deployment 라
#: 롤아웃/롤백 중에 (구 워커 × v2 행) 또는 (신 워커 × v1 행) 창이 열린다. 그 창에 들어온
#: 뽑기 주문은 워커가 `_fail` 로 **즉시 종단**시켜 "결과를 본 뒤 환급" 이 된다.
#: v1 의 `claim` 은 v2 와 모양이 완전히 같아서(1줄짜리 같은 dict) 읽는 비용이 0 이다 —
#: 얻는 것 없는 fail-closed 를 지불하고 롤백 창을 열 이유가 없다.
READABLE_RESULT_VERSIONS = frozenset({1, 2})

#: FAV 자릿수 상한. 실발행량이 `amount * 10**places` 라 자릿수가 곧 배율인데, 이 축을 재는
#: 검사가 여기 말고는 없다(CSV·CHECK 제약 어디도 자릿수를 재지 않는다).
#: lib9c 통화의 최대 자릿수가 18 이다.
MAX_DECIMAL_PLACES = 18


class GachaPoolError(ValueError):
    """풀이 추첨 가능한 상태가 아니다(빈 풀·비정수/0 이하 가중치). 설정 오류."""


def _weight_of(entry: Any) -> int:
    weight = entry.weight
    # DB CheckConstraint 가 이미 막지만, 여기서도 본다 — 이 함수는 raw dict 테스트와
    # 과거 데이터에도 쓰이고, 0 이 섞이면 "절대 안 나오는 칸"이 조용히 생긴다.
    if not isinstance(weight, int) or isinstance(weight, bool) or weight <= 0:
        raise GachaPoolError(
            f"gacha entry {getattr(entry, 'id', '?')} 의 weight 가 양의 정수가 아닙니다: {weight!r}"
        )
    return weight


def draw_entry(
    entries: Sequence[Any],
    *,
    rand_below: Callable[[int], int] = secrets.randbelow,
) -> Any:
    """
    가중치 추첨. `rand_below(n)` 는 `[0, n)` 의 정수를 돌려줘야 한다(테스트 주입용).

    누적합을 **오름차순 정렬 없이** 입력 순서로 순회한다 — 순서가 결과 분포에 영향을 주지
    않기 때문이다(각 칸이 차지하는 구간 길이가 곧 확률이고, 구간의 위치는 무관하다).
    다만 **재현성**을 위해 `id` 로 정렬해 순회한다: 같은 난수 + 같은 풀이면 같은 결과여야
    감사·재현이 가능한데, DB 가 돌려주는 행 순서는 보장되지 않는다.
    """
    if not entries:
        raise GachaPoolError("빈 풀에서는 뽑을 수 없습니다")

    ordered = sorted(entries, key=lambda e: (getattr(e, "id", 0) or 0))
    total = sum(_weight_of(e) for e in ordered)
    # total 은 양수가 보장된다(위에서 각 weight > 0 을 확인했고 풀이 비어 있지 않다).
    roll = rand_below(total)
    if not isinstance(roll, int) or roll < 0 or roll >= total:
        # 주입된 난수원이 계약을 어기면 **여기서 멈춘다**. 클램프하면 경계 칸이 과대 선택된다.
        raise GachaPoolError(f"난수 {roll!r} 가 [0, {total}) 밖입니다")

    cursor = 0
    for entry in ordered:
        cursor += _weight_of(entry)
        if roll < cursor:
            return entry
    # 도달 불가(Σweight == total 이고 roll < total). 방어적으로 남긴다 — 여기 오면 위의
    # 불변식이 깨진 것이므로 마지막 칸을 주는 대신 멈춘다.
    raise GachaPoolError(f"추첨이 칸을 고르지 못했습니다 (roll={roll}, total={total})")


def draw_entries(
    entries: Sequence[Any],
    count: int,
    *,
    rand_below: Callable[[int], int] = secrets.randbelow,
) -> List[Any]:
    """
    N 회 **독립** 추첨(복원추출). 같은 칸이 여러 번 나올 수 있다 — 그게 10연의 정의다.

    비복원(뽑힌 칸 제외)으로 하면 10연이 "서로 다른 10종 보장" 이 되어 공시 확률과
    실제 분포가 갈린다(그리고 풀이 10칸 미만이면 아예 성립하지 않는다).

    ⚠️ 회차마다 `rand_below` 를 새로 부른다. 한 번 뽑아 재사용하면 10연이 같은 칸 10개가 된다.
    """
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        raise GachaPoolError(f"추첨 횟수는 1 이상 정수여야 합니다: {count!r}")
    return [draw_entry(entries, rand_below=rand_below) for _ in range(count)]


def aggregate_claim(picked: Sequence[Any]) -> List[Dict[str, Any]]:
    """
    회차별 결과 → **티커별 합산** 지급 명령.

    합치는 이유: 10연이 같은 칸을 여러 번 뽑으면 claim 행이 중복되고, 그대로 tx 에 실으면
    같은 통화 항목이 10줄 들어간다. 합산이 온체인 페이로드를 줄이고 수량 상한 계산과도
    같은 모양이 된다(가드는 어차피 합을 센다).

    ⚠️ **회차별 원본은 버리지 않는다** — `gacha_result["draws"]` 가 들고 있다. 합산본만
       남기면 "10연에서 뭐가 몇 번 나왔나"를 화면도 감사도 재현할 수 없다.
    """
    merged: Dict[tuple, Dict[str, Any]] = {}
    for e in picked:
        key = (e.kind, e.ticker, int(e.decimal_places or 0))
        row = merged.get(key)
        if row is None:
            merged[key] = {
                "kind": e.kind,
                "ticker": e.ticker,
                "decimalPlaces": int(e.decimal_places or 0),
                "amount": int(e.amount),
            }
        else:
            row["amount"] += int(e.amount)
    # 결정적 순서 — 같은 풀·같은 결과면 동결본이 바이트까지 같아야 diff 로 재현된다
    #   (추첨 순서에 의존하면 같은 결과라도 tx 항목 순서가 요청마다 달라진다).
    return [merged[k] for k in sorted(merged)]


def pool_snapshot(entries: Sequence[Any]) -> List[Dict[str, Any]]:
    """확률 공시·감사용 풀 스냅샷. 지급 내용(티커)까지 포함해 그때의 표를 통째로 남긴다."""
    return [
        {
            "entryId": getattr(e, "id", None),
            # 운영이 그때 올린 시트와 1:1 로 맞춰 볼 축. 확률 분쟁에서 "이 칸" 을 가리키는
            #   건 entryId(내부 PK)가 아니라 시트의 칸 이름이다.
            "slotKey": getattr(e, "slot_key", None),
            "name": e.name,
            "weight": _weight_of(e),
            "kind": e.kind,
            "ticker": e.ticker,
            "decimalPlaces": int(e.decimal_places or 0),
            "sheetItemId": e.sheet_item_id,
            "amount": e.amount,
        }
        for e in sorted(entries, key=lambda e: (getattr(e, "id", 0) or 0))
    ]


def build_gacha_result(
    entries: Sequence[Any],
    picked: Union[Any, Sequence[Any]],
    *,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    아웃박스에 동결할 결과 JSON. `picked` 는 한 칸이거나 회차별 리스트(10연)다.

    `claim` 은 **지급 명령**이다 — 워커가 이 값만 보고 tx 를 만든다. 그래서 여기서
    `build_claim_data` 와 같은 모양(ticker/decimalPlaces/amount)으로 펼쳐 두고,
    같은 티커는 합산한다(10연이 같은 칸을 여러 번 뽑으면 행이 중복된다).

    `draws` 는 **회차별 원본**이다. 합산본만 남기면 "10연에서 뭐가 몇 번 나왔나"를 화면도
    감사도 재현할 수 없다 — 확률 분쟁에서 풀 스냅샷과 함께 이게 증거다.

    `kind` 를 같이 싣는 이유: 워커가 tx 를 만들 때 **FAV 와 아이템의 분기가 이 값으로**
    갈린다. 그 분기를 나중에 티커 접두어로 복원하면 접두어 관례 하나에 어긋난다 —
    뽑은 시점에 무엇이었는지를 결과에 못박아 둔다.
    """
    picks = list(picked) if isinstance(picked, (list, tuple)) else [picked]
    if not picks:
        raise GachaPoolError("추첨 결과가 비어 있습니다")
    return {
        "version": GACHA_RESULT_VERSION,
        "drawCount": len(picks),
        "draws": [
            {
                "entryId": getattr(e, "id", None),
                "entryName": e.name,
                "kind": e.kind,
                "ticker": e.ticker,
                "decimalPlaces": int(e.decimal_places or 0),
                "amount": int(e.amount),
            }
            for e in picks
        ],
        "claim": aggregate_claim(picks),
        "pool": pool_snapshot(entries),
        "totalWeight": sum(_weight_of(e) for e in entries),
        "drawnAt": (now or datetime.now(tz=timezone.utc)).isoformat(),
    }


def claim_from_result(result: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    동결된 결과 → 지급 명령 목록. **읽는 쪽의 유일한 입구**이고 fail-closed 다.

    모르는 버전·빈 claim·형식 위반은 전부 예외다. 지급 tx 는 되돌릴 수 없으므로
    "이상하면 일단 준다"가 없어야 한다 — 멈추면 사람이 보고, 주면 못 되돌린다.
    """
    if not result:
        raise GachaPoolError("뽑기 결과가 비어 있습니다")
    version = result.get("version")
    if version not in READABLE_RESULT_VERSIONS:
        raise GachaPoolError(
            f"모르는 뽑기 결과 버전 {version!r} (지원: {sorted(READABLE_RESULT_VERSIONS)})"
        )
    claim = result.get("claim")
    if not isinstance(claim, list) or not claim:
        raise GachaPoolError("뽑기 결과에 claim 이 없습니다")
    for row in claim:
        if not isinstance(row, dict):
            raise GachaPoolError(f"claim 행이 객체가 아닙니다: {row!r}")
        ticker = row.get("ticker")
        amount = row.get("amount")
        places = row.get("decimalPlaces")
        if not isinstance(ticker, str) or not ticker:
            raise GachaPoolError(f"claim ticker 가 비었습니다: {row!r}")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise GachaPoolError(f"claim amount 가 양의 정수가 아닙니다: {row!r}")
        kind = row.get("kind")
        if kind not in (GACHA_KIND_ITEM, GACHA_KIND_FAV):
            # kind 가 없거나 모르는 값이면 **멈춘다**. 여기서 접두어로 추측해 채우면
            # 지급 tx 의 FAV/아이템 분기가 추측 위에 서게 된다.
            raise GachaPoolError(f"claim kind 가 ITEM/FAV 가 아닙니다: {row!r}")
        # ⚠️ 자릿수를 재는 검사가 **여기 말고는 없다.** 실발행량이
        #    `int(amount * 10**decimalPlaces)` 라 자릿수가 곧 배율인데(180 이면 10^180 배),
        #    CSV 오타 하나가 임포트 검증과 CHECK 제약을 전부 통과해 그대로 체인에 나간다.
        #    그래서 여기가 유일한 방어선이고, 여기서 막는다.
        #    상한 18 = lib9c 통화의 최대 자릿수(그 이상은 통화 정의가 성립하지 않는다).
        if (
            not isinstance(places, int)
            or isinstance(places, bool)
            or not 0 <= places <= MAX_DECIMAL_PLACES
        ):
            raise GachaPoolError(
                f"claim decimalPlaces 는 0~{MAX_DECIMAL_PLACES} 정수여야 합니다: {row!r}"
            )
        # 아이템의 자릿수는 **항상 0** 이다(아이템엔 소수 자릿수가 없다). 0 이 아니면
        #    위와 같은 이유로 순수한 발행 사고다.
        if kind == GACHA_KIND_ITEM and places != 0:
            raise GachaPoolError(
                f"ITEM claim 의 decimalPlaces 는 0 이어야 합니다: {row!r}"
            )
    return claim


def build_gacha_pool_schema(entries: Sequence[Any]) -> List[Any]:
    """
    풀 → 공개 스키마(확률 공시). **rate 는 서버가 계산한다.**

    클라가 weight/Σweight 를 직접 나누게 하면 반올림이 구현마다 갈리고, 무엇보다 화면에
    뜬 확률과 서버가 실제로 뽑는 확률이 다를 수 있는 자리가 생긴다. 같은 수를 한 곳에서만
    만든다 — 여기서 나눈 rate 와 `draw_entry` 가 쓰는 weight 는 같은 Σ 를 쓴다.

    rate 는 **표시용**이다. 감사·분쟁의 근거는 반올림 안 된 `weight` 고, 주문에 동결되는
    스냅샷도 weight 를 남긴다.

    ⚠️ 자릿수를 10 으로 잡은 이유: 6자리면 Σweight 가 2,000,000 을 넘는 순간 희귀 칸이
       **0.0 으로 표시**된다. "표시 0% 인데 나오는 칸"은 확률형 아이템 공시에서 가장
       피해야 할 모양이다(있는 확률을 없다고 광고하는 것이다).
    """
    from shared.schemas.product import GachaEntrySchema

    ordered = sorted(entries, key=lambda e: (getattr(e, "id", 0) or 0))
    total = sum(_weight_of(e) for e in ordered)
    return [
        GachaEntrySchema(
            entry_id=e.id,
            name=e.name,
            weight=_weight_of(e),
            rate=round(_weight_of(e) / total, 10),
            kind=e.kind,
            ticker=e.ticker,
            decimal_places=int(e.decimal_places or 0),
            sheet_item_id=e.sheet_item_id,
            amount=e.amount,
        )
        for e in ordered
    ]
