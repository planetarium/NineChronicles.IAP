import logging
import os
from typing import Union, Dict, Any, Tuple, Optional

from gql import Client
from gql.dsl import DSLSchema, dsl_gql, DSLQuery, DSLMutation
from gql.transport.requests import RequestsHTTPTransport
from graphql import DocumentNode, ExecutionResult

from common.consts import CURRENCY_LIST


class GQL:
    def __init__(self, url: str = f"{os.environ.get('HEADLESS')}/graphql"):
        self._url = None
        self.client = None
        self.ds = None
        self.reset(url)

    def reset(self, url: str):
        self._url = url
        transport = RequestsHTTPTransport(url=self._url, verify=True, retries=2)
        self.client = Client(transport=transport, fetch_schema_from_transport=True)
        with self.client as _:
            assert self.client.schema is not None
            self.ds = DSLSchema(self.client.schema)

    def execute(self, query: DocumentNode) -> Union[Dict[str, Any], ExecutionResult]:
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
        resp = self.execute(query)

        if "errors" in resp:
            logging.error(f"GQL failed to get next Nonce: {resp['errors']}")
            return -1

        return resp["transaction"]["nextTxNonce"]

    def _unload_from_garage(self, **kwargs) -> bytes:
        fav_data = kwargs.get("fav_data")
        avatar_addr = kwargs.get("avatar_addr")
        item_data = kwargs.get("item_data")
        memo = kwargs.get("memo")

        if not fav_data and not item_data:
            raise ValueError("Nothing to unload")

        query = dsl_gql(
            DSLQuery(
                self.ds.StandaloneQuery.actionQuery.select(
                    self.ds.ActionQuery.unloadFromMyGarages.args(
                        recipientAvatarAddr=avatar_addr,
                        fungibleAssetValues=fav_data,
                        fungibleIdAndCounts=item_data,
                        memo=memo,
                    )
                )
            )
        )
        result = self.execute(query)
        return bytes.fromhex(result["actionQuery"]["unloadFromMyGarages"])

    def _transfer_asset(self, **kwargs) -> bytes:
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
                self.ds.StandaloneQuery.actionQuery.args.select(
                    self.ds.ActionQuery.transferAsset.args(
                        sender=sender, recipient=recipient, currency=currency, amount=amount, memo=memo
                    )
                )
            )
        )
        result = self.execute(query)
        return bytes.fromhex(result["actionQuery"]["transferAsset"])

    def create_unsigned_tx(self, plain_value: bytes, pubkey: bytes, nonce: int) -> bytes:
        query = dsl_gql(
            DSLQuery(
                self.ds.StandaloneQuery.transaction.select(
                    self.ds.TransactionHeadlessQuery.unsignedTransaction.args(
                        publicKey=pubkey.hex(),
                        plainValue=plain_value.hex(),
                        nonce=nonce,
                    )
                )
            )
        )
        resp = self.execute(query)
        return bytes.fromhex(resp["transaction"]["unsignedTransaction"])

    def create_action(self, action_type: str, pubkey: bytes, nonce: int, tx: bool, **kwargs) -> bytes:
        fn = getattr(self, f"_{action_type}")
        if not fn:
            raise ValueError(f"Action named {action_type} does not exists.")

        plain_value = fn(**kwargs)
        if tx:
            return self.create_unsigned_tx(plain_value, pubkey, nonce)
        else:
            return plain_value

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
        result = self.execute(query)
        return bytes.fromhex(result["transaction"]["signTransaction"])

    def stage(self, signed_tx: bytes) -> Tuple[bool, str, Optional[str]]:
        query = dsl_gql(
            DSLMutation(
                self.ds.StandaloneMutation.stageTransaction.args(
                    payload=signed_tx.hex()
                )
            )
        )
        result = self.execute(query)
        if "errors" in result:
            return False, result["errors"][0]["message"], None
        return True, "", result["stageTransaction"]
