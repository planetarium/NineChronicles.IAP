from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Union

from pydantic import BaseModel as BaseSchema
from pydantic import Field, model_validator

from shared.enums import ProductAssetUISize, ProductRarity, ProductType, Store


@dataclass
class GooglePriceSchema:
    currency: str
    priceMicros: str
    price: Optional[float] = None

    def __post_init__(self):
        self.price = float(self.priceMicros) / 1_000_000


@dataclass
class GoogleIAPProductSchema:
    packageName: str
    sku: str
    status: str
    defaultPrice: Union[Dict[str, str], GooglePriceSchema]
    prices: Union[Dict[str, Dict[str, str]], Dict[str, GooglePriceSchema]]
    purchaseType: str
    ###
    defaultLanguage: str
    listings: Dict
    managedProductTaxesAndComplianceSettings: Dict

    def __post_init__(self):
        self.defaultPrice = GooglePriceSchema(**self.defaultPrice)
        self.prices = {
            key: GooglePriceSchema(**value) for key, value in self.prices.items()
        }


class VoucherTicketSchema(BaseSchema):
    """
    (PLD-1472) 이 상품을 사면 지급되는 복권(NCG Voucher) 티켓 — **종류와 장수만**.

    상금표·확률·개봉은 **포탈이 소유**한다(기획 소유권 원칙: "IAP 는 상금을 몰라야 한다").
    IAP 의 역할은 발급까지이므로 여기에 상금을 실으면 진실이 두 곳이 되고, 상금 조정이
    IAP 배포를 기다리게 된다. 클라는 "티켓 N장"만 표시하고 상금은 포탈에서 본다.
    """

    ticket_type: str = Field(description="포탈 prizeTables 키 (예: STANDARD)")
    count: int = Field(description="지급 장수")

    class Config:
        from_attributes = True


class SimpleProductSchema(BaseSchema):
    name: str
    order: int
    google_sku: str = ""
    apple_sku: str = ""
    apple_sku_k: str = ""
    product_type: ProductType
    daily_limit: Optional[int] = None
    weekly_limit: Optional[int] = None
    account_limit: Optional[int] = None
    active: bool
    buyable: bool = False
    required_level: Optional[int] = None
    mileage: int
    mileage_price: Optional[int] = None
    #: (PLD-1561) 포탈 포인트샵 판매가(표시 포인트). NULL = 포인트로 팔지 않는다.
    #:   포탈은 이 값으로 차감액을 정한다(원장은 포탈 소유). `mileage_price` 와 같은 축.
    point_price: Optional[int] = None
    #: (PLD-1564) 결제 가능 포인트 종류. 'ANY' = 무상 포인트(PP_S)로도 / 'NCG' = 현금화
    #:   가능 포인트로만. 기획의 "PP-X 전용"(가챠·확정교환)이 'NCG' 다.
    #:   **강제는 포탈**이 한다(차감이 포탈 원장) — IAP 는 값만 실어 보낸다.
    point_payable_kinds: str = "ANY"
    # (PLD-1472) 복권 티켓. 마일리지(mileage)와 같은 결로 "이 상품을 사면 뭘 받는지"를 상품에 실어 보낸다.
    #   기본값 빈 리스트 = **하위호환**. 필드를 모르는 구버전 클라와, 매핑이 없는 상품(메인넷은 현재
    #   product_voucher_grant 0행이라 전부 여기 해당)이 같은 모양으로 보인다.
    #   채우는 주체는 상품 조회 API 뿐이다(app/voucher_display.py) — ORM Product 에 대응 속성이 없어
    #   `model_validate(product)` 만으로는 항상 []. 그래서 이 스키마를 재사용하는
    #   FullReceiptSchema(영수증 조회)에서는 언제나 []이며, 매핑 유무의 진실이 아니다
    #   (그쪽 진실은 `GET /api/admin/product-voucher-grants`).
    voucher_ticket_list: List[VoucherTicketSchema] = Field(default_factory=list)

    class Config:
        from_attributes = True


class PriceSchema(BaseSchema):
    store: Store
    currency: str
    price: float

    class Config:
        from_attributes = True


class FungibleAssetValueSchema(BaseSchema):
    ticker: str
    amount: float

    @model_validator(mode="after")
    def make_ticker_to_name(self):
        self.ticker = self.ticker.split("__")[-1]
        return self

    class Config:
        from_attributes = True


class FungibleItemSchema(BaseSchema):
    sheet_item_id: int
    fungible_item_id: str
    amount: int

    class Config:
        from_attributes = True


