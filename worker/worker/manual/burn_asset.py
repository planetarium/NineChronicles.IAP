# NOTE: Use this lambda function by executing manually in AWS console.
import os
from datetime import timedelta, datetime

from common import logger
from common._crypto import Account
from common._graphql import GQL
from common.utils.aws import fetch_parameter, fetch_kms_key_id
from common.utils.receipt import PlanetID
from common.utils.transaction import create_unsigned_tx, append_signature_to_unsigned_tx
from lib9c.actions.burn_asset import BurnAsset
from lib9c.models.fungible_asset_value import FungibleAssetValue

# NOTE: Set these values by manual from here
PLANET_ID = PlanetID.XXX
GQL_URL = "https://example.com/graphql"  # Use GQL host of desired chain
USE_ADHOC = True
#  to here

HEADLESS_GQL_JWT_SECRET = fetch_parameter(
    os.environ.get("REGION_NAME"),
    f"{os.environ.get('STAGE')}_9c_IAP_HEADLESS_GQL_JWT_SECRET",
    True
)["Value"]

DICT_HEADER = ["nonce", "owner", "amount", "memo"]
"""
--- Valid sample of event data
[
    3, 
    "0xDbF4c6d0D7C74D390fADae680f2144D885c878df",
    ["SOULSTONE_1001", 0, 100],
    "Burn by transfer to heimdall"
]
"""


def burn_asset(event, context):
    gql = GQL(GQL_URL, HEADLESS_GQL_JWT_SECRET)
    account = Account(fetch_kms_key_id(os.environ.get("STAGE"), os.environ.get("REGION_NAME"), adhoc=USE_ADHOC))
    data = dict(zip(DICT_HEADER, event))

    nonce = data["nonce"]
    amt = data["amount"]
    amount = FungibleAssetValue.from_raw_data(ticker=amt[0], decimal_places=amt[1], amount=amt[2])
    action = BurnAsset(owner=data["owner"], amount=amount, memo=data["memo"])
    utx = create_unsigned_tx(planet_id=PLANET_ID, public_key=account.pubkey.hex(), address=account.address, nonce=nonce,
                             plain_value=action.plain_value, timestamp=datetime.utcnow() + timedelta(days=1)
                             )
    signature = account.sign_tx(utx)
    signed_tx = append_signature_to_unsigned_tx(utx, signature)
    success, message, tx_id = gql.stage(signed_tx)

    logger.info(f"{success}::'{message}'::{tx_id} with nonce {nonce}")
    logger.debug(signed_tx.hex())
    return success, message, tx_id, nonce, signed_tx.hex()
