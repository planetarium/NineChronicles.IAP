from sqlalchemy import select

from common import logger
from common._crypto import Account
from common._graphql import GQL
from common.models.receipt import Receipt
from worker.controller.base import BaseController
from worker.schema.sqs import SQSMessage


class IAPController(BaseController):
    def __init__(self, sess, message: SQSMessage, account: Account, gql: GQL, **kwargs):
        super().__init__(sess, message, account, gql)

    def collect(self):
        uuid_list = [x.body.get("uuid") for x in self.message.Records if x.body.get("uuid") is not None]
        receipt_dict = {str(x.uuid): x for x in self.sess.scalars(select(Receipt).where(Receipt.uuid.in_(uuid_list)))}
        for i, record in enumerate(self.message.Records):
            if record.get("type") != "iap":
                continue
            data = record.body.get("data", {})
            if not data:
                logger.error(f"No request data found: {record.body}")
                continue

            receipt = receipt_dict.get(data.get("uuid"))
            if not receipt:
                msg = f"{data.get('uuid')} not found in receipt history"
                logger.error(msg)
                return False, msg, None

    def process(self):
        pass
