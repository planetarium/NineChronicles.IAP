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


class CategorySchema(BaseSchema):
    name: str
    order: int
    active: bool
    l10n_key: str
    path: str
    product_list: List[ProductSchema]

    class Config:
        from_attributes = True