class GachaEntrySchema(BaseSchema):
    """
    (PLD-1562) 뽑기 풀 한 칸의 **공개** 표현 — 확률 공시용.

    `rate` 를 서버가 계산해 실어 보낸다. 클라가 weight/Σweight 를 직접 나누게 하면 공시
    값이 구현마다 갈리고(반올림·부동소수), 무엇보다 **화면에 뜬 확률과 서버가 뽑는 확률이
    다를 수 있는 자리**가 생긴다. 같은 수를 한 곳에서만 만든다.

    ⚠️ `weight` 도 같이 낸다. rate 는 반올림된 표시값이라 감사에 못 쓰고, 공시 분쟁에서
       필요한 건 원본 가중치다(주문에 동결되는 스냅샷도 weight 를 남긴다).
    """

    entry_id: int
    name: str
    weight: int
    #: weight / Σweight (10자리 반올림 — 6자리면 큰 풀에서 희귀 칸이 0.0 이 된다).
    rate: float
    #: 'ITEM' | 'FAV'. 화면이 아이콘 소스를 가르는 축이기도 하다(아이템=sheet id, FAV=티커).
    kind: str
    #: 온체인 티커. `Item_NT_400000` / `FAV__RUNESTONE_HP`.
    ticker: str
    #: FAV 자릿수. 아이템은 0.
    decimal_places: int = 0
    #: 아이템 아이콘용. **FAV 는 null** 이다.
    sheet_item_id: Optional[int] = None
    amount: int

    class Config:
        from_attributes = True


class ProductSchema(SimpleProductSchema):
    id: int
    purchase_count: int = 0
    rarity: ProductRarity
    size: ProductAssetUISize
    discount: int = 0
    l10n_key: str
    path: str
    bg_path: Optional[str] = None
    popup_path_key: Optional[str] = None
    open_timestamp: Optional[datetime] = None
    close_timestamp: Optional[datetime] = None

    fav_list: List[FungibleAssetValueSchema]
    fungible_item_list: List[FungibleItemSchema]

    # (PLD-1562) 뽑기 풀. **빈 리스트 = 뽑기가 아니다**(하위호환 — 필드를 모르는 구버전
    #   클라와 고정 상품이 같은 모양이다). 채우는 주체는 상품 조회 API 뿐이다
    #   (ORM 관계명이 gacha_entry_list 로 달라 model_validate 만으로는 항상 []).
    gacha_pool: List[GachaEntrySchema] = Field(default_factory=list)
    #: (PLD-1562) 한 번 구매가 돌리는 추첨 횟수. 1=단연, 10=10연.
    #:   확률(`gacha_pool[].rate`)은 **회차당**이다 — 10연이라고 확률이 바뀌지 않는다.
    gacha_draw_count: int = 1

    price_list: List[PriceSchema]

    @model_validator(mode="after")
    def default_values(self):
        if self.bg_path is None:
            self.bg_path = (
                f"shop/images/product/list/bg_{self.rarity.value}_{self.size.value}.png"
            )

        if self.popup_path_key is None:
            self.popup_path_key = f"{self.l10n_key}_PATH"
        # Needs to return self
        return self


# (PLD-1575) `AdminProductSchema` 의 설계 근거. docstring 이 아니라 주석에 둔다 — 응답 모델의
#   docstring 은 공개 `openapi.json` 의 스키마 description 으로 나간다.
#
# **유저용 `ProductSchema` 에 필드를 직접 넣지 않는 이유**: 그건 게임 클라·현금 웹샵·포탈이 받는
#   유저용 응답 스키마다(`GET /api/product`). 필드를 늘리면 그대로 클라 계약이 바뀌고, "이 상품을
#   영수증 없이 무상 발행할 수 있나"는 유저가 알 필요 없는 내부 정보다.
# 반대로 백오피스 상품 목록(`GET /admin/products`)에는 **있어야** 한다. 없으면 포인트 전용 상품을
#   구분할 방법이 `GET /admin/point-shop-products`(켜진 것만 나오는 감사용 별도 목록)뿐이라,
#   상품 목록 화면에서는 눈에 보이지 않는다.
#   ⚠️ 이건 **서버 선행 작업**이다. 백오피스(9c-backoffice) 의 `ProductResponse` DTO 에 대응
#      필드가 없고 역직렬화가 모르는 멤버를 조용히 버리므로, 이 변경만으로 화면이 바뀌지는
#      않는다(하위호환은 안전). DTO·UI 추가는 후속 티켓.
class AdminProductSchema(ProductSchema):
    """백오피스 전용 상품 스키마 = 유저용 `ProductSchema` + 운영 플래그."""

    # ORM Product 에 컬럼이 있으므로 `model_validate(product)` 로 채워진다. 기본값 False 는
    #   컬럼 없는 객체를 검증할 때의 fail-safe — 화이트리스트 밖이 안전한 쪽이다.
    point_shop_grantable: bool = False


class CategorySchema(BaseSchema):
    name: str
    order: int
    active: bool
    l10n_key: str
    path: str
    product_list: List[ProductSchema]

    class Config:
        from_attributes = True
