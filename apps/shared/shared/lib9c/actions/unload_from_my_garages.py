from typing import List, Dict, Union, Optional

from shared.lib9c.actions import ActionBase
from shared.lib9c.models.address import Address
from shared.lib9c.models.fungible_asset_value import FungibleAssetValue


class UnloadFromMyGarages(ActionBase):
    """
    Python port of "UnloadFromMyGarages" action from lib9c

    - type_id: `unload_from_my_garages`
    - values:
      - avatar_addr: Recipient address
      - fav_data: List of Dict[str, Address|FungibleAssetValue]
        - valid keys: ["balanceAddr", "value"]
      - item_data: List of Dict[str, str|int]
        - valid keys: ["fungibleId", "count"]
      - memo: Json serialized string
    """

    TYPE_ID: str = "unload_from_my_garages"

    def __init__(
        self,
        *,
        avatar_addr: Address,
        fav_data: List[Dict[str, Union[Address, FungibleAssetValue]]] = None,
        item_data: List[Dict[str, str | int]] = None,
        memo: Optional[str] = None,
        _id: Optional[str] = None
    ):
        super().__init__(self.TYPE_ID, _id)
        self._avatar_addr: Address = avatar_addr
        self._fav_data = fav_data or []
        self._item_data = item_data or []
        self._memo = memo

    @property
    def _plain_value(self):
        return {
            "id": bytes.fromhex(self._id),
            "l": [
                bytes.fromhex(self._avatar_addr.short_format),
                (
                    [
                        [
                            bytes.fromhex(x["balanceAddr"].short_format),
                            x["value"].plain_value,
                        ]
                        for x in self._fav_data
                    ]
                    if self._fav_data
                    else None
                ),
                (
                    [
                        [bytes.fromhex(x["fungibleId"]), x["count"]]
                        for x in self._item_data
                    ]
                    if self._item_data
                    else None
                ),
                self._memo,
            ],
        }
