from __future__ import annotations

from typing import Dict, List, Optional, Any

import bencodex

from shared.lib9c.models.address import Address


class Currency:
    """
    # Currency
    ---
    Lib9c Currency model which has ticker, minters, decimal_places, total_supply_trackable.
    `minters` will be automatically sanitized to `None` if empty list provided.
    """

    def __init__(
        self,
        ticker: str,
        decimal_places: int,
        minters: Optional[List[str]] = None,
        total_supply_trackable: bool = False,
    ):
        self.ticker = ticker
        self.minters = [Address(x) for x in minters] if minters else None
        self.decimal_places = decimal_places
        self.total_supply_trackable = total_supply_trackable

    def __eq__(self, other: Currency):
        return (
            self.ticker == other.ticker
            and self.minters == other.minters
            and self.decimal_places == other.decimal_places
            and self.total_supply_trackable == other.total_supply_trackable
        )

    @classmethod
    def NCG(cls):
        return cls(
            ticker="NCG",
            minters=["47d082a115c63e7b58b1532d20e631538eafadde"],
            decimal_places=2,
        )

    @classmethod
    def CRYSTAL(cls):
        return cls(ticker="CRYSTAL", minters=None, decimal_places=18)

    @property
    def plain_value(self) -> Dict[str, Any]:
        value = {
            "ticker": self.ticker,
            "decimalPlaces": chr(self.decimal_places).encode(),
            "minters": [x.raw for x in self.minters] if self.minters else None,
        }
        if self.total_supply_trackable:
            value["totalSupplyTrackable"] = True
        return value

    @property
    def serialized_plain_value(self) -> bytes:
        return bencodex.dumps(self.plain_value)
