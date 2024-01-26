from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional, Any

import bencodex

from common.lib9c.models.currency import Currency


class FungibleAssetValue:
    def __init__(self, currency: Currency, amount: Decimal):
        self.currency = currency
        self.amount = amount

    def __eq__(self, other: FungibleAssetValue):
        return self.currency == other.currency and self.amount == other.amount

    @classmethod
    def from_raw_data(
            cls,
            ticker: str, decimal_places: int, minters: Optional[List[str]] = None, total_supply_trackable: bool = False,
            amount: Decimal = Decimal('0')
    ):
        return cls(
            Currency(ticker, decimal_places, minters, total_supply_trackable),
            amount=amount
        )

    @property
    def plain_value(self) -> List[Dict[str, Any] | int]:
        return [self.currency.plain_value, int(self.amount * max(1, 10 ** self.currency.decimal_places))]

    @property
    def serialized_plain_value(self) -> bytes:
        return bencodex.dumps(self.plain_value)
