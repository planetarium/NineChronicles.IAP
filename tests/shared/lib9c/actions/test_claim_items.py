import json
from decimal import Decimal

import pytest

from shared.lib9c.actions.claim_items import ClaimItems
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
            'cd': [[
                b'\x0b7)\xee\xdb.\xe3\xa0BO\xdbj\x81\x0f\x8dK\x98X"r',
                [[{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_400000'}, 300],
                 [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_500000'}, 10],
                 [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_600201'}, 20], ]
            ]],
            'm': '{"season_pass": {"n": [23], "p": [23], "t": "claim"}}'
        },
        b'du7:type_idu11:claim_itemsu6:valuesdu2:cdll20:\x0b7)\xee\xdb.\xe3\xa0BO\xdbj\x81\x0f\x8dK\x98X"rlldu13:decimalPlaces1:\x00u7:mintersnu6:tickeru14:Item_NT_400000ei300eeldu13:decimalPlaces1:\x00u7:mintersnu6:tickeru14:Item_NT_500000ei10eeldu13:decimalPlaces1:\x00u7:mintersnu6:tickeru14:Item_NT_600201ei20eeeeeu2:id16:\r\r\x9e\x0c\xbc\x1b\x11\xee\xb0\xdco\xd7\x14v\x14*u1:mu53:{"season_pass": {"n": [23], "p": [23], "t": "claim"}}ee'
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
            'cd': [[
                b'\xcc=\xae5\xaa/\x1b\x05=\xa0R\x04\xd0\\\xbbL \xfd\xbet',
                [[{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_800201'}, 18],
                 [{'decimalPlaces': b'\x12', 'minters': None, 'ticker': 'FAV__CRYSTAL'}, 7500000000000000000000],
                 [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_600201'}, 1],
                 [{'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'Item_NT_500000'}, 1]]
            ]],
            'm': 'patrol reward Cc3daE35aA2F1b053Da05204d05CBb4C20Fdbe74 / 123'
        },
        b'du7:type_idu11:claim_itemsu6:valuesdu2:cdll20:\xcc=\xae5\xaa/\x1b\x05=\xa0R\x04\xd0\\\xbbL \xfd\xbetlldu13:decimalPlaces1:\x00u7:mintersnu6:tickeru14:Item_NT_800201ei18eeldu13:decimalPlaces1:\x12u7:mintersnu6:tickeru12:FAV__CRYSTALei7500000000000000000000eeldu13:decimalPlaces1:\x00u7:mintersnu6:tickeru14:Item_NT_600201ei1eeldu13:decimalPlaces1:\x00u7:mintersnu6:tickeru14:Item_NT_500000ei1eeeeeu2:id16:\r\r\x9e\x0c\xbc\x1b\x11\xee\xb0\xdco\xd7\x14v\x14*u1:mu60:patrol reward Cc3daE35aA2F1b053Da05204d05CBb4C20Fdbe74 / 123ee'
    ),
    (
        {
            "_id": TEST_ID,
            "claim_data": [{
                "avatarAddress": Address("0ddfcca4467555376ed66e8079f9881490d67e81"),
                "fungibleAssetValues": [
                    FungibleAssetValue.from_raw_data("Item_NT_400000", 0, amount=Decimal("6000")),
                    FungibleAssetValue.from_raw_data("Item_NT_500000", 0, amount=Decimal("30")),
                    FungibleAssetValue.from_raw_data("Item_NT_600201", 0, amount=Decimal("400")),
                    FungibleAssetValue.from_raw_data("Item_NT_49900013", 0, amount=Decimal("1")),
                    FungibleAssetValue.from_raw_data("FAV__CRYSTAL", 18, amount=Decimal("5000000")),
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
        },
        b'du7:type_idu11:claim_itemsu6:valuesdu2:cdll20:\r\xdf\xcc\xa4FuU7n\xd6n\x80y\xf9\x88\x14\x90\xd6~\x81lldu13:decimalPlaces1:\x00u7:mintersnu6:tickeru14:Item_NT_400000ei6000eeldu13:decimalPlaces1:\x00u7:mintersnu6:tickeru14:Item_NT_500000ei30eeldu13:decimalPlaces1:\x00u7:mintersnu6:tickeru14:Item_NT_600201ei400eeldu13:decimalPlaces1:\x00u7:mintersnu6:tickeru16:Item_NT_49900013ei1eeldu13:decimalPlaces1:\x12u7:mintersnu6:tickeru12:FAV__CRYSTALei5000000000000000000000000eeeeeu2:id16:\r\r\x9e\x0c\xbc\x1b\x11\xee\xb0\xdco\xd7\x14v\x14*u1:mu49:{"season_pass": {"n": [], "p": [], "t": "claim"}}ee'
    )
]


@pytest.mark.parametrize("test_data", TEST_DATA)
def test_claim_items(test_data):
    data, expected, _ = test_data
    action = ClaimItems(**data)
    plain_value = action.plain_value
    values = plain_value["values"]

    assert plain_value["type_id"] == "claim_items"
    assert "cd" in values
    assert "m" in values
    del values["id"]
    assert values == expected


@pytest.mark.parametrize("test_data", TEST_DATA)
def test_serialized_plain_value(test_data):
    data, _, expected = test_data
    action = ClaimItems(**data)
    print(action.serialized_plain_value)
    assert action.serialized_plain_value == expected
