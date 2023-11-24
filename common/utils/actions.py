import bencodex
from bencodex import BValue

from typing import List, Optional

from common.lib9c.fungible_asset import FungibleAsset


def create_unload_my_garages_action_plain_value(id: str, fav_data: List, avatar_addr: str, item_data: List, memo: Optional[str]) -> BValue:
    if avatar_addr.startswith("0x"):
        avatar_addr = avatar_addr[2:]
    return bencodex.dumps({
        'type_id': 'unload_from_my_garages',
        'values': {
            'id': bytes.fromhex(id),
            "l": [
                bytes.fromhex(avatar_addr),
                [
                    [
                        bytes.fromhex(x['balanceAddr']),
                        FungibleAsset.to_fungible_asset(x['value']['currencyTicker'], x['value']['value'])
                    ]
                    for x in fav_data
                ],
                [
                    [
                        bytes.fromhex(x['fungibleId']),
                        x['count']
                    ]
                    for x in item_data
                ],
                memo if memo else None,
            ]
        }
    })
