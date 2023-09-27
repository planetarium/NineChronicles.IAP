from typing import List

from sqlalchemy import select, desc

from common._crypto import Account
from common._graphql import GQL
from common.models.sign import SignHistory
from schema.sqs import SQSMessage


class BaseController:
    def __init__(self, sess, account: Account, gql: GQL):
        self.sess = sess
        self.account = account
        self.gql = gql

    @property
    def next_nonce(self) -> int:
        next_nonce = self.gql.get_next_nonce(self.account.address)
        prev_nonce = self.sess.scalar(select(SignHistory.nonce).order_by(desc(SignHistory.nonce)).limit(1))
        return max(next_nonce, (-1 if prev_nonce is None else prev_nonce) + 1)

    def collect(self, message: SQSMessage):
        raise NotImplementedError

    def process(self, history_list: List[SignHistory]):
        raise NotImplementedError
