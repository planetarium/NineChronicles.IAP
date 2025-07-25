import pytest

from shared.lib9c.models.currency import Currency
from shared.lib9c.models.fungible_asset_value import FungibleAssetValue

TEST_DATASET = [
    ("NCG", 2, ["47d082a115c63e7b58b1532d20e631538eafadde"], False, 0,
     b'ldu13:decimalPlaces1:\x02u7:mintersl20:G\xd0\x82\xa1\x15\xc6>{X\xb1S- \xe61S\x8e\xaf\xad\xdeeu6:tickeru3:NCGei0ee'),
    ("CRYSTAL", 18, None, False, 0, b'ldu13:decimalPlaces1:\x12u7:mintersnu6:tickeru7:CRYSTALei0ee'),
    ("GARAGE", 18, None, True, 0,
     b'ldu13:decimalPlaces1:\x12u7:mintersnu6:tickeru6:GARAGEu20:totalSupplyTrackabletei0ee'),
    ("OTHER", 0, None, False, 0, b'ldu13:decimalPlaces1:\x00u7:mintersnu6:tickeru5:OTHERei0ee'),
    (
        "OTHER", 0, ["0x896cB1A849d8818BF8e1fcf4166DafD67E27Dce0", "0x3C32731b77C5D99D186572E5ce5d6AA93A8853dC"], False,
        0,
        b"ldu13:decimalPlaces1:\x00u7:mintersl20:\x89l\xb1\xa8I\xd8\x81\x8b\xf8\xe1\xfc\xf4\x16m\xaf\xd6~'\xdc\xe020:<2s\x1bw\xc5\xd9\x9d\x18er\xe5\xce]j\xa9:\x88S\xdceu6:tickeru5:OTHERei0ee"
    ),
    ("NCG", 2, ["47d082a115c63e7b58b1532d20e631538eafadde"], False, 1,
     b'ldu13:decimalPlaces1:\x02u7:mintersl20:G\xd0\x82\xa1\x15\xc6>{X\xb1S- \xe61S\x8e\xaf\xad\xdeeu6:tickeru3:NCGei100ee'),
    ("CRYSTAL", 18, None, False, 1, b'ldu13:decimalPlaces1:\x12u7:mintersnu6:tickeru7:CRYSTALei1000000000000000000ee'),
    ("GARAGE", 18, None, True, 1,
     b'ldu13:decimalPlaces1:\x12u7:mintersnu6:tickeru6:GARAGEu20:totalSupplyTrackabletei1000000000000000000ee'),
    ("OTHER", 0, None, False, 1, b'ldu13:decimalPlaces1:\x00u7:mintersnu6:tickeru5:OTHERei1ee'),
    (
        "OTHER", 0, ["0x896cB1A849d8818BF8e1fcf4166DafD67E27Dce0", "0x3C32731b77C5D99D186572E5ce5d6AA93A8853dC"], False,
        1,
        b"ldu13:decimalPlaces1:\x00u7:mintersl20:\x89l\xb1\xa8I\xd8\x81\x8b\xf8\xe1\xfc\xf4\x16m\xaf\xd6~'\xdc\xe020:<2s\x1bw\xc5\xd9\x9d\x18er\xe5\xce]j\xa9:\x88S\xdceu6:tickeru5:OTHERei1ee"
    ),
]


@pytest.mark.parametrize("test_data", TEST_DATASET)
def test_fav(test_data):
    ticker, decimal_places, minters, total_supply_trackable, amount, _ = test_data
    currency = Currency(ticker, decimal_places, minters, total_supply_trackable)
    fav = FungibleAssetValue(currency, amount)
    assert fav.currency == currency
    assert fav.amount == amount


@pytest.mark.parametrize("test_data", TEST_DATASET)
def test_fav_from_data(test_data):
    ticker, decimal_places, minters, total_supply_trackable, amount, _ = test_data
    fav = FungibleAssetValue.from_raw_data(ticker, decimal_places, minters, total_supply_trackable, amount)
    expected_currency = Currency(ticker, decimal_places, minters, total_supply_trackable)
    assert fav.currency == expected_currency
    assert fav.amount == amount


@pytest.mark.parametrize("test_data", TEST_DATASET)
def test_plain_value(test_data):
    ticker, decimal_places, minters, total_supply_trackable, amount, _ = test_data
    fav = FungibleAssetValue.from_raw_data(ticker, decimal_places, minters, total_supply_trackable, amount)
    plain_value = fav.plain_value
    assert plain_value[0]["ticker"] == ticker
    assert plain_value[0]["decimalPlaces"] == chr(decimal_places).encode()
    assert plain_value[0]["minters"] == (
        [bytes.fromhex(x[2:]) if x.startswith("0x") else bytes.fromhex(x) for x in minters] if minters else None
    )
    if total_supply_trackable:
        assert plain_value[0]["totalSupplyTrackable"] is True
    else:
        assert "totalSupplyTrackable" not in plain_value[0]
    assert plain_value[1] == amount * max(1, 10 ** decimal_places)


@pytest.mark.parametrize("test_data", TEST_DATASET)
def test_serialized_plain_value(test_data):
    ticker, decimal_places, minters, total_supply_trackable, amount, expected = test_data
    fav = FungibleAssetValue.from_raw_data(ticker, decimal_places, minters, total_supply_trackable, amount)
    assert fav.serialized_plain_value == expected
