import pytest

from common.lib9c.models.address import Address
from common.lib9c.models.currency import Currency

TEST_DATASET = [
    ("NCG", 2, ["47d082a115c63e7b58b1532d20e631538eafadde"], False,
     b'du13:decimalPlaces1:\x02u7:minterslu40:47d082a115c63e7b58b1532d20e631538eafaddeeu6:tickeru3:NCGe'),
    ("CRYSTAL", 18, None, False, b'du13:decimalPlaces1:\x12u7:mintersnu6:tickeru7:CRYSTALe'),
    ("GARAGE", 18, None, True, b'du13:decimalPlaces1:\x12u7:mintersnu6:tickeru6:GARAGEu20:totalSupplyTrackablete'),
    ("OTHER", 0, None, False, b'du13:decimalPlaces1:\x00u7:mintersnu6:tickeru5:OTHERe'),
    ("OTHER", 0, [], False, b'du13:decimalPlaces1:\x00u7:mintersnu6:tickeru5:OTHERe'),
    ("OTHER", 0, ["0x896cB1A849d8818BF8e1fcf4166DafD67E27Dce0"], False,
     b'du13:decimalPlaces1:\x00u7:minterslu40:896cb1a849d8818bf8e1fcf4166dafd67e27dce0eu6:tickeru5:OTHERe'),
    ("OTHER", 0, ["0x896cB1A849d8818BF8e1fcf4166DafD67E27Dce0", "0x3C32731b77C5D99D186572E5ce5d6AA93A8853dC"], False,
     b'du13:decimalPlaces1:\x00u7:minterslu40:896cb1a849d8818bf8e1fcf4166dafd67e27dce0u40:3c32731b77c5d99d186572e5ce5d6aa93a8853dceu6:tickeru5:OTHERe'),
]


@pytest.mark.parametrize("test_data", TEST_DATASET)
def test_currency(test_data):
    ticker, decimal_places, minters, total_supply_trackable, _ = test_data
    currency = Currency(ticker, decimal_places, minters, total_supply_trackable)
    assert currency.ticker == ticker
    assert currency.decimal_places == decimal_places
    assert currency.minters == ([Address(x) for x in minters] if minters else None)
    if total_supply_trackable:
        assert currency.total_supply_trackable is total_supply_trackable


def test_well_known_currency():
    test_ncg = Currency.NCG()
    expected_ncg = Currency("NCG", 2, ["47d082a115c63e7b58b1532d20e631538eafadde"], False)
    assert test_ncg == expected_ncg

    test_crystal = Currency.CRYSTAL()
    expected_crystal = Currency("CRYSTAL", 18, None, False)
    assert test_crystal == expected_crystal


@pytest.mark.parametrize("test_data", TEST_DATASET)
def test_plain_value(test_data):
    ticker, decimal_places, minters, total_supply_trackable, _ = test_data
    currency = Currency(ticker, decimal_places, minters, total_supply_trackable)
    plain_value = currency.plain_value
    assert plain_value["ticker"] == ticker
    assert plain_value["decimalPlaces"] == chr(decimal_places).encode()
    assert plain_value["minters"] == (
        [x[2:].lower() if x.startswith("0x") else x.lower() for x in minters] if minters else None)
    if total_supply_trackable:
        assert plain_value["totalSupplyTrackable"] == total_supply_trackable


@pytest.mark.parametrize("test_data", TEST_DATASET)
def test_serialized_plain_value(test_data):
    ticker, decimal_places, minters, total_supply_trackable, serialized = test_data
    currency = Currency(ticker, decimal_places, minters, total_supply_trackable)
    assert currency.serialized_plain_value == serialized
