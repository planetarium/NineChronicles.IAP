import json
import os
from typing import List

import googleapiclient.discovery
from google.oauth2 import service_account
from googleapiclient.discovery import build
from sqlalchemy.orm import joinedload

from common import logger
from common.enums import Store
from common.models.product import Product, Price
from common.schemas.product import GoogleIAPProductSchema


def update_google_price(sess, credential_data: str, package_name: str):
    store = Store.GOOGLE if os.environ.get("STAGE") == "mainnet" else Store.GOOGLE_TEST
    client = get_google_client(credential_data)
    all_product_dict = {x.google_sku: x for x in
                        (sess.query(Product).options(joinedload(Product.price_list))
                         # DISCUSS: Should I filter by store too?
                         .filter(Price.active.is_(True))
                         ).all()
                        }
    if not all_product_dict:
        # In case DB does not have any price, former query result can be empty.
        # Then, just get all products.
        all_product_dict = {x.google_sku: x for x in
                            (sess.query(Product).options(joinedload(Product.price_list))).all()
                            }

    google_product_info = client.inappproducts().list(packageName=package_name).execute()
    product_list = [GoogleIAPProductSchema(**x) for x in google_product_info["inappproduct"]]
    change_count = [0, 0]
    for product in product_list:
        if product.status != "active":
            logger.warning(f"Google product {product.sku} is not active. Skip this product from updating price.")
            continue

        target_product = all_product_dict.get(product.sku)
        if not target_product:
            # Do not update unknown product
            logger.error(f"Product with google SKU {product.sku} not found in DB.")
            continue

        change_count[0] += 1
        for price in target_product.price_list:
            price.active = False

        change_count[1] += 1
        target_product.price_list.append(Price(
            product_id=target_product.id,
            store=store,
            currency=product.defaultPrice.currency,
            price=product.defaultPrice.price,
            active=True
        ))

        for country, price_info in product.prices.items():
            change_count[1] += 1
            target_product.price_list.append(Price(
                product_id=target_product.id,
                store=store,
                currency=price_info.currency,
                price=price_info.price,
                active=True
            ))

        sess.add(target_product)
    try:
        sess.commit()
        return change_count
    except Exception as e:
        logger.error(f"Google price update failed: {e}")
        raise e
    finally:
        sess.rollback()


def get_google_client(credential_data: str):
    scopes = ["https://www.googleapis.com/auth/androidpublisher"]
    credential = service_account.Credentials.from_service_account_info(json.loads(credential_data), scopes=scopes)
    return googleapiclient.discovery.build("androidpublisher", "v3", credentials=credential)


class Spreadsheet:
    def __init__(self, credential_data: str, sheet_id: str):
        SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
        self.sheet_id = sheet_id
        self._token_file = "credential.pickle"
        self.creds = service_account.Credentials.from_service_account_info(json.loads(credential_data), scopes=SCOPES)
        self.service = build("sheets", "v4", credentials=self.creds)

    def get_values(self, range_):
        result = self.service.spreadsheets().values().get(spreadsheetId=self.sheet_id, range=range_).execute()
        return result

    def get_batch_values(self, range_: List[str]):
        result = self.service.spreadsheets().values().batchGet(spreadsheetId=self.sheet_id, ranges=range_).execute()
        return result

    def set_values(self, range_, value_):
        body = {
            "value_input_option": "USER_ENTERED",
            "data": [
                {
                    "range": range_,
                    "majorDimension": "ROWS",
                    "values": value_
                }
            ]
        }
        result = self.service.spreadsheets().values().batchUpdate(spreadsheetId=self.sheet_id, body=body).execute()
        return result
