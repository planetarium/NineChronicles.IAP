import json

import pytest

from common.lib9c.actions.claim_items import ClaimItems
from common.lib9c.models.address import Address
from common.lib9c.models.fungible_asset_value import FungibleAssetValue

TEST_DATA = [
    (
        {
            "claim_data": [{
                "avatarAddress": Address("0b3729eedb2ee3a0424fdb6a810f8d4b98582272"),
                "fungibleAssetValues": [
                    FungibleAssetValue.from_raw_data("Item_NT_400000", 0, amount=300),
                    FungibleAssetValue.from_raw_data("Item_NT_500000", 0, amount=10),
                    FungibleAssetValue.from_raw_data("Item_NT_600201", 0, amount=20),
                ]
            }],
            "memo": json.dumps({"season_pass": {"n": [23], "p": [23], "t": "claim"}})
        },
        {
            'cd': [[
                b'\x0b7)\xee\xdb.\xe3\xa0BO\xdbj\x81\x0f\x8dK\x98X"r',
                [[{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_400000'}, 300],
                 [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_500000'}, 10],
                 [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_600201'}, 20], ]
            ]],
            'm': '{"season_pass": {"n": [23], "p": [23], "t": "claim"}}'
        }
    ),
    (
        {
            "claim_data": [
                {
                    "avatarAddress": Address("cc3dae35aa2f1b053da05204d05cbb4c20fdbe74"),
                    "fungibleAssetValues": [
                        FungibleAssetValue.from_raw_data("Item_NT_800201", 0, amount=18),
                        FungibleAssetValue.from_raw_data("FAV__CRYSTAL", 18, amount=7500),
                        FungibleAssetValue.from_raw_data("Item_NT_600201", 0, amount=1),
                        FungibleAssetValue.from_raw_data("Item_NT_500000", 0, amount=1),
                    ]
                }
            ],
            "memo": 'patrol reward Cc3daE35aA2F1b053Da05204d05CBb4C20Fdbe74 / 123'
        },
        {
            'cd': [[
                b'\xcc=\xae5\xaa/\x1b\x05=\xa0R\x04\xd0\\\xbbL \xfd\xbet',
                [[{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_800201'}, 18],
                 [{'decimalPlaces': b'\x12', 'minters': None, 'ticker': 'FAV__CRYSTAL'}, 7500000000000000000000],
                 [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_600201'}, 1],
                 [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_500000'}, 1]]
            ]],
            'm': 'patrol reward Cc3daE35aA2F1b053Da05204d05CBb4C20Fdbe74 / 123'
        }
    ),
    (
        {
            "claim_data": [{
                "avatarAddress": Address("0ddfcca4467555376ed66e8079f9881490d67e81"),
                "fungibleAssetValues": [
                    FungibleAssetValue.from_raw_data("Item_NT_400000", 0, amount=6000),
                    FungibleAssetValue.from_raw_data("Item_NT_500000", 0, amount=30),
                    FungibleAssetValue.from_raw_data("Item_NT_600201", 0, amount=400),
                    FungibleAssetValue.from_raw_data("Item_NT_49900013", 0, amount=1),
                    FungibleAssetValue.from_raw_data("FAV__CRYSTAL", 18, amount=5000000),
                ],
            }],
            "memo": json.dumps({"season_pass": {"n": [], "p": [], "t": "claim"}})
        },
        {
            'cd': [[
                b'\r\xdf\xcc\xa4FuU7n\xd6n\x80y\xf9\x88\x14\x90\xd6~\x81',
                [[{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_400000'}, 6000],
                 [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_500000'}, 30],
                 [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_600201'}, 400],
                 [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_49900013'}, 1],
                 [{'decimalPlaces': b'\x12', 'minters': None, 'ticker': 'FAV__CRYSTAL'}, 5000000000000000000000000]]
            ]],
            'm': '{"season_pass": {"n": [], "p": [], "t": "claim"}}'
        }
    )
]


@pytest.mark.parametrize("test_data", TEST_DATA)
def test_claim_items(test_data):
    data, expected = test_data
    action = ClaimItems(**data)
    plain_value = action.plain_value
    values = plain_value["values"]

    assert plain_value["type_id"] == "claim_items"
    assert "cd" in values
    assert "m" in values
    del values["id"]
    assert values == expected
