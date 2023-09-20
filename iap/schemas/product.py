from typing import Optional, List

from pydantic import BaseModel as BaseSchema

from common.enums import Currency


class SimpleProductSchema(BaseSchema):
    name: str
    order: int
    google_sku: str
    # apple_sku: str
    # product_type: ProductType
    daily_limit: Optional[int] = None
    weekly_limit: Optional[int] = None
    account_limit: Optional[int] = None
    active: bool
    buyable: bool = True

    class Config:
        from_attributes = True


class PriceSchema(BaseSchema):
    currency: str
    price: float

    class Config:
        from_attributes = True


class FungibleAssetValueSchema(BaseSchema):
    ticker: Currency
    amount: float

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

    fav_list: List[FungibleAssetValueSchema]
    fungible_item_list: List[FungibleItemSchema]
    # price_list: List[PriceSchema]


class CategorySchema(BaseSchema):
    name: str
    order: int
    active: bool
    product_list: List[ProductSchema]

    class Config:
        from_attributes = True
