"""
`grant_items` tx 조립 — **영수증 경로(send_product)와 무영수증 경로(grant_outbox)가 공유한다.**

지급 자체(구성품→티커 변환 · GrantItems · unsigned tx · KMS 서명)는 원래 워커의
`send_product_task.create_tx` 안에 receipt 와 뒤엉켜 있었다. PLD-1564(포탈 포인트샵 지급)가
같은 조립을 필요로 하므로, receipt 를 모르는 순수 함수로 여기 끌어냈다.
**복제 금지** — 두 경로가 다른 tx 를 만들면 어느 쪽이 맞는지 알 수 없게 된다.

이 모듈은 DB 세션도, config 도 모른다. 입력은 `Product`(구성품 로드된 상태)와 지급 대상 주소,
nonce, memo 뿐이다.
"""

import datetime
from typing import Any, Dict, List, Optional, Protocol

from shared.enums import PlanetID
from shared.lib9c.actions.grant_items import GrantItems
from shared.lib9c.models.address import Address
from shared.lib9c.models.fungible_asset_value import FungibleAssetValue
from shared.utils.transaction import append_signature_to_unsigned_tx, create_unsigned_tx

# tx 유효기간 — send_product 가 쓰던 값(현재+7일)을 그대로 옮겼다.
TX_TIMESTAMP_DELTA = datetime.timedelta(days=7)

# THOR(테스트 행성) 프로모션 2배. **결제 프로모션**이라 무상 지급에는 적용하지 않는다
#   (호출자가 multiplier 를 명시한다 — grant_outbox 경로는 항상 1).
THOR_PROMO_MULTIPLIER = 2


class Signer(Protocol):
    """`shared._crypto.Account` 의 서명에 필요한 최소 인터페이스(테스트 대역용)."""

    address: str
    pubkey: bytes

    def sign_tx(self, unsigned_tx: bytes) -> bytes:
        ...


def promo_multiplier(planet_id: PlanetID) -> int:
    """결제 프로모션 배수. THOR 계열만 2배(기존 send_product 동작)."""
    return (
        THOR_PROMO_MULTIPLIER
        if planet_id in (PlanetID.THOR, PlanetID.THOR_INTERNAL)
        else 1
    )


def build_claim_data(product, multiplier: int = 1) -> List[FungibleAssetValue]:
    """
    상품 구성품(`fungible_item_list` + `fav_list`) → `grant_items` 가 받는 FAV 리스트.

    티커는 DB 에 저장된 온체인 포맷을 그대로 쓴다(`Item_NT_…`, `FAV__CRYSTAL` — 런타임 변환 아님).
    아이템은 decimal_places=0 고정, FAV 는 컬럼값을 따른다.

    ⚠️ 호출 전에 두 관계가 로드돼 있어야 한다(`selectinload`). 비어 있으면 빈 리스트가 나오고,
       그 상태로 tx 를 만들면 **아무것도 안 주는 tx** 가 체인에 올라간다 — 호출자가 막아야 한다.
    """
    claim_data: List[FungibleAssetValue] = []
    for item in product.fungible_item_list:
        claim_data.append(
            FungibleAssetValue.from_raw_data(
                ticker=item.fungible_item_id,
                decimal_places=0,
                amount=item.amount * multiplier,
            )
        )
    for fav in product.fav_list:
        claim_data.append(
            FungibleAssetValue.from_raw_data(
                ticker=fav.ticker,
                decimal_places=fav.decimal_places,
                amount=fav.amount * multiplier,
            )
        )
    return claim_data


def build_grant_items_action(
    *,
    avatar_addr: str,
    claim_data: List[FungibleAssetValue],
    memo: Optional[str] = None,
) -> GrantItems:
    """`grant_items` 액션. memo 는 체인에 그대로 실리는 문자열(JSON 직렬화는 호출자 책임)."""
    return GrantItems(
        claim_data=[
            {"avatarAddress": Address(avatar_addr), "fungibleAssetValues": claim_data}
        ],
        memo=memo,
    )


def sign_action_tx(
    *,
    account: Signer,
    planet_id: PlanetID,
    nonce: int,
    plain_value: Dict[str, Any],
    timestamp: Optional[datetime.datetime] = None,
) -> bytes:
    """unsigned tx 작성 → KMS 서명 → 서명 붙인 tx bytes."""
    unsigned_tx = create_unsigned_tx(
        planet_id=planet_id,
        public_key=account.pubkey.hex(),
        address=account.address,
        nonce=nonce,
        plain_value=plain_value,
        timestamp=timestamp
        or (datetime.datetime.now(tz=datetime.timezone.utc) + TX_TIMESTAMP_DELTA),
    )
    return append_signature_to_unsigned_tx(unsigned_tx, account.sign_tx(unsigned_tx))


def create_grant_items_tx(
    *,
    account: Signer,
    planet_id: PlanetID,
    avatar_addr: str,
    claim_data: List[FungibleAssetValue],
    nonce: int,
    memo: Optional[str] = None,
    timestamp: Optional[datetime.datetime] = None,
) -> bytes:
    """
    구성품이 준비된 상태에서 서명까지 끝난 `grant_items` tx 한 건.

    ⚠️ `claim_data` 가 비어 있어도 **막지 않는다** — 기존 영수증 경로(`send_product`)의 동작을
       그대로 보존하기 위해서다(라이브 결제 흐름). 빈 지급 tx 는 가스만 태우고 유저에겐 아무 일도
       일어나지 않으므로, 빈 구성품 차단은 **호출자**가 한다:
         · API `POST /admin/grant` — 구성품 없는 productId 는 400
         · 무영수증 워커 — 빈 구성품이면 tx 를 만들지 않고 FAILED(사유 기록)
    """
    action = build_grant_items_action(
        avatar_addr=avatar_addr, claim_data=claim_data, memo=memo
    )
    return sign_action_tx(
        account=account,
        planet_id=planet_id,
        nonce=nonce,
        plain_value=action.plain_value,
        timestamp=timestamp,
    )
