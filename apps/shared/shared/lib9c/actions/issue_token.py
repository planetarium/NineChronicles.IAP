from typing import List, Optional

from shared.lib9c.actions import ActionBase
from shared.lib9c.models.address import Address
from shared.lib9c.models.fungible_asset_value import FungibleAssetValue


class ItemSpec:
    def __init__(self, item_id: int, amount: int, tradable: bool):
        self._item_id = item_id
        self._amount = amount
        self._tradable = tradable

    @property
    def plain_value(self):
        return [self._item_id, self._amount, self._tradable]


class IssueToken(ActionBase):
    TYPE_ID: str = "issue_token"

    def __init__(
        self,
        *,
        avatar_addr: Address,
        fav_list: List[FungibleAssetValue],
        item_list: List[ItemSpec],
        _id: Optional[str] = None
    ):
        super().__init__(self.TYPE_ID, _id)
        self._avatar_addr = avatar_addr
        self._fav_list = fav_list
        self._item_list = item_list

    @property
    def _plain_value(self):
        return {
            "a": bytes.fromhex(self._avatar_addr.short_format),
            "f": [x.plain_value for x in self._fav_list],
            "i": [x.plain_value for x in self._item_list],
        }
