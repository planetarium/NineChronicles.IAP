from typing import Dict, Union, List

import bencodex

from common.lib9c.currency import Currency


class FungibleAsset():

    @staticmethod
    def to_fungible_asset(ticker: str, amount: int, decimalPlaces: int) -> List[Union[Dict[str, Union[str, int, None]], int]]:
        return [Currency.to_currency(ticker), amount * 10 ** decimalPlaces]

    @staticmethod
    def serialize(fungible_asset: List[Union[Dict[str, Union[str, int, None]], int]]) -> bytes:
        return bencodex.dumps([Currency.serialize(fungible_asset[0]), fungible_asset[1]])
