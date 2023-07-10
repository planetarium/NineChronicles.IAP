import hmac
import json
import os
from hashlib import sha1
from typing import Union, Optional, Dict

import boto3
import eth_utils
import googleapiclient.discovery
from google.oauth2 import service_account
from sqlalchemy.orm import joinedload

from common import logger
from common.enums import Store
from common.models.product import Product, Price
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


def checksum_encode(addr: bytes) -> str:  # Takes a 20-byte binary address as input
    """
    Convert input address to checksum encoded address without prefix "0x"
    See [ERC-55](https://eips.ethereum.org/EIPS/eip-55)

    :param addr: 20-bytes binary address
    :return: checksum encoded address as string
    """
    hex_addr = addr.hex()
    checksum_buffer = ""

    # Treat the hex address as ascii/utf-8 for keccak256 hashing
    hashed_address = eth_utils.keccak(text=hex_addr).hex()

    # Iterate over each character in the hex address
    for nibble_index, character in enumerate(hex_addr):
        if character in "0123456789":
            # We can't upper-case the decimal digits
            checksum_buffer += character
        elif character in "abcdef":
            # Check if the corresponding hex digit (nibble) in the hash is 8 or higher
            hashed_address_nibble = int(hashed_address[nibble_index], 16)
            if hashed_address_nibble > 7:
                checksum_buffer += character.upper()
            else:
                checksum_buffer += character
        else:
            raise eth_utils.ValidationError(
                f"Unrecognized hex character {character!r} at position {nibble_index}"
            )
    return checksum_buffer


def derive_address(address: Union[str, bytes], key: Union[str, bytes], get_byte: bool = False) -> Union[bytes, str]:
    """
    Derive given address using key.
    It's just like libplanet's `address.DeriveAddress(key)` function.

    :param address: Original address to make derived address
    :param key: Derive Key
    :param get_byte: If set this values to `True`, the return value is converted to checksum encoded string. default: False
    :return: Derived address. (Either bytes or str followed by `get_byte` flag)
    """
    # TODO: Error handling
    if address.startswith("0x"):
        address = address[2:]

    if type(address) == str:
        address = bytes.fromhex(address)

    if type(key) == str:
        key = bytes(key, "UTF-8")

    derived = hmac.new(key, address, sha1).digest()
    return derived if get_byte else checksum_encode(derived)


def get_google_client(credential_data: str):
    scopes = ["https://www.googleapis.com/auth/androidpublisher"]
    credential = service_account.Credentials.from_service_account_info(json.loads(credential_data), scopes=scopes)
    return googleapiclient.discovery.build("androidpublisher", "v3", credentials=credential)


def update_google_price(sess, credential_data: str, package_name: str):
    store = Store.GOOGLE if os.environ.get("ENV") == "mainnet" else Store.GOOGLE_TEST
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
