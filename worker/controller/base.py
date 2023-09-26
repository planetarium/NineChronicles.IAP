from common._crypto import Account
from common._graphql import GQL
from worker.schema.sqs import SQSMessage


class BaseController:
    def __init__(self, sess, message: SQSMessage, account: Account, gql: GQL):
        self.sess = sess
        self.message = message
        self.account = account
        self.gql = gql

    def collect(self):
        raise NotImplementedError

    def process(self):
        raise NotImplementedError
