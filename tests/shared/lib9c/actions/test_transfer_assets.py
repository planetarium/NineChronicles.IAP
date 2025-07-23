from decimal import Decimal

import pytest

from shared.lib9c.actions.transfer_assets import TransferAssets
from shared.lib9c.models.address import Address
from shared.lib9c.models.fungible_asset_value import FungibleAssetValue

TEST_SENDER_ADDRESS = "0xDbF4c6d0D7C74D390fADae680f2144D885c878df"
TEST_RECIPIENT_ADDRESS_1 = "0x49D5FcEB955800B2c532D6319E803c7D80f817Af"
TEST_RECIPIENT_ADDRESS_2 = "0xcfcd6565287314ff70e4c4cf309db701c43ea5bd"

ACTION_TEST_DATA = [
    (
        {
            "sender": Address(TEST_SENDER_ADDRESS),
            "recipients": [
                [
                    Address(TEST_RECIPIENT_ADDRESS_1),
                    FungibleAssetValue.from_raw_data("FAV__CRYSTAL", 18, amount=Decimal("1000"))
                ]
            ]
        },
        {
            "sender": bytes.fromhex(TEST_SENDER_ADDRESS[2:]),
            "recipients": [
                [
                    bytes.fromhex(TEST_RECIPIENT_ADDRESS_1[2:]),
                    [{"decimalPlaces": b'\x12', "minters": None, "ticker": "FAV__CRYSTAL"}, 1000000000000000000000]
                ]
            ]
        }
    ),
    (
        {
            "sender": Address(TEST_SENDER_ADDRESS),
            "recipients": [
                [
                    Address(TEST_RECIPIENT_ADDRESS_1),
                    FungibleAssetValue.from_raw_data("FAV__CRYSTAL", 18, amount=Decimal("1000"))
                ]
            ],
            "memo": "memo"
        },
        {
            "sender": bytes.fromhex(TEST_SENDER_ADDRESS[2:]),
            "recipients": [
                [
                    bytes.fromhex(TEST_RECIPIENT_ADDRESS_1[2:]),
                    [{"decimalPlaces": b'\x12', "minters": None, "ticker": "FAV__CRYSTAL"}, 1000000000000000000000]
                ]
            ],
            "memo": "memo"
        }
    ),
    (
        {
            "sender": Address(TEST_SENDER_ADDRESS),
            "recipients": [
                [
                    Address(TEST_RECIPIENT_ADDRESS_1),
                    FungibleAssetValue.from_raw_data("FAV__CRYSTAL", 18, amount=Decimal("1000"))
                ],
                [
                    Address(TEST_RECIPIENT_ADDRESS_2),
                    FungibleAssetValue.from_raw_data("FAV__CRYSTAL", 18, amount=Decimal("2000"))
                ],
            ],
            "memo": "memo2"
        },
        {
            "sender": bytes.fromhex(TEST_SENDER_ADDRESS[2:]),
            "recipients": [
                [
                    bytes.fromhex(TEST_RECIPIENT_ADDRESS_1[2:]),
                    [{"decimalPlaces": b'\x12', "minters": None, "ticker": "FAV__CRYSTAL"}, 1000000000000000000000]
                ],
                [
                    bytes.fromhex(TEST_RECIPIENT_ADDRESS_2[2:]),
                    [{"decimalPlaces": b'\x12', "minters": None, "ticker": "FAV__CRYSTAL"}, 2000000000000000000000]
                ],
            ],
            "memo": "memo2"
        }
    ),
    (
        {
            "sender": Address(TEST_SENDER_ADDRESS),
            "recipients": [
                [
                    Address(TEST_RECIPIENT_ADDRESS_1),
                    FungibleAssetValue.from_raw_data("FAV__CRYSTAL", 18, amount=Decimal("1000"))
                ],
                [
                    Address(TEST_RECIPIENT_ADDRESS_2),
                    FungibleAssetValue.from_raw_data("FAV__RUNE_GOLDENLEAF", 0, amount=Decimal("20"))
                ],
            ],
            "memo": "memo3"
        },
        {
            "sender": bytes.fromhex(TEST_SENDER_ADDRESS[2:]),
            "recipients": [
                [
                    bytes.fromhex(TEST_RECIPIENT_ADDRESS_1[2:]),
                    [{"decimalPlaces": b'\x12', "minters": None, "ticker": "FAV__CRYSTAL"}, 1000000000000000000000]
                ],
                [
                    bytes.fromhex(TEST_RECIPIENT_ADDRESS_2[2:]),
                    [{"decimalPlaces": b'\x00', "minters": None, "ticker": "FAV__RUNE_GOLDENLEAF"}, 20]
                ],
            ],
            "memo": "memo3"
        }
    )
]


@pytest.mark.parametrize("test_data", ACTION_TEST_DATA)
def test_transfer_assets(test_data):
    data, expected = test_data
    action = TransferAssets(**data)
    plain_value = action.plain_value

    assert plain_value["type_id"] == "transfer_assets3"
    assert plain_value["values"] == expected
