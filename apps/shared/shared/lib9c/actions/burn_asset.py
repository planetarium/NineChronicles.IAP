from typing import Optional

from shared.lib9c.actions import ActionBase
from shared.lib9c.models.address import Address
from shared.lib9c.models.fungible_asset_value import FungibleAssetValue


class BurnAsset(ActionBase):
    TYPE_ID: str = "burn_asset"

    def __init__(
        self,
        *,
        owner: Address,
        amount: FungibleAssetValue,
        memo: str,
        _id: Optional[str] = None
    ):
        super().__init__(self.TYPE_ID, _id)
        self._owner = owner
        self._amount = amount
        self._memo = memo

    @property
    def _plain_value(self):
        return [
            bytes.fromhex(self._owner.short_format),
            self._amount.plain_value,
            self._memo,
        ]
