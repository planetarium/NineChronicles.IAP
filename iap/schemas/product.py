from typing import Optional, List

from pydantic import BaseModel as BaseSchema

from common.enums import ProductType, Currency


class PriceSchema(BaseSchema):
    currency: str
    price: float

    class Config:
        orm_mode = True


class FungibleAssetValueSchema(BaseSchema):
    ticker: Currency
    amount: float

    class Config:
        orm_mode = True


class FungibleItemSchema(BaseSchema):
    sheet_item_id: int
    fungible_item_id: str
    amount: int

    class Config:
        orm_mode = True


class ProductSchema(BaseSchema):
    google_sku: str
    # apple_sku: str
    product_type: ProductType
    daily_limit: Optional[int] = None
    weekly_limit: Optional[int] = None
    purchase_count: int = 0
    display_order: int
    active: bool
    buyable: bool = True

    fav_list: List[FungibleAssetValueSchema]
    fungible_item_list: List[FungibleItemSchema]
    price_list: List[PriceSchema]

    class Config:
        orm_mode = True
