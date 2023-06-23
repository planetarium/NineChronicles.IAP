from typing import Optional, List

from pydantic import BaseModel as BaseSchema

from common.enums import ProductType, Currency


class FungibleAssetValueSchema(BaseSchema):
    ticker: Currency
    amount: float

    class Config:
        orm_mode = True


class FungibleItemSchema(BaseSchema):
    item_id: int
    # fungible_id: str
    amount: int

    class Config:
        orm_mode = True


class ProductSchema(BaseSchema):
    google_sku: str
    # apple_sku: str
    product_type: ProductType
    daily_limit: Optional[int] = None
    weekly_limit: Optional[int] = None
    display_order: int
    active: bool

    fav_list: List[FungibleAssetValueSchema]
    item_list: List[FungibleItemSchema]

    class Config:
        orm_mode = True
