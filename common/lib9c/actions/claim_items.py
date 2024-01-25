from typing import Dict, List, Optional

from common.lib9c.actions import ActionBase
from common.lib9c.models.address import Address
from common.lib9c.models.fungible_asset_value import FungibleAssetValue


class ClaimItems(ActionBase):
    """
    Python port of `ClaimItems` action from lib9c

    - type_id : `claim_items`
    - values: List[claim_data]
      - claimData: List[claimItem]
        - claimItem: Dict[str, Address|List[FungibleAssetValue]]
         - valid keys: ["avatarAddress", "fungibleAssetValues"]
      - memo: JSON serialized string
    """

    def __init__(self, *, claim_data: List[Dict[str, Address | List[FungibleAssetValue]]], memo: Optional[str] = None):
        super().__init__("claim_items")
        self._claim_data = claim_data
        self._memo = memo

    @property
    def _plain_value(self):
        return {
            "id": bytes.fromhex(self._id),
            "cd": [
                [
                    cd["avatarAddress"].raw,
                    [x.plain_value for x in cd["fungibleAssetValues"]],
                ] for cd in self._claim_data
            ],
            "m": self._memo
        }
