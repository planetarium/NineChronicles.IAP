import datetime
import logging
import os
import random
from typing import Optional, Tuple

from gql import Client
from gql.dsl import DSLMutation, DSLQuery, DSLSchema, dsl_gql
from gql.transport.requests import RequestsHTTPTransport
from graphql import DocumentNode

CURRENCY_LIST = ("NCG", "CRYSTAL")

HOST_LIST = {
    "local": [
        "http://localhost",
    ],
    "internal": [
        "https://9c-internal-rpc-1.nine-chronicles.com",
    ],
    "mainnet": [
        "https://9c-main-rpc-1.nine-chronicles.com",
        "https://9c-main-rpc-2.nine-chronicles.com",
        "https://9c-main-rpc-3.nine-chronicles.com",
        "https://9c-main-rpc-4.nine-chronicles.com",
        "https://9c-main-rpc-5.nine-chronicles.com",
    ],
}


class GQL:
    def __init__(self):
        stage = os.environ.get("STAGE", "development")
        self._url = f"{random.choice(HOST_LIST[stage])}/graphql"
        transport = RequestsHTTPTransport(url=self._url, verify=True, retries=2)
        self.client = Client(transport=transport, fetch_schema_from_transport=True)
        with self.client as _:
            assert self.client.schema is not None
            self.ds = DSLSchema(self.client.schema)

    def execute(self, query: DocumentNode) -> object:
        with self.client as sess:
            return sess.execute(query)

    def get_next_nonce(self, address: str) -> int:

        """
        Get next Tx Nonce to create Transaction.
        -1 will be returned in case of any error.

        :param str address: 9c Address to get next Nonce.
        :return: Next tx Nonce. In case of any error, `-1` will be returned.
        """
        query = dsl_gql(
            DSLQuery(
                self.ds.StandaloneQuery.transaction.select(
                    self.ds.TransactionHeadlessQuery.nextTxNonce.args(
                        address=address,
                    )
                )
            )
        )
        resp = self.client.execute(query)

        if "errors" in resp:
            logging.error(f"GQL failed to get next Nonce: {resp['errors']}")
            return -1

        return max(resp["transaction"]["nextTxNonce"], 1)  # 1 is minimum nonce

    def _transfer_asset(self, pubkey: str, nonce: int, **kwargs) -> bytes:
        ts = kwargs.get("timestamp", datetime.datetime.utcnow().isoformat())
        sender = kwargs.get("sender")
        recipient = kwargs.get("recipient")
        currency = kwargs.get("currency")
        amount = kwargs.get("amount")
        memo = kwargs.get("memo", "")
        if not (sender and recipient and currency and amount):
            raise ValueError("All params must be exist to execute this action: sender, recipient, currency, amount")
        if currency not in CURRENCY_LIST:
            raise ValueError(f"Given currency {currency} it not valid. Please input one of {CURRENCY_LIST}")
        if float(amount) <= 0:
            raise ValueError(f"Given amount {amount} is not positive. Please give positive value")

        query = dsl_gql(
            DSLQuery(
                self.ds.StandaloneQuery.actionTxQuery.args(
                    publicKey=pubkey,
                    nonce=nonce,
                    timestamp=ts,
                ).select(
                    self.ds.ActionTxQuery.transferAsset.args(
                        sender=sender, recipient=recipient, currency=currency, amount=amount, memo=memo
                    )
                )
            )
        )
        result = self.client.execute(query)
        return bytes.fromhex(result["actionTxQuery"]["transferAsset"])

    def create_action(self, action_type: str, pubkey: bytes, nonce: int, **kwargs) -> bytes:
        fn = getattr(self, f"_{action_type}")
        if not fn:
            raise ValueError(f"Action named {action_type} does not exists.")

        return fn(pubkey, nonce, **kwargs)

    def sign(self, unsigned_tx: bytes, signature: bytes) -> bytes:
        query = dsl_gql(
            DSLQuery(
                self.ds.StandaloneQuery.transaction.select(
                    self.ds.TransactionHeadlessQuery.signTransaction.args(
                        unsignedTransaction=unsigned_tx.hex(),
                        signature=signature.hex()
                    )
                )
            )
        )
        result = self.client.execute(query)
        return bytes.fromhex(result["transaction"]["signTransaction"])

    def stage(self, signed_tx: bytes) -> Tuple[bool, str, Optional[str]]:
        query = dsl_gql(
            DSLMutation(
                self.ds.StandaloneMutation.stageTransaction.args(
                    payload=signed_tx.hex()
                )
            )
        )
        result = self.client.execute(query)
        if "errors" in result:
            return False, result["errors"][0]["message"], None
        return True, "", result["stageTransaction"]
