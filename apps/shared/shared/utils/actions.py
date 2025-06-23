from typing import List, Optional, Dict, Any

from shared.lib9c.models.fungible_asset_value import FungibleAssetValue


def create_unload_my_garages_action_plain_value(
    _id: str, fav_data: List, avatar_addr: str, item_data: List, memo: Optional[str]
) -> Dict[str, Any]:
    if avatar_addr.startswith("0x"):
        avatar_addr = avatar_addr[2:]
    return {
        "type_id": "unload_from_my_garages",
        "values": {
            "id": bytes.fromhex(_id),
            "l": [
                bytes.fromhex(avatar_addr),
                [
                    [
                        bytes.fromhex(
                            x["balanceAddr"][2:]
                            if x["balanceAddr"].startswith("0x")
                            else x["balanceAddr"]
                        ),
                        FungibleAssetValue.from_raw_data(
                            x["value"]["currencyTicker"],
                            x["value"]["decimalPlaces"],
                            x["value"].get("minters", None),
                            amount=x["value"]["value"],
                        ).plain_value,
                    ]
                    for x in fav_data
                ],
                [[bytes.fromhex(x["fungibleId"]), x["count"]] for x in item_data],
                memo if memo else None,
            ],
        },
    }
