import json
from decimal import Decimal

import bencodex
import pytest

from shared.lib9c.actions.grant_items import GrantItems
from shared.lib9c.models.address import Address
from shared.lib9c.models.fungible_asset_value import FungibleAssetValue

TEST_ID = "0d0d9e0cbc1b11eeb0dc6fd71476142a"

TEST_DATA = [
    (
        {
            "_id": TEST_ID,
            "claim_data": [{
                "avatarAddress": Address("0b3729eedb2ee3a0424fdb6a810f8d4b98582272"),
                "fungibleAssetValues": [
                    FungibleAssetValue.from_raw_data("Item_NT_400000", 0, amount=Decimal("300")),
                    FungibleAssetValue.from_raw_data("Item_NT_500000", 0, amount=Decimal("10")),
                    FungibleAssetValue.from_raw_data("Item_NT_600201", 0, amount=Decimal("20")),
                ]
            }],
            "memo": json.dumps({"season_pass": {"n": [23], "p": [23], "t": "claim"}})
        },
        {
            "cd": [[
                b'\x0b7)\xee\xdb.\xe3\xa0BO\xdbj\x81\x0f\x8dK\x98X"r',
                [
                    [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_400000'}, 300],
                    [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_500000'}, 10],
                    [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_600201'}, 20],
                ],
            ]],
            "m": '{"season_pass": {"n": [23], "p": [23], "t": "claim"}}',
        },
    ),
    (
        {
            "_id": TEST_ID,
            "claim_data": [
                {
                    "avatarAddress": Address("cc3dae35aa2f1b053da05204d05cbb4c20fdbe74"),
                    "fungibleAssetValues": [
                        FungibleAssetValue.from_raw_data("Item_NT_800201", 0, amount=Decimal("18")),
                        FungibleAssetValue.from_raw_data("FAV__CRYSTAL", 18, amount=Decimal("7500")),
                        FungibleAssetValue.from_raw_data("Item_NT_600201", 0, amount=Decimal("1")),
                        FungibleAssetValue.from_raw_data("Item_NT_500000", 0, amount=Decimal("1")),
                    ]
                }
            ],
            "memo": 'patrol reward Cc3daE35aA2F1b053Da05204d05CBb4C20Fdbe74 / 123'
        },
        {
            "cd": [[
                b'\xcc=\xae5\xaa/\x1b\x05=\xa0R\x04\xd0\\\xbbL \xfd\xbet',
                [
                    [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_800201'}, 18],
                    [{'decimalPlaces': b'\x12', 'minters': None, 'ticker': 'FAV__CRYSTAL'}, 7500000000000000000000],
                    [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_600201'}, 1],
                    [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_500000'}, 1],
                ],
            ]],
            "m": 'patrol reward Cc3daE35aA2F1b053Da05204d05CBb4C20Fdbe74 / 123',
        },
    ),
]


@pytest.mark.parametrize("test_data", TEST_DATA)
def test_grant_items_plain_value(test_data):
    data, expected_values_without_id = test_data
    action = GrantItems(**data)
    plain_value = action.plain_value
    values = plain_value["values"]

    assert plain_value["type_id"] == "grant_items"
    assert "id" in values
    assert values["id"] == bytes.fromhex(TEST_ID)

    # Compare other fields
    del values["id"]
    assert values == expected_values_without_id


@pytest.mark.parametrize("test_data", TEST_DATA)
def test_grant_items_serialized_plain_value(test_data):
    data, _ = test_data
    action = GrantItems(**data)
    # `serialized_plain_value` should be bencodex encoding of `plain_value`.
    assert action.serialized_plain_value == bencodex.dumps(action.plain_value)
