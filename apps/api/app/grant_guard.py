"""
지급 API 상품 화이트리스트 — `point_shop_grantable` 한 축만 남았다.

## 왜 나머지(PLD-1575 머니 가드)를 걷어냈는가
원래 이 모듈은 **무엇을(상품) · 얼마나(수량·빈도) · 누가(네임스페이스)** 세 축을 요청
시점에 닫았다. 근거는 "`GrantItems` 는 force-grant 라 사실상 민터 권한" 이었고, 그 안에는
**FAV 수량 상한이 곧 화폐 발행 상한** 이라는 전제가 있었다. 그 전제가 틀렸다:

    GrantItems 의 FAV 분기는 `FAV__` **wrapped currency** 만 받고, 풀 때
    `Currencies.GetMinterlessCurrency(ticker)` 를 탄다. 그 함수가 아는 티커는
    **CRYSTAL / GARAGE / RUNE_*·RUNESTONE_* / SOULSTONE_*** 뿐이고 나머지는 예외다.
    NCG 는 민터가 있는 통화라 이 경로에 아예 없다 — `FAV__NCG` 는 액션이 죽는다.

즉 이 API 로 **직접 찍을 수 있는 화폐가 없다.** 남는 위험은 CRYSTAL·룬스톤(v0.9 에서
거래 가능 유지로 확정돼 마켓 환금 경로가 열려 있다) 정도인데, 그건 한 단계 건너뛴 위험이고
상품 화이트리스트·CSV 등록 검사가 이미 앞단에서 막는다.

비용 쪽은 반대로 컸다. 수량 상한과 티커 얼로우리스트는 **추첨 뒤**에만 판정할 수 있어
(뽑기 상품은 구성품이 비어 있고 상금이 풀에 있다) 거절이 곧 `아웃박스 행 없음 → 포탈
재시도 → 재추첨` 이었다. 2% 짜리 룬 칸에 당첨된 유저가 조용히 다시 뽑히는 경로다.
시간창 상한도 마찬가지로 **정상 트래픽을 400 으로 거절**할 수 있었고(400 은 포탈이 영구
실패로 확정하는 코드다), 그 임계값은 근거 있는 숫자가 아니라 추정이었다.

## 그래서 지금 남은 방어
  · **상품 화이트리스트** — `point_shop_grantable` 이 켜진 상품만 지급된다(아래).
  · `grant_outbox.external_ref` UNIQUE — 1 주문 = 1 행 = 1 tx (멱등).
  · CSV 등록 시점 검증 — 풀 구성 오류는 임포트가 거절한다(`import_utils`).

## 남아 있는 구멍 (알고 두는 것)
admin JWT 에 엔드포인트 스코프가 없다. 토큰이 유출되면 공격자가 **스스로 화이트리스트를
켜고** 상품을 등록할 수 있으므로, 이 한 축이 닫는 것은 "잘못 설정된 상품"이지 "유출된
토큰"이 아니다. 후자는 스코프 분리로만 닫힌다.
"""
from typing import Optional, Union

from fastapi import HTTPException
from shared.enums import ProductType
from shared.models.product import SEASON_PASS_SKU_TOKEN


#: `point_shop_grantable` 셀 토큰. `O` 를 true 에 넣지 않는다 — 숫자 `0`(=False) 오타가
#: True 로 읽히는 비대칭은 머니 플래그에서 허용할 수 없다.
GRANTABLE_TRUE_TOKENS = frozenset({"TRUE", "T", "Y", "YES", "1"})
GRANTABLE_FALSE_TOKENS = frozenset({"FALSE", "F", "N", "NO", "0", "X", "-"})


def parse_point_shop_grantable(value: Optional[str]) -> Optional[bool]:
    """
    상품 CSV 의 `point_shop_grantable` 셀 → True/False/**None(=변경 없음)**.

    **3상태여야 한다.** "TRUE 아니면 False" 로 읽으면 컬럼이 없는 기존 시트로 임포트할 때마다
    전 상품의 화이트리스트가 조용히 꺼진다(= 포인트샵 전면 중단). 빈칸·컬럼 부재는 유지고,
    명시적으로 쓴 값만 반영한다.

    해석 불가 토큰은 ValueError — 머니 플래그라 "모르는 값은 False" 도 위험하다(오타로 꺼져도
    장애고, 무엇보다 운영자가 켠 줄 알고 방치한다). 임포트를 세우는 쪽이 낫다.
    """
    if value is None:
        return None
    token = value.strip().upper()
    if token == "":
        return None
    if token in GRANTABLE_TRUE_TOKENS:
        return True
    if token in GRANTABLE_FALSE_TOKENS:
        return False
    raise ValueError(
        f"point_shop_grantable '{value}' 를 해석할 수 없습니다"
        f" (허용: {sorted(GRANTABLE_TRUE_TOKENS)} / {sorted(GRANTABLE_FALSE_TOKENS)}"
        " / 빈칸=유지)"
    )


