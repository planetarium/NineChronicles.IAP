from decimal import Decimal

import pytest

from shared.lib9c.actions.issue_tokens_from_garage import IssueTokensFromGarage, FavIssueSpec, ItemIssueSpec
from shared.lib9c.models.currency import Currency
from shared.lib9c.models.fungible_asset_value import FungibleAssetValue

TEST_ID = "0d0d9e0cbc1b11eeb0dc6fd71476142a"
TEST_FUNGIBLE_ITEM_ID = "f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0"  # Golden Dust
TEST_FUNGIBLE_ITEM_BINARY = b'\xf8\xfa\xf9,\x9c\r\x0e\x8e\x06iCa\xea\x87\xbf\xc8\xb2\x9a\x8a\xe8\xde\x93\x04K\x98G\nWcn\xd0\xe0'
ACTION_TEST_DATA = [
    (
        {
            "_id": TEST_ID,
            "values": [
                FavIssueSpec(FungibleAssetValue.from_raw_data("Crystal", 18, amount=Decimal("1000")))
            ]
        },
        [
            [
                [
                    {
                        "ticker": "Crystal",
                        "decimalPlaces": b'\x12',
                        "minters": None,
                    },
                    1000 * 10 ** 18
                ],
                None
            ],
        ]
    ),
    (
        {
            "_id": TEST_ID,
            "values": [
                ItemIssueSpec(TEST_FUNGIBLE_ITEM_ID, 42)
            ]
        },
        [
            [
                None,
                [
                    TEST_FUNGIBLE_ITEM_BINARY,
                    42
                ]
            ]
        ]
    ),
    (
        {
            "_id": TEST_ID,
            "values": [
                ItemIssueSpec("f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0", 42)
            ]
        },
        [
            [
                None,
                [
                    b'\xf8\xfa\xf9,\x9c\r\x0e\x8e\x06iCa\xea\x87\xbf\xc8\xb2\x9a\x8a\xe8\xde\x93\x04K\x98G\nWcn\xd0\xe0',
                    42
                ]
            ]
        ]
    ),
    (
        {
            "_id": TEST_ID,
            "values": [
                FavIssueSpec(FungibleAssetValue.from_raw_data("Crystal", 18, amount=Decimal("1000"))),
                ItemIssueSpec("f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0", 42)
            ]
        },
        [
            [
                [
                    {
                        "ticker": "Crystal",
                        "decimalPlaces": b'\x12',
                        "minters": None,
                    },
                    1000 * 10 ** 18
                ],
                None
            ],
            [
                None,
                [
                    b'\xf8\xfa\xf9,\x9c\r\x0e\x8e\x06iCa\xea\x87\xbf\xc8\xb2\x9a\x8a\xe8\xde\x93\x04K\x98G\nWcn\xd0\xe0',
                    42
                ]
            ]
        ]
    )
]


def test_fav_issue_spec():
    fav = FungibleAssetValue(Currency("Crystal", 18), Decimal(42))
    fav_issue_spec = FavIssueSpec(fav)
    assert fav_issue_spec.plain_value[0] == fav.plain_value


@pytest.mark.parametrize("data", [TEST_FUNGIBLE_ITEM_ID, TEST_FUNGIBLE_ITEM_BINARY])
def test_item_issue_spec(data):
    item_issue_spec = ItemIssueSpec(data, 42)
    assert item_issue_spec.plain_value == [None, [TEST_FUNGIBLE_ITEM_BINARY, 42]]


@pytest.mark.parametrize("test_data", ACTION_TEST_DATA)
def test_action(test_data):
    data, expected = test_data
    action = IssueTokensFromGarage(**data)
    plain_value = action.plain_value
    values = plain_value["values"]

    assert plain_value["type_id"] == "issue_tokens_from_garage"
    assert values == expected
