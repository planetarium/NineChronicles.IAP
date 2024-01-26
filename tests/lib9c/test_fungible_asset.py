from common.lib9c.fungible_asset import FungibleAsset


def test_to_fungible_asset():
    assert FungibleAsset.to_fungible_asset("CRYSTAL", 100, 18) == [{"decimalPlaces": b'\x12', "minters": None, "ticker": "CRYSTAL"}, 100 * 10**18]
    assert FungibleAsset.to_fungible_asset("GARAGE", 1, 18) == [{"decimalPlaces": b'\x12', "minters": None, "ticker": "GARAGE", "totalSupplyTrackable": True}, 1 * 10**18]
    assert FungibleAsset.to_fungible_asset("OTHER", 999, 0) == [{"decimalPlaces": b'\x00', "minters": None, "ticker": "OTHER"}, 999]


def test_serialize():
    assert FungibleAsset.serialize(FungibleAsset.to_fungible_asset("CRYSTAL", 100, 18)).hex() == "6c35323a647531333a646563696d616c506c61636573313a1275373a6d696e746572736e75363a7469636b657275373a4352595354414c65693130303030303030303030303030303030303030306565"
    assert FungibleAsset.serialize(FungibleAsset.to_fungible_asset("GARAGE", 1, 18)).hex() == "6c37363a647531333a646563696d616c506c61636573313a1275373a6d696e746572736e75363a7469636b657275363a4741524147457532303a746f74616c537570706c79547261636b61626c65746569313030303030303030303030303030303030306565"
    assert FungibleAsset.serialize(FungibleAsset.to_fungible_asset("OTHER", 999, 0)).hex() == "6c35303a647531333a646563696d616c506c61636573313a0075373a6d696e746572736e75363a7469636b657275353a4f5448455265693939396565"
