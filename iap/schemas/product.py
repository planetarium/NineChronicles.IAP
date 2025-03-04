from datetime import datetime
from typing import Optional, List

from pydantic import BaseModel as BaseSchema, model_validator

from common.enums import ProductRarity, ProductAssetUISize, ProductType


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

    class Config:
        from_attributes = True


class PriceSchema(BaseSchema):
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

    # price_list: List[PriceSchema]

    @model_validator(mode="after")
    def default_values(self):
        if self.bg_path is None:
            self.bg_path = f"shop/images/product/list/bg_{self.rarity.value}_{self.size.value}.png"

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
