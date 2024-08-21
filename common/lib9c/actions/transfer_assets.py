from typing import List, Tuple, Optional

from common.lib9c.actions import ActionBase
from common.lib9c.models.address import Address
from common.lib9c.models.fungible_asset_value import FungibleAssetValue


class TransferAssets(ActionBase):
    """
    Python port of `TransferAssets` action from lib9c

    - type_id: `transfer_assets3`
    - values:
        - sender: Sender address
        - Recipients: List[Tuple[Addr, FAV]]
            - Addr: Recipient Address
            - FAV: FungibleAssetValue to send
        - memo: Optional message string to leave
    """
    TYPE_ID: str = "transfer_assets3"

    def __init__(self, *, sender: Address, recipients: List[Tuple[Address, FungibleAssetValue]],
                 memo: Optional[str] = None, _id: Optional[str] = None):
        super().__init__(self.TYPE_ID, _id)
        self._sender = sender
        self._recipients = recipients
        self._memo = memo

    @property
    def _plain_value(self):
        pv = {
            "sender": bytes.fromhex(self._sender.short_format),
            "recipients": [[bytes.fromhex(r[0].short_format), r[1].plain_value] for r in self._recipients]
        }
        if self._memo is not None:
            pv["memo"] = self._memo

        return pv
