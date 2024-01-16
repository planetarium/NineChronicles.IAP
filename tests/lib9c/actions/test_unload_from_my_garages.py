import pytest

from common.lib9c.actions.unload_from_my_garages import UnloadFromMyGarages
from common.lib9c.models.address import Address
from common.lib9c.models.currency import Currency
from common.lib9c.models.fungible_asset_value import FungibleAssetValue

TEST_AGENT_ADDR = "0xDbF4c6d0D7C74D390fADae680f2144D885c878df"
TEST_AVATAR_ADDR = "0x49D5FcEB955800B2c532D6319E803c7D80f817Af"

TEST_DATA = [
    # One FAV
    (
        {
            "avatar_addr": Address(TEST_AVATAR_ADDR),
            "fav_data": [{
                "balanceAddr": Address(TEST_AGENT_ADDR),
                "value": FungibleAssetValue.from_raw_data("CRYSTAL", 18, amount=1)
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
        ]
    ),
    # Multiple FAVs
    (
        {
            "avatar_addr": Address(TEST_AVATAR_ADDR),
            "fav_data": [
                {
                    "balanceAddr": Address(TEST_AGENT_ADDR),
                    "value": FungibleAssetValue(Currency.CRYSTAL(), amount=1)
                },
                {
                    "balanceAddr": Address(TEST_AGENT_ADDR),
                    "value": FungibleAssetValue(Currency.NCG(), amount=10)
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
        ]
    ),
    # Multiple FAVs with Avatar bound FAV
    (
        {
            "avatar_addr": Address(TEST_AVATAR_ADDR),
            "fav_data": [
                {
                    "balanceAddr": Address(TEST_AGENT_ADDR),
                    "value": FungibleAssetValue.from_raw_data("CRYSTAL", 18, amount=1)
                },
                {
                    "balanceAddr": Address(TEST_AVATAR_ADDR),
                    "value": FungibleAssetValue.from_raw_data("RUNE_GOLDENLEAF", 0, amount=10)
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
        ]
    ),
    # One Item
    (
        {
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
        ]
    ),
    # Multiple Items
    (
        {
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
        ]
    ),
    # All
    (
        {
            "avatar_addr": Address(TEST_AVATAR_ADDR),
            "fav_data": [
                {
                    "balanceAddr": Address(TEST_AGENT_ADDR),
                    "value": FungibleAssetValue(Currency.CRYSTAL(), amount=1)
                },
                {
                    "balanceAddr": Address(TEST_AGENT_ADDR),
                    "value": FungibleAssetValue(Currency.NCG(), amount=10)
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
        ]
    ),
]


@pytest.mark.parametrize("test_data", TEST_DATA)
def test_unload_action(test_data):
    data, expected = test_data
    action = UnloadFromMyGarages(**data)
    plain_value = action.plain_value

    assert plain_value["type_id"] == "unload_from_my_garages"
    assert "l" in plain_value["values"]
    assert plain_value["values"]["l"] == expected
