import json
from typing import List

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from common import logger
from common._crypto import Account
from common._graphql import GQL
from common.models.product import Product
from common.models.receipt import Receipt
from common.models.sign import SignHistory
from controller.base import BaseController
from schema.sqs import SQSMessage


class IAPController(BaseController):
    def __init__(self, sess, account: Account, gql: GQL, **kwargs):
        super().__init__(sess, account, gql)

    def collect(self, message: SQSMessage) -> List[SignHistory]:
        nonce = self.next_nonce
        history_list = []
        uuid_list = [x.body.get("data", {}).get("uuid") for x in message.Records
                     if x.body.get("data", {}).get("uuid") is not None]
        receipt_dict = {str(x.uuid): x for x in self.sess.scalars(select(Receipt).where(Receipt.uuid.in_(uuid_list)))}
        prev_collections = [str(x) for x in self.sess.scalars(select(SignHistory.uuid)).fetchall()]

        for i, record in enumerate(message.Records):
            if record.body["type"] != "iap":
                logger.debug(f"{record.body['uuid']} is not type of iap. Skip.")
                continue

            if record.body["uuid"] in prev_collections:
                logger.warning(f"{record.body['uuid']} already added to history. Skip.")
                continue

            data = record.body.get("data", {})
            if not data:
                logger.error(f"No request data found: {record.body}")
                continue

            receipt = receipt_dict.get(data.get("uuid"))
            if not receipt:
                msg = f"{data.get('uuid')} not found in receipt history"
                logger.error(msg)
                continue

            history_list.append(SignHistory(
                uuid=record.body["uuid"],
                request_type=record.body["type"],
                data=json.dumps(record.body.get("data", {})),
                nonce=nonce
            ))
            nonce += 1

        self.sess.add_all(history_list)
        self.sess.commit()
        # self.sess.refresh_all(history_list)
        logger.info(f"{len(history_list)} IAP requests collected. Next nonce is {nonce}")
        return history_list

    def process(self, history_list: List[SignHistory]):
        for history in history_list:
            if history.plain_value is not None:
                logger.info(f"History #{history.id} has already been processed. Please check plain value and nonce.")
                continue

            request_data = json.loads(history.data)
            if not request_data:
                history.plain_value = ""
                history.tx_id = ""
                continue

            product = self.sess.scalar(
                select(Product)
                .options(joinedload(Product.fav_list)).options(joinedload(Product.fungible_item_list))
                .where(Product.id == request_data.get("product_id"))
            )

            fav_data = [{
                "balanceAddr": request_data.get("agent_addr"),
                "fungibleAssetValue": {
                    "currency": x.currency.name,
                    "majorUnit": x.amount,
                    "minorUnit": 0
                }
            } for x in product.fav_list]

            item_data = [{
                "fungibleId": x.fungible_item_id,
                "count": x.amount
            } for x in product.fungible_item_list]

            plain_value = self.gql.create_action(
                "unload_from_garage", pubkey=self.account.pubkey, nonce=history.nonce, tx=False,
                fav_data=fav_data, avatar_addr=request_data.get("avatar_addr"), item_data=item_data
            )
            unsigned_tx = self.gql.create_unsigned_tx(plain_value, pubkey=self.account.pubkey, nonce=history.nonce)
            signature = self.account.sign_tx(unsigned_tx)
            signed_tx = self.gql.sign(unsigned_tx, signature)
            success, msg, tx_id = self.gql.stage(signed_tx)
            history.plain_value = plain_value.hex()
            history.tx_id = tx_id
            # Staged data should be recorded at the moment
            self.sess.add(history)
            self.sess.commit()
            logger.info(f"Request {history.uuid} has been treated.")
