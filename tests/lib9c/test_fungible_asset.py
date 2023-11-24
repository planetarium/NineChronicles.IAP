from common.lib9c.fungible_asset import FungibleAsset


def test_to_fungible_asset():
    assert FungibleAsset.to_fungible_asset("CRYSTAL", 100) == [{"decimalPlaces": b'\x12', "minters": None, "ticker": "CRYSTAL"}, 100]
    assert FungibleAsset.to_fungible_asset("GARAGE", 1) == [{"decimalPlaces": b'\x12', "minters": None, "ticker": "GARAGE", "totalSupplyTrackable": True}, 1]
    assert FungibleAsset.to_fungible_asset("OTHER", 999) == [{"decimalPlaces": b'0', "minters": None, "ticker": "OTHER"}, 999]

def test_serialize():
    assert FungibleAsset.serialize(FungibleAsset.to_fungible_asset("CRYSTAL", 100)).hex() == "6c647531333a646563696d616c506c61636573323a313875373a6d696e746572736e75363a7469636b657275373a4352595354414c65693130306565"
    assert FungibleAsset.serialize(FungibleAsset.to_fungible_asset("GARAGE", 1)).hex() == "6c647531333a646563696d616c506c61636573323a313275373a6d696e746572736e75363a7469636b657275363a4741524147457532303a746f74616c537570706c79547261636b61626c65746569316565"
    assert FungibleAsset.serialize(FungibleAsset.to_fungible_asset("OTHER", 999)).hex() == "6c647531333a646563696d616c506c61636573313a3075373a6d696e746572736e75363a7469636b657275353a4f5448455265693939396565"
    