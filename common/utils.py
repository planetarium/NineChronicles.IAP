import json
import os
from typing import Optional, Dict, List

import boto3
import googleapiclient.discovery
from google.oauth2 import service_account
from gql.dsl import dsl_gql, DSLQuery
from sqlalchemy import select, distinct
from sqlalchemy.orm import joinedload

from common import logger
from common._crypto import Account
from common._graphql import GQL
from common.enums import Store
from common.models.product import Product, Price, FungibleItemProduct
from common.schemas.product import GoogleIAPProductSchema


def fetch_parameter(region: str, parameter_name: str, secure: bool):
    ssm = boto3.client("ssm", region_name=region)
    resp = ssm.get_parameter(
        Name=parameter_name,
        WithDecryption=secure,
    )
    return resp["Parameter"]


def fetch_secrets(region: str, secret_arn: str) -> Dict:
    sm = boto3.client("secretsmanager", region_name=region)
    resp = sm.get_secret_value(SecretId=secret_arn)
    return json.loads(resp["SecretString"])


def fetch_kms_key_id(stage: str, region: str) -> Optional[str]:
    client = boto3.client("ssm", region_name=region)
    try:
        return client.get_parameter(Name=f"{stage}_9c_IAP_KMS_KEY_ID", WithDecryption=True)["Parameter"]["Value"]
    except Exception as e:
        logger.error(e)
        return None


def format_addr(addr: str) -> str:
    """
    Check and reformat input address if not starts with `0x`.
    """
    if not addr.startswith("0x"):
        return f"0x{addr}"
    return addr


def get_google_client(credential_data: str):
    scopes = ["https://www.googleapis.com/auth/androidpublisher"]
    credential = service_account.Credentials.from_service_account_info(json.loads(credential_data), scopes=scopes)
    return googleapiclient.discovery.build("androidpublisher", "v3", credentials=credential)


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


def get_iap_garage(sess) -> List[Optional[Dict]]:
    """
    Get NCG balance and fungible item count of IAP address.
    :return:
    """
    stage = os.environ.get("STAGE", "development")
    region_name = os.environ.get("REGION_NAME", "us-east-2")
    client = GQL()
    account = Account(fetch_kms_key_id(stage, region_name))

    fungible_id_list = sess.scalars(select(distinct(FungibleItemProduct.fungible_item_id))).fetchall()

    query = dsl_gql(
        DSLQuery(
            client.ds.StandaloneQuery.stateQuery.select(
                client.ds.StateQuery.garages.args(
                    agentAddr=account.address,
                    fungibleItemIds=fungible_id_list,
                ).select(
                    client.ds.GaragesType.agentAddr,
                    client.ds.GaragesType.fungibleItemGarages.select(
                        client.ds.FungibleItemGarageWithAddressType.fungibleItemId,
                        client.ds.FungibleItemGarageWithAddressType.count,
                    )
                )
            )
        )
    )
    resp = client.execute(query)
    if "errors" in resp:
        msg = f"GQL failed to get IAP garage: {resp['errors']}"
        logger.error(msg)
        raise Exception(msg)

    return resp["stateQuery"]["garages"]["fungibleItemGarages"]
