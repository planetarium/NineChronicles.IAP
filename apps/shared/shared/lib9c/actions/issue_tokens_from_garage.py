from typing import List, Optional

from shared.lib9c.actions import ActionBase
from shared.lib9c.models.fungible_asset_value import FungibleAssetValue


class FavIssueSpec:
    def __init__(self, fav: FungibleAssetValue):
        self._fav = fav

    @property
    def plain_value(self):
        return [self._fav.plain_value, None]  # No Item spec


class ItemIssueSpec:
    def __init__(self, fungible_item_id: [str | bytes], amount: int):
        self.item_id = (
            fungible_item_id
            if isinstance(fungible_item_id, bytes)
            else bytes.fromhex(fungible_item_id)
        )
        self.amount = amount

    @property
    def plain_value(self):
        return [None, [self.item_id, self.amount]]  # No FAV spec


class IssueTokensFromGarage(ActionBase):
    """
    Python port of `IssueTokensFromGarage` action from lib9c

    - type_id: `issue_tokens_from_garage`
    - values: List[spec]
      - spec: List[FavIssueSpec | ItemIssueSpec]
    """

    TYPE_ID: str = "issue_tokens_from_garage"

    def __init__(
        self, *, values: List[FavIssueSpec | ItemIssueSpec], _id: Optional[str] = None
    ):
        super().__init__(self.TYPE_ID, _id)
        self._values: List[FavIssueSpec | ItemIssueSpec] = values

    @property
    def _plain_value(self):
        return [x.plain_value for x in self._values] if self._values else None
