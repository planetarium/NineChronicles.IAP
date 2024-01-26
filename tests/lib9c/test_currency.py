import bencodex
from common.lib9c.currency import Currency


def test_crystal():
    crystal = Currency.to_currency("crystal")
    assert crystal["decimalPlaces"] == b'\x12'
    assert crystal["minters"] == None
    assert crystal["ticker"] == "CRYSTAL"

def test_garage():
    garage = Currency.to_currency("garage")
    assert garage["decimalPlaces"] == b'\x12'
    assert garage["minters"] == None
    assert garage["ticker"] == "GARAGE"
    assert garage["totalSupplyTrackable"] == True

def test_other():
    other = Currency.to_currency("other")
    assert other["decimalPlaces"] == b'\x00'
    assert other["minters"] == None
    assert other["ticker"] == "OTHER"

def test_serialize():
    crystal = Currency.to_currency("crystal")
    assert Currency.serialize(crystal) == bencodex.dumps({'decimalPlaces': b'\x12', 'minters': None, 'ticker': 'CRYSTAL'})
    garage = Currency.to_currency("garage")
    assert Currency.serialize(garage) == bencodex.dumps({'decimalPlaces': b'\x12', 'minters': None, 'ticker': 'GARAGE', 'totalSupplyTrackable': True})
    other = Currency.to_currency("other")
    assert Currency.serialize(other) == bencodex.dumps({'decimalPlaces': b'\x00', 'minters': None, 'ticker': 'OTHER'})