def _type_name(product_type: Optional[Union[ProductType, str]]) -> str:
    return getattr(product_type, "name", str(product_type))


def validate_point_shop_grantable_eligible(
    product_id: int,
    product_type: Optional[Union[ProductType, str]],
    google_sku: Optional[str] = None,
) -> None:
    """
    이 상품에 `point_shop_grantable` 을 **켤 수 있는가** — 현금 상품이면 400.

    화이트리스트 플래그 자체가 1차 가드지만, 플래그를 켜는 경로(백오피스 CRUD · CSV import)와
    지급 경로 **양쪽에서** 이 검사를 돌린다. 이유는 플래그가 스테일해질 수 있기 때문이다:
    CSV import 는 기존 상품의 `product_type` 을 바꿀 수 있어서, 한 번 켠 플래그가 나중에
    현금 상품에 붙어 있을 수 있다. 지급 시점 재검증이 그 창을 닫는다.

    얼로우리스트가 아니라 **명시 차단 목록**인 이유: 포인트샵 상품이 어떤 유형으로 등록될지는
    기획 소관(FREE 가 자연스럽지만 MILEAGE 도 가능)이고, 여기서 좁히면 운영이 막힌다.
    반드시 막아야 하는 건 "현금이 오간 상품을 무상 발행하는 것"이다. 단 **미지 유형은 차단**한다
    (ProductType 에 새 유형이 추가돼도 기본이 차단, None·오전달도 조용히 통과하지 않는다).
    """
    name = _type_name(product_type)
    known = {member.name for member in ProductType}
    if name not in known:
        raise HTTPException(
            status_code=400,
            detail=f"product {product_id} product_type={name}"
            " — 알 수 없는 상품유형(포인트샵 지급 불가)",
        )
    if name == ProductType.IAP.name:
        raise HTTPException(
            status_code=400,
            detail=f"product {product_id} product_type={name}"
            " — 현금 상품은 무상 지급 대상이 아닙니다 (포인트샵 전용 상품만 허용)",
        )
    if google_sku and SEASON_PASS_SKU_TOKEN in google_sku:
        # 시즌패스는 현금 패스고 지급 주체가 SeasonPass 서비스다 — IAP 가 발행할 물건이 아니다.
        raise HTTPException(
            status_code=400,
            detail=f"product {product_id} sku={google_sku}"
            " — 시즌패스 상품은 포인트샵 지급 대상이 아닙니다",
        )


def assert_product_grantable(product) -> None:
    """
    지급 시점 화이트리스트. **이 한 축이 남은 유일한 요청 시점 가드다.**

    플래그가 꺼져 있으면 그 상품은 포인트샵으로 지급되지 않는다. 플래그가 켜져 있어도
    상품 유형을 다시 본다 — 켠 뒤에 바뀌었을 수 있다(위 함수 도커스트링).
    """
    if not bool(getattr(product, "point_shop_grantable", False)):
        raise HTTPException(
            status_code=400,
            detail=(
                f"product {product.id} 는 포인트샵 지급 대상이 아닙니다"
                " (point_shop_grantable=false — 상품 CSV 나 백오피스에서 켜야 합니다)"
            ),
        )
    validate_point_shop_grantable_eligible(
        product.id, product.product_type, product.google_sku
    )


def namespace_of(external_ref: str) -> Optional[str]:
    """
    `<namespace>:<orderId>` 의 앞부분. **거절하지 않는다** — 감사 로그의 호출자 식별용이다
    (admin JWT 에 subject 클레임이 없어 이게 유일한 출처 단서다).
    """
    if not external_ref or ":" not in external_ref:
        return None
    head = external_ref.split(":", 1)[0].strip()
    return head or None
