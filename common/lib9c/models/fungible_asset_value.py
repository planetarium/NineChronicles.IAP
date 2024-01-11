from __future__ import annotations

from typing import Dict, Union, List, Optional, Any

import bencodex

from common.lib9c.models.currency import Currency


class FungibleAssetValue:
    def __init__(self, currency: Currency, amount: float):
        self.currency = currency
        self.amount = amount

    def __eq__(self, other: FungibleAssetValue):
        return self.currency == other.currency and self.amount == other.amount

    @classmethod
    def from_raw_data(
            cls,
            ticker: str, decimal_places: int, minters: Optional[List[str]] = None, total_supply_trackable: bool = False,
            amount: float = 0
    ):
        return cls(
            Currency(ticker, decimal_places, minters, total_supply_trackable),
            amount=amount
        )

    @property
    def plain_value(self) -> List[Dict[str, Any] | float]:
        return [self.currency.plain_value, self.amount * max(1, 10 ** self.currency.decimal_places)]

    @property
    def serialized_plain_value(self) -> bytes:
        return bencodex.dumps(self.plain_value)

    @staticmethod
    def to_fungible_asset(ticker: str, amount: int, decimal_places: int) \
            -> List[Union[Dict[str, Union[str, int, None]], int]]:
        return [Currency.to_currency_plain_value(ticker), amount * max(1, 10 ** decimal_places)]

    @staticmethod
    def serialize(fungible_asset: List[Union[Dict[str, Union[str, int, None]], int]]) -> bytes:
        return bencodex.dumps([Currency.serialize(fungible_asset[0]), fungible_asset[1]])
