import pytest

from iap.schemas.product import FungibleAssetValueSchema, FungibleItemSchema


@pytest.mark.parametrize(
    "fav_set",
    [("CRYSTAL", "CRYSTAL"), ("FAV__CRYSTAL", "CRYSTAL"), ("RUNE_GOLDENLEAF", "RUNE_GOLDENLEAF")]
)
def test_fav_schema(fav_set):
    original, expected = fav_set

    schema = FungibleAssetValueSchema(ticker=original, amount=0)
    assert schema.ticker == expected


@pytest.mark.parametrize(
    "item_set",
    [(600201,
      "f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0",
      "f8faf92c9c0d0e8e06694361ea87bfc8b29a8ae8de93044b98470a57636ed0e0"),  # Golden Dust
     (600201, "Item_NT_600201", "Item_NT_600201"),  # Golden Dust, Wrapped
     (500000, "Item_NT_500000", "Item_NT_500000"),  # Ap Potion, Wrapped
     (49900011, "Item_NT_49900011", "Item_NT_49900011"),  # SeasonPass 1 Title, Wrapped
     ]
)
def test_fungible_item_schema(item_set):
    sheet_item_id, original, expected = item_set

    schema = FungibleItemSchema(sheet_item_id=sheet_item_id, fungible_item_id=original, amount=1)
    assert schema.fungible_item_id == expected
