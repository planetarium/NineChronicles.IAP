import logging
import os
import random

import requests

HOST_LIST = [
    "https://9c-main-rpc-1.nine-chronicles.com/",
    "https://9c-main-rpc-2.nine-chronicles.com/",
    "https://9c-main-rpc-3.nine-chronicles.com/",
    "https://9c-main-rpc-4.nine-chronicles.com/",
    "https://9c-main-rpc-5.nine-chronicles.com/",
]

URL = f"{random.choice(HOST_LIST)}/graphql"


def get_next_nonce(address: str) -> int:
    """
    Get next Tx Nonce to create Transaction.
    -1 will be returned in case of any error.

    :param str address: 9c Address to get next Nonce.
    :return: Next tx Nonce. In case of any error, `-1` will be returned.
    """
    query = """
    query getNextNonce($address:Address!) {
        transaction {
            nextTxNonce(address: $address)
        }
    }
    """
    variables = {
        "address": os.environ.get("SIGNER_ADDRESS")
    }

    resp = requests.post(URL, json={"query": query, "variables": variables})
    if resp.status_code != 200:
        logging.error("Failed to get next Nonce from GQL host.")
        return -1

    data = resp.json()
    if "errors" in data:
        logging.error(f"GQL failed to get next Nonce: {data['errors']}")
        return -1

    return data["data"]["transaction"]["nextTxNonce"]


def sign_tx():
    pass


def stage_tx():
    pass


def transfer_box(recipient: str, *, payload: dict, ncg: float) -> str:
    """
    Create Tx to transfer purchased items to buyer.
    This Tx is not signed, so you have to sign this with sender's private key before stage it to 9c blockchain.

    :param str recipient: The 9c address where the IAP purchased items will be sent.
    This address should be the same as the one used by the IAP product buyer.
    :param dict payload: The items to be transferred, corresponding to the package purchased by the buyer.
    :param float ncg: The values of NCGs to be transferred to buyer.
    :return: Hexadecimal encoded unsigned Tx string.
    """
    # Sender is Fixed to IAP address
    # Create Tx
    # Sign Tx
    # Stage Tx
