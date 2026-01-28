from typing import Dict, List, Optional

from shared.lib9c.actions import ActionBase
from shared.lib9c.models.address import Address
from shared.lib9c.models.fungible_asset_value import FungibleAssetValue


class GrantItems(ActionBase):
    """
    Python port of `GrantItems` action from lib9c (PR #3257).

    - type_id : `grant_items`
    - values: List[grant_data]
      - claimData: List[claimItem]
        - claimItem: Dict[str, Address|List[FungibleAssetValue]]
          - valid keys: ["avatarAddress", "fungibleAssetValues"]
      - memo: optional string

    NOTE:
    - Unlike `ClaimItems`, `GrantItems` does NOT include an `id` field in values.
    """

    TYPE_ID: str = "grant_items"

    def __init__(
        self,
        *,
        claim_data: List[Dict[str, Address | List[FungibleAssetValue]]],
        memo: Optional[str] = None,
        _id: Optional[str] = None,
    ):
        super().__init__(self.TYPE_ID, _id)
        self._claim_data = claim_data
        self._memo = memo

    @property
    def _plain_value(self):
        pv = {
            "cd": [
                [
                    cd["avatarAddress"].raw,
                    [x.plain_value for x in cd["fungibleAssetValues"]],
                ]
                for cd in self._claim_data
            ],
        }
        if self._memo is not None and self._memo != "":
            pv["m"] = self._memo
        return pv
