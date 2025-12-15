import os
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, HTTPException
from shared._graphql import GQL
from shared.utils.balance import BALANCE_QUERY
from shared.enums import PlanetID, ReceiptStatus, Store
from shared.models.product import Price
from shared.models.receipt import Receipt
from sqlalchemy import Date, cast, func

from app.api import admin, l10n, mileage, product, purchase, redeem
from app.config import config
from app.dependencies import session

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
    redeem,
]

for view in __all__:
    router.include_router(view.router)


@router.get("/balance/{planet}")
def get_balance(planet: str):
    """Report IAP Garage stock"""
    url = config.gql_url_map[planet]
    gql = GQL(url, jwt_secret=config.headless_jwt_secret)

    resp = requests.post(
        url,
        json={"query": BALANCE_QUERY},
        headers={"Authorization": f"Bearer {gql.create_token()}"},
    )
    data = resp.json()["data"]["stateQuery"]

    msg = {}
    for name, balance in data.items():
        msg[name] = {
            "ticker": balance["currency"]["ticker"],
            "quantity": float(balance["quantity"]),
        }

    return msg
