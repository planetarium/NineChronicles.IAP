import json
import os
from typing import List

import requests
from sqlalchemy import select, desc

from common._crypto import Account
from common._graphql import GQL
from common.models.sign import SignHistory
from common.utils.receipt import PlanetID
from schema.sqs import SQSMessage


class BaseController:
    def __init__(self, sess, account: Account, gql: GQL):
        self.sess = sess
        self.account = account
        self.gql = gql
        self.main_planet = PlanetID.ODIN if os.environ.get("STAGE") == "mainnet" else PlanetID.ODIN_INTERNAL
        self.planet_dict = {}
        self.gql_url = ""
        try:
            resp = requests.get(os.environ.get("PLANET_URL"))
            data = resp.json()
            for planet in data:
                if PlanetID(bytes(planet["id"], "utf-8")) == self.main_planet:
                    self.gql_url = planet["rpcEndpoints"]["headless.gql"][0]
                    self.gql.reset(self.gql_url)
                    self.planet_dict = {
                        PlanetID(bytes(k, "utf-8")): v for k, v in planet["bridges"].items()
                    }
        except:
            # Fail over
            self.planet_dict = json.loads(os.environ.get("BRIDGE_DATA", "{}"))

    @property
    def next_nonce(self) -> int:
        next_nonce = self.gql.get_next_nonce(self.account.address)
        prev_nonce = self.sess.scalar(select(SignHistory.nonce).order_by(desc(SignHistory.nonce)).limit(1))
        return max(next_nonce, (-1 if prev_nonce is None else prev_nonce) + 1)

    def collect(self, message: SQSMessage):
        raise NotImplementedError

    def process(self, history_list: List[SignHistory]):
        raise NotImplementedError
