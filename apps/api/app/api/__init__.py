import os

import requests
from fastapi import APIRouter
from shared._graphql import GQL
from shared.enums import PlanetID

from app.api import admin, l10n, mileage, product, purchase
from app.config import config

router = APIRouter(
    prefix="/api",
    # tags=["API"],
)

__all__ = [
    purchase,
    product,
    l10n,
    mileage,
    admin,
]

for view in __all__:
    router.include_router(view.router)


@router.get("/balance/{planet}")
def get_balance(planet: str):
    """Report IAP Garage stock"""
    target_planet = config.gql_url_map[planet.upper()]
    url = target_planet["url"]
    gql = GQL(url, jwt_secret=config.headless_jwt_secret)
    query = """
query balanceQuery(
  $address: Address! = "0xCb75C84D76A6f97A2d55882Aea4436674c288673"
) {
  stateQuery {
    BlackCat: balance (
      address: $address,
      currency: {ticker: "FAV__SOULSTONE_1001", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    RedDongle: balance (
      address: $address,
      currency: {ticker: "FAV__SOULSTONE_1002", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    Valkyrie: balance (
      address: $address,
      currency: {ticker: "FAV__SOULSTONE_1003", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    LilFenrir: balance (
      address: $address,
      currency: {ticker: "FAV__SOULSTONE_1004", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    ThorRune: balance (
      address: $address,
      currency: {ticker: "FAV__RUNESTONE_GOLDENTHOR", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    GoldenMeat: balance (
      address: $address,
      currency: {ticker: "Item_NT_800202", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    CriRune: balance (
      address: $address,
      currency: {ticker: "FAV__RUNESTONE_CRI", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    EmeraldDust: balance (
      address: $address,
      currency: {ticker: "Item_NT_600203", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    Crystal: balance (
      address: $address,
      currency: {ticker: "FAV__CRYSTAL", decimalPlaces: 18, minters: [], }
    ) { currency {ticker} quantity }
    hourglass: balance (
      address: $address,
      currency: {ticker: "Item_NT_400000", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    APPotion: balance (
      address: $address,
      currency: {ticker: "Item_NT_500000", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    GoldenLeafRune: balance (
      address: $address,
      currency: {ticker: "FAV__RUNE_GOLDENLEAF", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    GoldenDust: balance (
      address: $address,
      currency: {ticker: "Item_NT_600201", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    RubyDust: balance (
      address: $address,
      currency: {ticker: "Item_NT_600202", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
    SilverDust: balance (
      address: $address,
      currency: {ticker: "Item_NT_800201", decimalPlaces: 0, minters: [], }
    ) { currency {ticker} quantity }
  }
}"""

    resp = requests.post(url, json={"query": query}, headers={"Authorization": f"Bearer {gql.create_token()}"})
    data = resp.json()["data"]["stateQuery"]

    msg = {}
    for name, balance in data.items():
        msg[name] = {"ticker": balance["currency"]["ticker"], "quantity": float(balance["quantity"])}

    return msg
