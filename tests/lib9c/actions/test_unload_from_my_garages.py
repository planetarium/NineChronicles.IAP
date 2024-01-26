from decimal import Decimal

import pytest

from common.lib9c.actions.unload_from_my_garages import UnloadFromMyGarages
from common.lib9c.models.address import Address
from common.lib9c.models.currency import Currency
from common.lib9c.models.fungible_asset_value import FungibleAssetValue

TEST_AGENT_ADDR = "0xDbF4c6d0D7C74D390fADae680f2144D885c878df"
TEST_AVATAR_ADDR = "0x49D5FcEB955800B2c532D6319E803c7D80f817Af"

TEST_ID = "0f24f5e6bc1b11eeb0dc6fd71476142a"
TEST_DATA = [
    # One FAV
    (
        {
            "_id": TEST_ID,
            "avatar_addr": Address(TEST_AVATAR_ADDR),
            "fav_data": [{
                "balanceAddr": Address(TEST_AGENT_ADDR),
                "value": FungibleAssetValue.from_raw_data("CRYSTAL", 18, amount=Decimal("1"))
            }],
            "memo": "test_fav"
        },
        [
            bytes.fromhex(TEST_AVATAR_ADDR[2:]),
            [[
                bytes.fromhex(TEST_AGENT_ADDR[2:]),
                [{"decimalPlaces": b'\x12', "minters": None, "ticker": "CRYSTAL"}, 1000000000000000000]
            ]],
            None,
            "test_fav"
        ],
        b'du7:type_idu22:unload_from_my_garagesu6:valuesdu2:id16:\x0f$\xf5\xe6\xbc\x1b\x11\xee\xb0\xdco\xd7\x14v\x14*u1:ll20:I\xd5\xfc\xeb\x95X\x00\xb2\xc52\xd61\x9e\x80<}\x80\xf8\x17\xafll20:\xdb\xf4\xc6\xd0\xd7\xc7M9\x0f\xad\xaeh\x0f!D\xd8\x85\xc8x\xdfldu13:decimalPlaces1:\x12u7:mintersnu6:tickeru7:CRYSTALei1000000000000000000eeeenu8:test_faveee'
    ),
    # Multiple FAVs
    (
        {
            "_id": TEST_ID,
            "avatar_addr": Address(TEST_AVATAR_ADDR),
            "fav_data": [
                {
                    "balanceAddr": Address(TEST_AGENT_ADDR),
                    "value": FungibleAssetValue(Currency.CRYSTAL(), amount=Decimal("1"))
                },
                {
                    "balanceAddr": Address(TEST_AGENT_ADDR),
                    "value": FungibleAssetValue(Currency.NCG(), amount=Decimal("10"))
                },
            ],
            "memo": "test_favs"
        },
        [
            bytes.fromhex(TEST_AVATAR_ADDR[2:]),
            [
                [
                    bytes.fromhex(TEST_AGENT_ADDR[2:]),
                    [{"decimalPlaces": b'\x12', "minters": None, "ticker": "CRYSTAL"}, 1000000000000000000]
                ],
                [
                    bytes.fromhex(TEST_AGENT_ADDR[2:]),
                    [{"decimalPlaces": b'\x02', "minters": [bytes.fromhex("47d082a115c63e7b58b1532d20e631538eafadde")],
                      "ticker": "NCG"}, 1000]
                ]
            ],
            None,
            "test_favs"
        ],
        b'du7:type_idu22:unload_from_my_garagesu6:valuesdu2:id16:\x0f$\xf5\xe6\xbc\x1b\x11\xee\xb0\xdco\xd7\x14v\x14*u1:ll20:I\xd5\xfc\xeb\x95X\x00\xb2\xc52\xd61\x9e\x80<}\x80\xf8\x17\xafll20:\xdb\xf4\xc6\xd0\xd7\xc7M9\x0f\xad\xaeh\x0f!D\xd8\x85\xc8x\xdfldu13:decimalPlaces1:\x12u7:mintersnu6:tickeru7:CRYSTALei1000000000000000000eeel20:\xdb\xf4\xc6\xd0\xd7\xc7M9\x0f\xad\xaeh\x0f!D\xd8\x85\xc8x\xdfldu13:decimalPlaces1:\x02u7:mintersl20:G\xd0\x82\xa1\x15\xc6>{X\xb1S- \xe61S\x8e\xaf\xad\xdeeu6:tickeru3:NCGei1000eeeenu9:test_favseee'
    ),
    # Multiple FAVs with Avatar bound FAV
    (
        {
            "_id": TEST_ID,
            "avatar_addr": Address(TEST_AVATAR_ADDR),
            "fav_data": [
                {
                    "balanceAddr": Address(TEST_AGENT_ADDR),
                    "value": FungibleAssetValue.from_raw_data("CRYSTAL", 18, amount=Decimal("1"))
                },
                {
                    "balanceAddr": Address(TEST_AVATAR_ADDR),
                    "value": FungibleAssetValue.from_raw_data("RUNE_GOLDENLEAF", 0, amount=Decimal("10"))
                },
            ],
            "memo": "avatar_fav"
        },
        [
            bytes.fromhex(TEST_AVATAR_ADDR[2:]),
            [
                [
                    bytes.fromhex(TEST_AGENT_ADDR[2:]),
                    [{"decimalPlaces": b'\x12', "minters": None, "ticker": "CRYSTAL"}, 1000000000000000000]
                ],
                [
                    bytes.fromhex(TEST_AVATAR_ADDR[2:]),
                    [{"decimalPlaces": b'\x00', "minters": None, "ticker": "RUNE_GOLDENLEAF"}, 10]
                ]
            ],
            None,
            "avatar_fav"
        ],
        b'du7:type_idu22:unload_from_my_garagesu6:valuesdu2:id16:\x0f$\xf5\xe6\xbc\x1b\x11\xee\xb0\xdco\xd7\x14v\x14*u1:ll20:I\xd5\xfc\xeb\x95X\x00\xb2\xc52\xd61\x9e\x80<}\x80\xf8\x17\xafll20:\xdb\xf4\xc6\xd0\xd7\xc7M9\x0f\xad\xaeh\x0f!D\xd8\x85\xc8x\xdfldu13:decimalPlaces1:\x12u7:mintersnu6:tickeru7:CRYSTALei1000000000000000000eeel20:I\xd5\xfc\xeb\x95X\x00\xb2\xc52\xd61\x9e\x80<}\x80\xf8\x17\xafldu13:decimalPlaces1:\x00u7:mintersnu6:tickeru15:RUNE_GOLDENLEAFei10eeeenu10:avatar_faveee'
    ),
    # One Item
    (
        {
            "_id": TEST_ID,
            "avatar_addr": Address(TEST_AVATAR_ADDR),
            "item_data": [{
                "fungibleId": "f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0",
                "count": 1
            }],
            "memo": "test_item"
        },
        [
            bytes.fromhex(TEST_AVATAR_ADDR[2:]),
            None,
            [
                [bytes.fromhex("f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0"), 1]
            ],
            "test_item"
        ],
        b'du7:type_idu22:unload_from_my_garagesu6:valuesdu2:id16:\x0f$\xf5\xe6\xbc\x1b\x11\xee\xb0\xdco\xd7\x14v\x14*u1:ll20:I\xd5\xfc\xeb\x95X\x00\xb2\xc52\xd61\x9e\x80<}\x80\xf8\x17\xafnll32:\xf8\xfa\xf9,\x9c\r\x0e\x8e\x06iCa\xea\x87\xbf\xc8\xb2\x9a\x8a\xe8\xde\x93\x04K\x98G\nWcn\xd0\xe0i1eeeu9:test_itemeee'
    ),
    # Multiple Items
    (
        {
            "_id": TEST_ID,
            "avatar_addr": Address(TEST_AVATAR_ADDR),
            "item_data": [
                {
                    "fungibleId": "f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0",
                    "count": 1
                },
                {
                    "fungibleId": "00dfffe23964af9b284d121dae476571b7836b8d9e2e5f510d92a840fecc64fe",
                    "count": 1000
                },
            ],
            "memo": "test_items"
        },
        [
            bytes.fromhex(TEST_AVATAR_ADDR[2:]),
            None,
            [
                [bytes.fromhex("f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0"), 1],
                [bytes.fromhex("00dfffe23964af9b284d121dae476571b7836b8d9e2e5f510d92a840fecc64fe"), 1000]
            ],
            "test_items"
        ],
        b'du7:type_idu22:unload_from_my_garagesu6:valuesdu2:id16:\x0f$\xf5\xe6\xbc\x1b\x11\xee\xb0\xdco\xd7\x14v\x14*u1:ll20:I\xd5\xfc\xeb\x95X\x00\xb2\xc52\xd61\x9e\x80<}\x80\xf8\x17\xafnll32:\xf8\xfa\xf9,\x9c\r\x0e\x8e\x06iCa\xea\x87\xbf\xc8\xb2\x9a\x8a\xe8\xde\x93\x04K\x98G\nWcn\xd0\xe0i1eel32:\x00\xdf\xff\xe29d\xaf\x9b(M\x12\x1d\xaeGeq\xb7\x83k\x8d\x9e._Q\r\x92\xa8@\xfe\xccd\xfei1000eeeu10:test_itemseee'
    ),
    # All
    (
        {
            "_id": TEST_ID,
            "avatar_addr": Address(TEST_AVATAR_ADDR),
            "fav_data": [
                {
                    "balanceAddr": Address(TEST_AGENT_ADDR),
                    "value": FungibleAssetValue(Currency.CRYSTAL(), amount=Decimal("1"))
                },
                {
                    "balanceAddr": Address(TEST_AGENT_ADDR),
                    "value": FungibleAssetValue(Currency.NCG(), amount=Decimal("10"))
                },
            ],
            "item_data": [
                {
                    "fungibleId": "f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0",
                    "count": 1
                },
                {
                    "fungibleId": "00dfffe23964af9b284d121dae476571b7836b8d9e2e5f510d92a840fecc64fe",
                    "count": 1000
                },
            ],
            "memo": "test_all"
        },
        [
            bytes.fromhex(TEST_AVATAR_ADDR[2:]),
            [
                [
                    bytes.fromhex(TEST_AGENT_ADDR[2:]),
                    [{"decimalPlaces": b'\x12', "minters": None, "ticker": "CRYSTAL"}, 1000000000000000000]
                ],
                [
                    bytes.fromhex(TEST_AGENT_ADDR[2:]),
                    [{"decimalPlaces": b'\x02', "minters": [bytes.fromhex("47d082a115c63e7b58b1532d20e631538eafadde")],
                      "ticker": "NCG"}, 1000]
                ]
            ],
            [
                [bytes.fromhex("f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0"), 1],
                [bytes.fromhex("00dfffe23964af9b284d121dae476571b7836b8d9e2e5f510d92a840fecc64fe"), 1000]
            ],
            "test_all"
        ],
        b'du7:type_idu22:unload_from_my_garagesu6:valuesdu2:id16:\x0f$\xf5\xe6\xbc\x1b\x11\xee\xb0\xdco\xd7\x14v\x14*u1:ll20:I\xd5\xfc\xeb\x95X\x00\xb2\xc52\xd61\x9e\x80<}\x80\xf8\x17\xafll20:\xdb\xf4\xc6\xd0\xd7\xc7M9\x0f\xad\xaeh\x0f!D\xd8\x85\xc8x\xdfldu13:decimalPlaces1:\x12u7:mintersnu6:tickeru7:CRYSTALei1000000000000000000eeel20:\xdb\xf4\xc6\xd0\xd7\xc7M9\x0f\xad\xaeh\x0f!D\xd8\x85\xc8x\xdfldu13:decimalPlaces1:\x02u7:mintersl20:G\xd0\x82\xa1\x15\xc6>{X\xb1S- \xe61S\x8e\xaf\xad\xdeeu6:tickeru3:NCGei1000eeeell32:\xf8\xfa\xf9,\x9c\r\x0e\x8e\x06iCa\xea\x87\xbf\xc8\xb2\x9a\x8a\xe8\xde\x93\x04K\x98G\nWcn\xd0\xe0i1eel32:\x00\xdf\xff\xe29d\xaf\x9b(M\x12\x1d\xaeGeq\xb7\x83k\x8d\x9e._Q\r\x92\xa8@\xfe\xccd\xfei1000eeeu8:test_alleee'
    ),
]


@pytest.mark.parametrize("test_data", TEST_DATA)
def test_unload_action(test_data):
    data, expected, _ = test_data
    action = UnloadFromMyGarages(**data)
    plain_value = action.plain_value

    assert plain_value["type_id"] == "unload_from_my_garages"
    assert "l" in plain_value["values"]
    assert plain_value["values"]["l"] == expected


@pytest.mark.parametrize("test_data", TEST_DATA)
def test_serialized_plain_value(test_data):
    data, _, expected = test_data
    action = UnloadFromMyGarages(**data)
    print(action.serialized_plain_value)
    assert action.serialized_plain_value == expected
